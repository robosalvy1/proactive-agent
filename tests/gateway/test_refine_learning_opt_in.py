"""Messaging /refine requests run explicitly even when periodic learning is off."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gateway.slash_commands_goals import GatewayGoalCommandsMixin
from run_agent import AIAgent


@pytest.mark.asyncio
@pytest.mark.parametrize("focus", ["", "save the verified workflow"])
async def test_messaging_refine_bypasses_automatic_review_opt_in(monkeypatch, focus):
    """The real command handler reaches the spawn seam with explicit user authority."""
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: {
        "auxiliary": {"background_review": {"enabled": False}},
    })
    agent = SimpleNamespace(
        _session_messages=[{"role": "user", "content": "a verified workflow"}],
        valid_tool_names={"memory", "skill_manage"}, _spawn_background_review_now=Mock(),
    )
    agent._spawn_background_review = lambda **kwargs: AIAgent._spawn_background_review(agent, **kwargs)
    runner = SimpleNamespace(_idle_cached_agent_or_error=lambda *_args: ("test", agent, None))
    event = SimpleNamespace(get_command_args=lambda: focus)

    await GatewayGoalCommandsMixin._handle_refine_command(runner, event)

    agent._spawn_background_review_now.assert_called_once()
    request = agent._spawn_background_review_now.call_args.kwargs
    assert request["explicit"] is True
    assert request["focus"] == (focus or None)
