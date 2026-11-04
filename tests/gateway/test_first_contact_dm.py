"""Personalization starts in messaging even after CLI setup or prior sessions."""

from unittest.mock import AsyncMock

import hermes_yaml as yaml
import pytest

from gateway.config import GatewayConfig, Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource, SessionStore


# Include bundled plugin adapters as well as built-ins, so new messaging apps
# exercise the shared onboarding path without adding a platform allowlist.
_MESSAGING_PLATFORMS = sorted(
    ({platform.value for platform in Platform} | Platform._scan_bundled_plugin_platforms()[0])
    - {"local", "webhook"}
)


def _runner(tmp_path, monkeypatch):
    """Bind a minimal runner to disposable state and a fake messaging transport."""
    monkeypatch.setattr("gateway.run._hermes_home", tmp_path)
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "home")
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig()
    runner.session_store = SessionStore(sessions_dir=tmp_path / "sessions", config=runner.config)
    runner._deliver_platform_notice = AsyncMock()
    return runner


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_name", _MESSAGING_PLATFORMS)
async def test_first_dm_gets_personalization_once_after_cli_use(tmp_path, monkeypatch, platform_name):
    """Exercise every discovered adapter without an onboarding platform allowlist."""
    from gateway.messaging_onboarding import MESSAGING_PERSONALIZATION_FLAG, personalization_directive

    (tmp_path / "config.yaml").write_text("model: test\n", encoding="utf-8")
    runner = _runner(tmp_path, monkeypatch)
    runner.session_store.has_any_sessions = lambda: True
    source = SessionSource(platform=Platform(platform_name), chat_id="dm", user_id="u", chat_type="dm")

    first: list[str] = []
    await runner._hmwa_first_contact_notes(source, [], first)
    second: list[str] = []
    await runner._hmwa_first_contact_notes(source, [], second)

    assert first == [personalization_directive(tmp_path)]
    assert second == []
    seen = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["onboarding"]["seen"]
    assert seen[MESSAGING_PERSONALIZATION_FLAG] is True


@pytest.mark.asyncio
async def test_switching_apps_after_restart_does_not_repeat_onboarding(tmp_path, monkeypatch):
    """The profile claim survives a new runner and a different messaging transport."""
    runner = _runner(tmp_path, monkeypatch)
    notes = []
    await runner._hmwa_first_contact_notes(
        SessionSource(platform=Platform.DISCORD, chat_id="first", user_id="u", chat_type="dm"),
        [], notes,
    )
    assert len(notes) == 1

    restarted = _runner(tmp_path, monkeypatch)
    notes = []
    await restarted._hmwa_first_contact_notes(
        SessionSource(platform=Platform.SIGNAL, chat_id="second", user_id="u", chat_type="dm"),
        [], notes,
    )
    assert notes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type,platform,history,internal", [
    ("group", Platform.TELEGRAM, [], False),
    ("dm", Platform.LOCAL, [], False),
    ("dm", Platform.WEBHOOK, [], False),
    ("dm", Platform.TELEGRAM, [{"role": "user", "content": "earlier"}], False),
    ("dm", Platform.TELEGRAM, [], True),
])
async def test_non_first_human_dm_does_not_start_personalization(
    tmp_path, monkeypatch, chat_type, platform, history, internal,
):
    """Excluded events must not mutate the profile onboarding state."""
    runner = _runner(tmp_path, monkeypatch)
    source = SessionSource(platform=platform, chat_id="chat", user_id="u", chat_type=chat_type)
    notes = []
    await runner._hmwa_first_contact_notes(source, history, notes, internal=internal)
    assert notes == []
    assert not (tmp_path / "config.yaml").exists()


@pytest.mark.asyncio
async def test_off_disables_personalization_without_writing_config(tmp_path, monkeypatch):
    """Explicit opt-out leaves both the offer and the existing config untouched."""
    path = tmp_path / "config.yaml"
    original = "onboarding:\n  profile_build: 'off'\n"
    path.write_text(original)
    runner = _runner(tmp_path, monkeypatch)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="dm", user_id="u", chat_type="dm")
    notes = []
    await runner._hmwa_first_contact_notes(source, [], notes)
    assert notes == []
    assert path.read_text() == original


@pytest.mark.asyncio
async def test_routed_profile_owns_the_offer_and_name_destinations(tmp_path, monkeypatch):
    """A routed conversation must never personalize the launch profile."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    runner = _runner(tmp_path, monkeypatch)
    routed = tmp_path / "profiles" / "other"
    routed.mkdir(parents=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="dm", user_id="u", chat_type="dm")
    notes = []
    token = set_hermes_home_override(str(routed))
    try:
        await runner._hmwa_first_contact_notes(source, [], notes)
    finally:
        reset_hermes_home_override(token)

    assert len(notes) == 1
    assert str(routed / "USER_NAME.txt") in notes[0]
    assert str(routed / "AGENT_NAME.txt") in notes[0]
    assert (routed / "config.yaml").exists()
    assert not (tmp_path / "config.yaml").exists()
