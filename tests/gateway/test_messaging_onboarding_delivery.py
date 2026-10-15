"""Onboarding reaches proxy agents without blocking other gateway turns."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.messaging_onboarding import personalization_directive
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override
from tests.gateway.test_proxy_mode import _FakeSession, _FakeSSEResponse, _make_runner, _patch_aiohttp


@pytest.mark.asyncio
async def test_lock_wait_keeps_event_loop_responsive_and_profile_scope(tmp_path, monkeypatch):
    """An occupied claim worker must not stall the loop or lose the routed home."""
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    observed = []
    routed = tmp_path / 'routed'
    routed.mkdir()

    def held_claim(config, config_path):
        """Hold the worker until the event loop proves it can run independently."""
        observed.append((threading.get_ident(), get_hermes_home(), config_path))
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=10):
            raise TimeoutError('Claim worker was not released by the gateway loop')
        return 'profile introduction'

    monkeypatch.setattr('gateway.messaging_onboarding.first_messaging_note', held_claim)
    monkeypatch.setattr('gateway.run._hermes_home', tmp_path)
    monkeypatch.setenv('TELEGRAM_HOME_CHANNEL', 'home')
    runner = SimpleNamespace(config=GatewayConfig(), _deliver_platform_notice=AsyncMock())
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='dm', user_id='u')
    notes = []
    token = set_hermes_home_override(str(routed))
    task = asyncio.create_task(GatewayRunner._hmwa_first_contact_notes(runner, source, [], notes))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        assert len(observed) == 1
        assert observed[0][1:] == (routed, routed / 'config.yaml')
        assert observed[0][0] != threading.get_ident()
        assert not task.done()
    finally:
        release.set()
        reset_hermes_home_override(token)
        await task
    assert notes == ['profile introduction']


@pytest.mark.asyncio
async def test_proxy_forwards_onboarding_once_without_changing_transcript_text(tmp_path, monkeypatch):
    """The remote request gets the directive while local user text stays clean."""
    monkeypatch.setattr('gateway.run._hermes_home', tmp_path)
    monkeypatch.setattr('gateway.run._load_gateway_config', dict)
    monkeypatch.setenv('GATEWAY_PROXY_URL', 'http://proxy.invalid:8642')
    runner = _make_runner()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='dm', user_id='u')
    notes = []
    await runner._hmwa_first_contact_notes(source, [], notes)
    assert notes == [personalization_directive(tmp_path)]
    runner._set_pending_turn_sidecar_notes('key', notes)
    history = [{'role': 'user', 'content': 'earlier'}, {'role': 'assistant', 'content': 'hello'}]
    session = _FakeSession(_FakeSSEResponse(sse_chunks=[
        'data: {"choices":[{"delta":{"content":"Welcome"}}]}\n\n',
        'data: [DONE]\n\n',
    ]))
    with _patch_aiohttp(session):
        result = await runner._run_agent_via_proxy(
            'hi', 'fixed context', history, source, 'sid', session_key='key', scheduled_heartbeat=True,
        )
        sent = session.captured_json['messages']
        assert sent[:-1] == [{'role': 'system', 'content': 'fixed context'}, *history]
        assert sent[-1]['content'] == 'hi\n\n' + notes[0]
        assert result['messages'][0] == {'role': 'user', 'content': 'hi'}
        assert runner._consume_pending_turn_sidecar_notes('key') == []

        await runner._run_agent_via_proxy(
            'later', 'fixed context', history, source, 'sid', session_key='key', scheduled_heartbeat=True,
        )
        assert session.captured_json['messages'][-1] == {'role': 'user', 'content': 'later'}
