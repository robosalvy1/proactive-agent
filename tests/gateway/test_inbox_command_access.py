"""/inbox on messaging platforms: profile-wide attention state is only for an operator's DM."""

import threading
from types import SimpleNamespace

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _runner(extra=None):
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(platforms={
        Platform.TELEGRAM: PlatformConfig(enabled=True, token="token", extra=extra or {})})
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    return runner


def _event(*, chat_type="dm", chat_id="chat-1", user_id="user-1", args=""):
    source = SessionSource(platform=Platform.TELEGRAM, chat_id=chat_id, chat_type=chat_type, user_id=user_id)
    return SimpleNamespace(source=source, get_command_args=lambda: args)


@pytest.fixture
def handled(monkeypatch):
    calls = []
    monkeypatch.setattr("hermes_cli.inbox_cmd.handle_inbox_command",
                        lambda rest: calls.append(rest) or "inbox output")
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type", ["group", "channel", "thread"])
async def test_shared_chats_are_refused(handled, chat_type):
    reply = await _runner()._handle_inbox_command(_event(chat_type=chat_type, args="sources remove 1"))
    assert "direct message" in reply and handled == []


@pytest.mark.asyncio
async def test_non_operator_dm_is_refused_when_admins_are_configured(handled):
    runner = _runner({"allow_admin_from": ["operator"]})
    assert "operator" in await runner._handle_inbox_command(_event(user_id="other"))
    assert handled == []
    assert await runner._handle_inbox_command(_event(user_id="operator", args="log")) == "inbox output"
    assert handled == ["log"]


@pytest.mark.asyncio
async def test_dm_without_admin_policy_reaches_the_handler(handled):
    assert await _runner()._handle_inbox_command(_event(args="watch")) == "inbox output"
