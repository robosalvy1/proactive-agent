"""The legacy sidecar exposes Home without building an agent or submitting a prompt."""
from hermes_state import SessionDB
from tui_gateway import server


def test_home_action_resolves_from_the_profile_store(tmp_path, monkeypatch):
    with SessionDB(tmp_path / "state.db") as db:
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_profile_home", lambda _profile: None)
        handler = server._methods["home.action"]
        first = handler(1, {})
        assert "result" in first, first
        assert handler(2, {})["result"]["session_id"] == first["result"]["session_id"]
        assert db.message_count() == 0
