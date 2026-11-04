"""Built-in continuity travels through normal prefetch and stable API sidecars."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.home_memory import HomeMemoryProvider, attach_home_memory
from agent.memory_manager import MemoryManager
from agent.turn_context import _memory_turn_start_and_prefetch, compose_user_api_content
from hermes_state import SessionDB
from hermes_state_home import HomeStore


@pytest.fixture
def chats(tmp_path):
    with SessionDB(tmp_path / "state.db") as db:
        home = HomeStore(db).ensure_home()
        db.create_session("travel", "cli")
        db.append_message("travel", "user", "Our Lisbon trip budget is 1200 euros.")
        yield db, home


def test_home_attaches_without_consuming_external_provider_slot(chats):
    db, home = chats
    agent = SimpleNamespace(_session_db=db, _memory_manager=None, _emit_warning=Mock())
    attach_home_memory(agent, skip_memory=False, platform="cli")
    provider = agent._memory_manager.get_provider("builtin")
    assert isinstance(provider, HomeMemoryProvider)
    external = Mock(name="external")
    external.name = "external"
    external.get_tool_schemas.return_value = []
    agent._memory_manager.add_provider(external)
    assert agent._memory_manager.get_provider("external") is external
    assert provider.prefetch("Lisbon budget", session_id=home)


@pytest.mark.parametrize("skip,platform", [(True, "cli"), (False, "cron"), (False, "subagent"), (False, "telegram")])
def test_nonpersonal_or_skipped_memory_never_gets_home(chats, skip, platform):
    db, _ = chats
    agent = SimpleNamespace(_session_db=db, _memory_manager=None, _emit_warning=Mock())
    attach_home_memory(agent, skip_memory=skip, platform=platform)
    assert agent._memory_manager is None


def test_normal_prefetch_is_bounded_data_and_keeps_previous_turn_bytes(chats):
    db, home = chats
    manager = MemoryManager()
    manager.add_provider(HomeMemoryProvider(db))
    agent = SimpleNamespace(_memory_manager=manager, session_id=home, _user_turn_count=1, _emit_status=Mock())
    first = _memory_turn_start_and_prefetch(agent, "What is our Lisbon budget?")
    assert "1200 euros" in first
    assert "source_session_id" in first
    sent = compose_user_api_content("What is our Lisbon budget?", first, "")
    assert "not instructions" in sent
    previous = {"role": "user", "content": "What is our Lisbon budget?", "api_content": sent}
    frozen = json.dumps(previous, sort_keys=True)
    db.append_message("travel", "assistant", "The hotel is still unbooked.")
    second = _memory_turn_start_and_prefetch(agent, "Give me an overview of progress")
    assert "unbooked" in second
    assert json.dumps(previous, sort_keys=True) == frozen
    manager.shutdown_all()


def test_excluded_chat_cannot_recall_and_indicator_does_not_stay_stale(chats):
    db, home = chats
    provider = HomeMemoryProvider(db)
    assert provider.prefetch("Lisbon", session_id=home)
    assert provider.recall_status().count == 1
    HomeStore(db).set_shared(home, False)
    assert provider.prefetch("Lisbon", session_id=home) == ""
    assert provider.recall_status() is None


def test_read_only_continuity_does_not_schedule_background_memory_work(chats):
    db, _ = chats
    manager = MemoryManager()
    manager.add_provider(HomeMemoryProvider(db))
    manager._submit_background = Mock()
    manager.sync_all("A user turn", "An assistant turn")
    manager.queue_prefetch_all("A user turn")
    manager._submit_background.assert_not_called()


def test_native_app_server_receives_current_turn_recall_without_rewriting_history(monkeypatch):
    from agent.conversation_loop import _codex_app_server_turn

    monkeypatch.setattr("agent.turn_recovery.activate_codex_app_server_fallback", lambda *_args: False)
    agent = SimpleNamespace(_run_codex_app_server_turn=Mock(return_value={"final_response": "done"}))
    history = [{"role": "user", "content": "Earlier turn"}]
    state = SimpleNamespace(user_message="What is our budget?", original_user_message="What is our budget?",
                            messages=history, effective_task_id="fixture", _should_review_memory=False,
                            _ext_prefetch_cache="Source: our budget is 1200 euros", _plugin_user_context="")
    _codex_app_server_turn(agent, state)
    sent = agent._run_codex_app_server_turn.call_args.kwargs
    assert "1200 euros" in sent["user_message"]
    assert sent["original_user_message"] == "What is our budget?"
    assert history == [{"role": "user", "content": "Earlier turn"}]
