"""Home reads retain transport authentication without consuming durable write receipts."""
import subprocess
import sys
import json
from types import SimpleNamespace

import psutil
import pytest


@pytest.mark.asyncio
async def test_worker_home_read_authenticates_assignment_without_write_receipts(tmp_path, monkeypatch):
    from gateway.config import Platform
    from gateway.session_authority import LiveSession, SessionAuthority
    from gateway.session_contract import Principal, SessionRef
    from gateway.session_home import handlers
    from gateway.session_worker import worker_request
    from hermes_state import SessionDB
    from hermes_state_home import HomeStore
    from hermes_state_runtime import RuntimeStoreError, begin_runtime_epoch
    from tests.hermes_state.test_worker_home import native_chat

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    db = SessionDB(tmp_path / 'state.db')
    HomeStore(db).ensure_home()
    db.create_session('owned', 'cli')
    native_chat(db, 'travel', 'human', 'Lisbon budget is 1200 euros')
    runner = SimpleNamespace(_draining=False, config=SimpleNamespace(multiplex_profiles=False),
                             _adapter_for_source=lambda source: None)
    authority = SessionAuthority(runner, profile_id='p', instance_id='owner', db=db,
                                 epoch=begin_runtime_epoch(db, instance_id='owner'))
    authority.sessions['owned'] = LiveSession(SimpleNamespace(platform=Platform.TELEGRAM, user_id='human'), 'route')
    connection = SimpleNamespace(authority=authority, actor=Principal('human', 'p', frozenset({'worker:adopt'}), 't'))
    ref = SessionRef('p', 'owned')
    child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE,  # noqa: ASYNC220 -- Popen returns immediately
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    scope = dict(profile_id='p', session_id='owned', execution_id='compute', generation=0,
                 pid=child.pid, birth=psutil.Process(child.pid).create_time(), secret='w' * 32)
    try:
        await worker_request(connection, ref, scope | {'kind': 'compute'}, operation='register')
        from hermes_state_local import POLICY_PREFIX
        db._write_sql("UPDATE sessions SET user_id='human',chat_id='owned',chat_type='dm' WHERE id='owned'")
        db._write_sql('INSERT INTO state_meta(key,value) VALUES(?,?)',
                      (POLICY_PREFIX + 'owned', json.dumps({'principal_id': 'human', 'session_id': 'owned',
                                                           'policy': {'source': 'cli'}})))
        recall = handlers(connection)['worker.home.recall']
        params = scope | dict(epoch=authority.epoch, query='Lisbon', overview=False)
        assert '1200 euros' in (await recall(ref, params))['context']
        assert db._read_one("SELECT last_sequence FROM worker_executions WHERE execution_id='compute'")[0] == 0
        for override, error in [({'secret': 'x' * 32}, 'permission_denied'),
                                ({'profile_id': 'other'}, 'profile_mismatch'),
                                ({'epoch': authority.epoch + 1}, 'stale_epoch')]:
            with pytest.raises(RuntimeStoreError, match=error):
                await recall(ref, params | override)
        connection.actor = Principal('human', 'p', frozenset({'session:control'}), 't')
        with pytest.raises(RuntimeStoreError, match='permission_denied'):
            await recall(ref, params)
    finally:
        child.stdin.close()
        child.wait(timeout=5)
        db.close()
