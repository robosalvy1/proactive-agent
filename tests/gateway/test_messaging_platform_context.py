"""Future adapters inherit profile onboarding and current-app prompt context."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platform_registry import PlatformEntry, PlatformRegistry
from gateway.run_turn_prepare import GatewayTurnPrepareMixin
from gateway.session import SessionSource, build_session_context, build_session_context_prompt


@pytest.mark.asyncio
async def test_future_adapters_inherit_onboarding_and_identify_the_current_app(tmp_path, monkeypatch):
    """Runtime registration alone supplies onboarding and current-app context."""
    registry = PlatformRegistry()
    monkeypatch.setattr("gateway.platform_registry.platform_registry", registry)
    monkeypatch.setattr("gateway.run._hermes_home", tmp_path)
    config = GatewayConfig()
    runner = SimpleNamespace(config=config, _deliver_platform_notice=AsyncMock())

    # Register adapters at runtime, with no built-in enumeration or onboarding entry.
    for index, name in enumerate(("future_messenger_one", "future_messenger_two")):
        registry.register(PlatformEntry(
            name=name, label=name, adapter_factory=lambda cfg: None, check_fn=lambda: True,
        ))
        platform = Platform(name)
        source = SessionSource(platform=platform, chat_id="chat", user_id="u", chat_type="dm")
        notes = []
        await GatewayTurnPrepareMixin._hmwa_first_contact_notes(runner, source, [], notes)
        assert bool(notes) is (index == 0)

        context = build_session_context(source, config)
        prompt = build_session_context_prompt(context)
        assert f"**Source:** {name.title()} (" in prompt
        # New message identifiers must not change the cached platform context.
        later = build_session_context(replace(source, message_id="next-message"), config)
        assert build_session_context_prompt(later) == prompt

        # A fresh runner on another transport must still see the profile's latch.
        runner = SimpleNamespace(config=config, _deliver_platform_notice=AsyncMock())


def test_current_app_context_changes_with_the_transport():
    """The source label comes from this conversation rather than a prior app."""
    config = GatewayConfig()
    for platform in (Platform.TELEGRAM, Platform.SIGNAL, Platform("photon")):
        source = SessionSource(platform=platform, chat_id="chat", user_id="u", chat_type="dm")
        prompt = build_session_context_prompt(build_session_context(source, config))
        source_lines = [line for line in prompt.splitlines() if line.startswith("**Source:**")]
        assert len(source_lines) == 1
        assert source_lines[0].startswith(f"**Source:** {platform.value.title()} (")
