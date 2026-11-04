"""Existing owner housekeeping runs scoped dreams, tracks liveness, and discards cancelled work."""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from gateway.home_dreams import home_dream_chore
from gateway.session_authorities import SessionAuthorities
from hermes_state import SessionDB
from hermes_state_dreams import DreamStore
from hermes_state_home import HomeStore
from tests.waiting import async_wait_until


def prepare(db):
    HomeStore(db).ensure_home()
    db.create_session('travel', 'cli')
    db.append_message('travel', 'user', 'Prefer rail travel')
    DreamStore(db).configure(enabled=True)
    db._write_sql('UPDATE sessions SET last_activity_at=?', (time.time() - 1000,))


def response(sources):
    row = sources[0]['messages'][0]
    return json.dumps({'notes': [{'kind': 'preference', 'text': row['text'],
                                 'sources': [{'id': row['id'], 'quote': row['text']}]}]})


@pytest.mark.asyncio
async def test_idle_chore_creates_one_tracked_pass_and_never_appends_messages(tmp_path, monkeypatch):
    from gateway import run

    with SessionDB(tmp_path / 'state.db') as db:
        prepare(db)
        stop = threading.Event()
        authority = SimpleNamespace(db=db, sessions={})
        runner = SimpleNamespace(session_authority=authority, _draining=False)
        calls = []
        monkeypatch.setattr('agent.home_dream_model.reflect', lambda sources: calls.append(sources) or response(sources))
        # Run the actual housekeeping registration, suppressing unrelated chores.
        monkeypatch.setattr(run, '_housekeeping_chore', lambda label, fn: fn() if label == 'Home dream tick' else None)
        housekeeper = asyncio.create_task(asyncio.to_thread(
            run._start_gateway_housekeeping, stop, loop=asyncio.get_running_loop(), interval=3600, runner=runner))
        try:
            task = await async_wait_until(lambda: getattr(authority, '_home_dream_task', None))
            tick = home_dream_chore(runner, asyncio.get_running_loop(), stop)
            for _ in range(4):
                tick()
            await asyncio.wait_for(task, timeout=20)
        finally:
            stop.set()
            await asyncio.wait_for(housekeeper, timeout=20)
        assert len(calls) == 1
        assert len(DreamStore(db).status()['notes']) == 1
        assert db.message_count() == 1
        assert not authority._mutation_tasks


@pytest.mark.asyncio
async def test_stop_discards_response_and_physical_work_stays_tracked(tmp_path, monkeypatch):
    with SessionDB(tmp_path / 'state.db') as db:
        prepare(db)
        entered, release, stop = threading.Event(), threading.Event(), threading.Event()
        authority = SimpleNamespace(db=db, sessions={})
        runner = SimpleNamespace(session_authority=authority, _draining=False)

        def blocked(sources):
            entered.set()
            assert release.wait(20)
            return response(sources)

        monkeypatch.setattr('agent.home_dream_model.reflect', blocked)
        home_dream_chore(runner, asyncio.get_running_loop(), stop)()
        try:
            await async_wait_until(entered.is_set)
            assert authority._mutation_tasks
            stop.set()
        finally:
            release.set()
            await asyncio.wait_for(authority._home_dream_task, timeout=20)
        assert DreamStore(db).status()['notes'] == []
        assert DreamStore(db).status()['last_status'] == 'discarded'
        assert not authority._mutation_tasks


@pytest.mark.asyncio
async def test_enqueued_dream_keeps_owning_profile_after_scope_exit(tmp_path, monkeypatch):
    from hermes_constants import get_hermes_home
    from gateway.run import _profile_runtime_scope

    launch = get_hermes_home()
    homes = [tmp_path / 'a', tmp_path / 'b']
    dbs = [SessionDB(home / 'state.db') for home in homes]
    registry = SessionAuthorities(homes[0], multiplexed=True)
    authorities = []
    for home, db in zip(homes, dbs):
        prepare(db)
        authority = SimpleNamespace(db=db, sessions={}, profile_id=str(home))
        authorities.append(authority)
        registry.add(home, authority)
    runner = SimpleNamespace(session_authorities=registry, _draining=False)
    seen = []
    monkeypatch.setattr('agent.home_dream_model.reflect', lambda sources: seen.append(get_hermes_home()) or response(sources))
    try:
        tick = home_dream_chore(runner, asyncio.get_running_loop(), threading.Event())
        for home in homes:
            with _profile_runtime_scope(home):
                tick()
        assert get_hermes_home() == launch
        for authority in authorities:
            task = await async_wait_until(lambda: getattr(authority, '_home_dream_task', None))
            await asyncio.wait_for(task, timeout=20)
        assert set(seen) == set(homes)
        assert all(len(DreamStore(db).status()['notes']) == 1 for db in dbs)
        assert get_hermes_home() == launch
    finally:
        for db in dbs:
            db.close()
