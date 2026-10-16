"""Home command actions keep navigation separate from task execution."""
import pytest
from types import SimpleNamespace

from hermes_cli.home import home_action
from hermes_state import SessionDB


def test_cli_home_controls_keep_the_resumed_owner(tmp_path, monkeypatch):
    from hermes_cli.home import handle_cli_home
    from hermes_state_home import HomeStore
    from tests.hermes_state.test_worker_home import native_chat

    with SessionDB(tmp_path / 'state.db') as db:
        home = HomeStore(db).ensure_home()
        native_chat(db, 'travel', 'human', 'Lisbon budget is 1200 euros')
        cli = SimpleNamespace(_session_db=db, session_id='travel', cwd=str(tmp_path), _agent_running=False)
        output = []
        monkeypatch.setattr('hermes_cli.cli_commands_session_tools._cp', output.append)
        handle_cli_home(cli, '/home overview')
        assert '1200 euros' in output[-1]
        handle_cli_home(cli, '/home exclude')
        assert HomeStore(db, principal_id='human').recall(home, 'Lisbon') == []
        handle_cli_home(cli, '/home share')
        assert HomeStore(db, principal_id='human').recall(home, 'Lisbon')


def test_home_actions_and_overview_use_the_same_durable_store(tmp_path):
    with SessionDB(tmp_path / "state.db") as db:
        first = home_action(db, "")
        assert home_action(db, "")["session_id"] == first["session_id"]
        db.create_session("travel", "cli")
        db.append_message("travel", "user", "Lisbon budget: 1200 euros")
        assert "1200 euros" in home_action(db, "travel", "overview")["output"]
        home_action(db, "travel", "exclude")
        assert "1200 euros" not in home_action(db, "travel", "overview")["output"]
        home_action(db, "travel", "share")
        home_action(db, "travel", "off")
        assert "1200 euros" not in home_action(db, "travel", "overview")["output"]
        home_action(db, "travel", "on")
        assert "1200 euros" in home_action(db, "travel", "overview")["output"]
        with pytest.raises(ValueError, match="/home"):
            home_action(db, "travel", "invalid")
