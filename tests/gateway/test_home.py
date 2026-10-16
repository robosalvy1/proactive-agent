"""Home controls retain native transport, profile and capability boundaries."""
from types import SimpleNamespace

import pytest

from gateway.session_authority import SessionAuthority
from gateway.session_controls import AuthorityConnection
from hermes_state import SessionDB
from hermes_state_home import HomeStore
from hermes_state_runtime import begin_runtime_epoch


@pytest.fixture
def owner(tmp_path):
    with SessionDB(tmp_path / "state.db") as db:
        epoch = begin_runtime_epoch(db, instance_id="current")
        authority = SessionAuthority(SimpleNamespace(_draining=False), profile_id=str(tmp_path),
                                     instance_id="current", db=db, epoch=epoch)
        identity = {"user_id": "human", "provider": "local", "native_bootstrap": True,
                    "profile_id": str(tmp_path), "instance_id": "current"}
        yield authority, identity


@pytest.mark.asyncio
async def test_native_home_open_is_idempotent_and_does_not_start_work(owner):
    authority, identity = owner
    connection = AuthorityConnection(authority, object(), identity)
    try:
        first = await connection.dispatch({"id": 1, "method": "home.action", "params": {}})
        assert "result" in first, first
        second = await connection.dispatch({"id": 2, "method": "home.action", "params": {}})
        assert first["result"]["session_id"] == second["result"]["session_id"]
        assert HomeStore(authority.db).status()["enabled"]
        assert not authority.sessions  # navigation has not admitted a prompt or restored an agent
        assert authority.db.message_count() == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_remote_identity_cannot_enable_personal_home(owner):
    authority, identity = owner
    connection = AuthorityConnection(authority, object(), {**identity, "provider": "remote"})
    try:
        result = await connection.dispatch({"id": 1, "method": "home.action", "params": {}})
        assert result["error"]["data"]["reason"] == "permission_denied"
        assert HomeStore(authority.db).status()["enabled"] is False
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_read_only_capability_cannot_enable_home(owner):
    authority, identity = owner
    connection = AuthorityConnection(authority, object(), {**identity, "capabilities": ["session:read"]})
    try:
        result = await connection.dispatch({"id": 1, "method": "home.action", "params": {}})
        assert result["error"]["data"]["reason"] == "permission_denied"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_home_adopts_and_resets_through_real_local_conversation_receipts(tmp_path, monkeypatch):
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_local import create_local_session
    from gateway.session_local_migration import resolve_local_target
    from hermes_state_mutation_reset import reset_in_transaction
    from agent.home_memory import HomeMemoryProvider

    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {"platform_toolsets": {"cli": []}})
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda *_args: "fixture")
    store = SessionStore(tmp_path / "sessions", GatewayConfig())
    runner = SimpleNamespace(session_store=store, _session_db=store._db, adapters={}, _draining=False)
    authority = await initialize_session_authority(runner, profile_id=str(tmp_path), instance_id="fixture")
    connection = AuthorityConnection(authority, object(), {"user_id": "human", "provider": "local",
        "native_bootstrap": True, "profile_id": str(tmp_path), "instance_id": "fixture"})
    try:
        result = await connection.dispatch({"id": 1, "method": "home.action", "params": {}})
        home = result["result"]["session_id"]
        ref = resolve_local_target(authority, connection.actor, home)
        assert ref.session_id == home
        assert HomeStore(authority.db, principal_id=connection.actor.subject).ensure_home() == home
        side = create_local_session(authority, connection.actor, {"source": "cli", "cwd": str(tmp_path),
            "request_id": "side", "model": "fixture", "toolsets": []})
        authority.db.append_message(side.session_id, "user", "Lisbon budget is 1200 euros")
        reset = authority.db._execute_write(lambda conn: reset_in_transaction(authority.db, conn, home, {}))[1]
        target = reset["target_session_id"]
        assert target != home
        assert HomeStore(authority.db).status()["session_id"] == target
        assert "1200 euros" in HomeMemoryProvider(authority.db).prefetch("overview of progress", session_id=target)
        HomeStore(authority.db, principal_id=connection.actor.subject).set_shared(target, False)
        assert HomeMemoryProvider(authority.db).prefetch("Lisbon budget", session_id=target) == ""
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_private_link_controls_require_authenticated_local_owner(owner):
    from tests.hermes_state.test_home_links import messaging_chat
    from hermes_state_home_links import list_links

    authority, identity = owner
    messaging_chat(authority.db)
    native = AuthorityConnection(authority, object(), identity)
    remote = AuthorityConnection(authority, object(), {**identity, 'provider': 'remote'})
    stranger = AuthorityConnection(authority, object(), {**identity, 'user_id': 'other-local-user'})
    try:
        opened = await native.dispatch({'id': 1, 'method': 'home.action', 'params': {}})
        assert 'result' in opened
        denied = await remote.dispatch({'id': 2, 'method': 'home.action', 'params': {'action': 'link dm'}})
        assert denied['error']['data']['reason'] == 'permission_denied'
        linked = await native.dispatch({'id': 3, 'method': 'home.action', 'params': {'action': 'link dm'}})
        assert 'result' in linked, linked
        for action in ('link dm', 'unlink dm'):
            refused = await stranger.dispatch({'id': 4, 'method': 'home.action', 'params': {'action': action}})
            assert refused['error']['data']['reason'] == 'invalid_params'
        assert len(list_links(HomeStore(authority.db, principal_id=native.actor.subject))) == 1
        unlinked = await native.dispatch({'id': 5, 'method': 'home.action', 'params': {'action': 'unlink dm'}})
        assert 'result' in unlinked
        assert list_links(HomeStore(authority.db, principal_id=native.actor.subject)) == []
    finally:
        await native.close()
        await remote.close()
        await stranger.close()
