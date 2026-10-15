"""Home command actions keep navigation separate from task execution."""
import pytest

from hermes_cli.home import home_action
from hermes_state import SessionDB


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
