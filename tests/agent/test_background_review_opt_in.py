"""Automatic learning requires an opt-in; explicit learning remains available."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.background_review import load_background_review_settings
from run_agent import AIAgent


@pytest.mark.parametrize("config", [
    {}, {"auxiliary": None}, {"auxiliary": []},
    {"auxiliary": {"background_review": None}},
    {"auxiliary": {"background_review": []}},
    {"auxiliary": {"background_review": {}}},
])
def test_missing_or_malformed_review_block_does_not_spawn(monkeypatch, config):
    """Presence-sensitive loaders cannot accidentally opt a profile into review."""
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: config)
    agent = SimpleNamespace(_spawn_background_review_now=Mock())
    AIAgent._spawn_background_review(agent, [{"role": "user", "content": "hello"}], review_memory=True)
    agent._spawn_background_review_now.assert_not_called()


@pytest.mark.parametrize("value, expected", [
    (True, True), (False, False), ("true", True), ("on", True),
    ("false", False), ("off", False), (1, True), (0, False),
    (None, False), ("invalid", False), (2, False), (-1, False),
    ([True], False), ({"enabled": True}, False), (1.0, False),
])
def test_only_explicit_boolean_opt_in_enables_review(monkeypatch, value, expected):
    """Malformed truthy objects must not authorize extra model calls."""
    cfg = {"auxiliary": {"background_review": {"enabled": value}}}
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: cfg)
    assert load_background_review_settings()[0] is expected


@pytest.mark.parametrize("contents, expected", [
    (None, False), ("auxiliary:\n  background_review:\n    enabled: true\n", True),
    ("auxiliary:\n  background_review:\n    enabled: false\n", False),
])
def test_effective_config_default_and_explicit_override(tmp_path, monkeypatch, contents, expected):
    """The real merged loader and runtime agree on the opt-in default."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    if contents is not None:
        (tmp_path / "config.yaml").write_text(contents, encoding="utf-8")
    assert load_background_review_settings()[0] is expected


@pytest.mark.parametrize("focus", [None, "", "save the verified workflow"])
def test_explicit_review_runs_with_auto_disabled(monkeypatch, focus):
    """An argument-free /refine is still a user-requested review."""
    cfg = {"auxiliary": {"background_review": {"enabled": False}}}
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: cfg)
    agent = SimpleNamespace(_spawn_background_review_now=Mock())
    AIAgent._spawn_background_review(
        agent, [{"role": "user", "content": "hello"}], review_memory=True,
        focus=focus, explicit=True,
    )
    agent._spawn_background_review_now.assert_called_once()
    assert agent._spawn_background_review_now.call_args.kwargs["explicit"] is True


def test_foreground_memory_save_remains_available(tmp_path, monkeypatch):
    """Disabling unattended review does not disable requested durable memory writes."""
    from tools.memory_tool import MemoryStore, memory_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "auxiliary:\n  background_review:\n    enabled: false\n", encoding="utf-8")
    assert load_background_review_settings()[0] is False
    store = MemoryStore()
    store.load_from_disk()
    result = json.loads(memory_tool(action="add", target="user", content="Prefers brief replies", store=store))
    assert result["success"] is True
    reloaded = MemoryStore()
    reloaded.load_from_disk()
    assert "Prefers brief replies" in reloaded._entries_for("user")


def test_deferred_review_gate_failure_does_not_spawn(monkeypatch):
    """An optional queued review needs a successful opt-in check at dispatch time."""
    from agent.review_idle_queue import ReviewIdleQueue

    queue = ReviewIdleQueue()
    queue._ensure_thread = Mock()
    agent = SimpleNamespace(_spawn_background_review_now=Mock())
    queue.enqueue(agent, "session", {"messages_snapshot": [], "task_cfg": {}})
    monkeypatch.setattr(
        "agent.background_review.load_background_review_settings",
        Mock(side_effect=RuntimeError("configuration unavailable")),
    )
    queue._dispatch(queue._pending["session"])
    agent._spawn_background_review_now.assert_not_called()
