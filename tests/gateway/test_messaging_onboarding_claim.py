"""Onboarding claims survive stale reads, bot messages and refused preparation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.messaging_onboarding import first_messaging_note
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from hermes_yaml import safe_load


def test_stale_config_cannot_claim_an_already_saved_offer(tmp_path):
    """An old config snapshot must not bypass the durable profile flag."""
    path = tmp_path / 'config.yaml'
    assert first_messaging_note({}, path) is not None
    assert first_messaging_note({}, path) is None


def test_concurrent_claims_offer_only_once(tmp_path):
    """Competing callers share the persisted claim instead of duplicating offers."""
    path = tmp_path / 'config.yaml'
    start = Barrier(2)

    def claim():
        """Start both stale-snapshot callers together without timing sleeps."""
        start.wait(timeout=10)
        return first_messaging_note({}, path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(note is not None for note in results) == 1
    assert safe_load(path.read_text())['onboarding']['seen']['messaging_personalization_offered'] is True


def _runner(tmp_path, monkeypatch):
    """Bind a minimal runner to disposable state and a fake messaging transport."""
    monkeypatch.setattr('gateway.run._hermes_home', tmp_path)
    monkeypatch.setenv('TELEGRAM_HOME_CHANNEL', 'home')
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig()
    runner._deliver_platform_notice = AsyncMock()
    return runner


@pytest.mark.asyncio
async def test_bot_dm_does_not_consume_the_human_offer(tmp_path, monkeypatch):
    """An admitted bot message must leave onboarding available for a human."""
    runner = _runner(tmp_path, monkeypatch)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='dm', user_id='bot', is_bot=True)
    notes = []
    await runner._hmwa_first_contact_notes(source, [], notes)
    assert notes == []
    assert not (tmp_path / 'config.yaml').exists()

    source.is_bot = False
    await runner._hmwa_first_contact_notes(source, [], notes)
    assert len(notes) == 1


@pytest.mark.asyncio
async def test_refused_input_leaves_onboarding_for_the_next_accepted_turn(tmp_path, monkeypatch):
    """Refused input must neither stage a directive nor consume its claim."""
    runner = _runner(tmp_path, monkeypatch)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='dm', user_id='user')
    event = MessageEvent(text='read @file:blocked.txt', source=source)
    event._gateway_turn_refusal = 'Reference refused'
    entry = SimpleNamespace(yolo=None, session_id='sid', session_key='key')
    runner._hmwa_open_session = AsyncMock(return_value=(False, True))
    monkeypatch.setattr('gateway.run_turn_prepare.build_session_context', lambda *_: None)
    runner._set_session_env = lambda _: []
    runner._pinned_session_context_prompt = lambda *a, **kw: ''
    runner._hmwa_acquire_turn_lease = AsyncMock()
    runner._mark_durable_active_turn = AsyncMock()
    runner.session_store = object()
    runner._async_session_store = SimpleNamespace(
        _store=runner.session_store, load_transcript=AsyncMock(return_value=[]),
    )
    runner._hmwa_run_session_hygiene = AsyncMock(return_value=[])
    runner._voice_channel_sidecar_note = lambda *a: None
    runner._prepare_profile_scoped_inbound_message_text = AsyncMock(side_effect=[None, 'hi'])
    runner._set_pending_turn_sidecar_notes = Mock()
    runner._delivery_adapter_for = lambda _: None
    runner._bind_adapter_run_generation = lambda *a: None

    reply, _ = await runner._hmwa_prepare_turn(event, source, entry, 'key', 'key', 1)
    assert reply == 'Reference refused'
    assert not (tmp_path / 'config.yaml').exists()
    runner._set_pending_turn_sidecar_notes.assert_not_called()

    event.text = 'hi'
    prepared, _ = await runner._hmwa_prepare_turn(event, source, entry, 'key', 'key', 2)
    assert prepared.message_text == 'hi'
    notes = runner._set_pending_turn_sidecar_notes.call_args.args[1]
    assert len(notes) == 1
    assert (tmp_path / 'config.yaml').exists()


def test_stale_snapshot_does_not_override_a_persisted_opt_out(tmp_path):
    """The locked config read must honor a newer user opt-out."""
    path = tmp_path / 'config.yaml'
    original = "onboarding:\n  profile_build: 'off'\n"
    path.write_text(original)
    assert first_messaging_note({}, path) is None
    assert path.read_text() == original


def test_unreadable_config_does_not_abort_the_turn_or_overwrite_it(tmp_path):
    """Malformed config must be preserved while optional onboarding is omitted."""
    path = tmp_path / 'config.yaml'
    original = 'onboarding: [broken yaml'
    path.write_text(original)
    assert first_messaging_note({}, path) is None
    assert path.read_text() == original
