"""The legacy sidecar exposes Home without building an agent or submitting a prompt."""
from hermes_state import SessionDB
from tui_gateway import server


def test_home_wire_accepts_argument_actions_and_bounds_input():
    import pytest
    from pydantic import ValidationError
    from tui_gateway.contracts.home import HomeActionParams

    for action in ('link CaseSensitive-ID', 'index clear', 'forget 12', 'supersede 12 28'):
        assert HomeActionParams(action=action).action == action
    with pytest.raises(ValidationError):
        HomeActionParams(action='x' * 513)


def test_home_action_resolves_from_the_profile_store(tmp_path, monkeypatch):
    with SessionDB(tmp_path / "state.db") as db:
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_profile_home", lambda _profile: None)
        handler = server._methods["home.action"]
        first = handler(1, {})
        assert "result" in first, first
        assert handler(2, {})["result"]["session_id"] == first["result"]["session_id"]
        assert db.message_count() == 0


def test_resumed_sidecar_controls_use_the_persisted_owner(tmp_path, monkeypatch):
    from hermes_state_home import HomeStore
    from tests.hermes_state.test_worker_home import native_chat

    with SessionDB(tmp_path / 'state.db') as db:
        home = HomeStore(db).ensure_home()
        native_chat(db, 'travel', 'human', 'Lisbon budget is 1200 euros')
        monkeypatch.setattr(server, '_get_db', lambda: db)
        monkeypatch.setattr(server, '_profile_home', lambda _profile: None)
        monkeypatch.setattr(server, '_sessions', {'runtime': {'session_key': 'travel', 'running': False}})
        monkeypatch.setattr(server, '_ensure_session_db_row', lambda _session: None)
        handler = server._methods['home.action']
        assert '1200 euros' in handler(1, {'session_id': 'runtime', 'action': 'overview'})['result']['output']
        assert 'result' in handler(2, {'session_id': 'runtime', 'action': 'exclude'})
        assert HomeStore(db, principal_id='human').recall(home, 'Lisbon') == []
        assert 'result' in handler(3, {'session_id': 'runtime', 'action': 'share'})
        assert HomeStore(db, principal_id='human').recall(home, 'Lisbon')
