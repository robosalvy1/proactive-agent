"""Open-loop capture: the deterministic pre-filter, verbatim-evidence validation, due-date parsing,
store writes from a stubbed extractor, and the post-turn hook's eligibility rules."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent import open_loops
from cron import attention_store as store
from tests.waiting import wait_until

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 15, 10, 0, tzinfo=TZ)  # a Thursday


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("attention:\n  enabled: true\n")
    return tmp_path


@pytest.fixture
def model(monkeypatch):
    """Stub the auxiliary call; ``model.reply`` is the JSON payload, ``model.calls`` the prompts."""
    state = SimpleNamespace(reply={"add": [], "close": []}, calls=[])

    def call_llm(*, task, messages, **kw):
        assert task == "open_loops"
        state.calls.append(messages[-1]["content"])
        content = json.dumps(state.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr("agent.auxiliary_client.call_llm", call_llm)
    return state


def loops():
    with store.transaction() as conn:
        return store.list_open_loops(conn, ("open", "done", "cancelled"))


@pytest.mark.parametrize("text,titles,expected", [
    ("Remind me to call mom", [], True),
    ("I need to renew my passport by Friday", [], True),
    ("I have to pay rent tomorrow", [], True),
    ("What's the weather like?", [], False),
    ("I need to think about this", [], False),            # commitment cue without a time cue
    ("Can you summarize this article from Monday?", [], False),
    ("I renewed the passport already", ["Renew passport"], True),
    ("Finished the report", ["Renew passport"], False),   # completion, but no tracked loop matches
    ("", [], False),
])
def test_prefilter(text, titles, expected):
    assert open_loops.needs_extraction(text, titles) is expected


def test_evidence_must_be_quoted_from_the_message():
    message = "Ugh, I need to renew my  passport by Friday!"
    assert open_loops.evidence_in_message("renew my passport by Friday", message)
    assert open_loops.evidence_in_message("“I need to renew my passport”", message)
    assert not open_loops.evidence_in_message("book flights to Rome", message)
    assert not open_loops.evidence_in_message("by", message)


def test_due_parsing():
    assert open_loops.parse_due("2026-10-16", NOW) == datetime(2026, 10, 16, 18, 0, tzinfo=TZ)
    assert open_loops.parse_due("2026-10-16T09:30", NOW) == datetime(2026, 10, 16, 9, 30, tzinfo=TZ)
    assert open_loops.parse_due("2026-10-01", NOW) is None  # stale/misread date
    assert open_loops.parse_due("next friday", NOW) is None
    assert open_loops.parse_due(None, NOW) is None


def test_message_text_from_content_parts():
    parts = [{"type": "text", "text": "remind me"}, {"type": "image_url", "image_url": {"url": "x"}}]
    assert open_loops.message_text(parts) == "remind me"


def test_capture_adds_validated_loops(home, model):
    model.reply = {"add": [
        {"title": "Renew passport", "due": "2026-10-16", "evidence": "renew my passport by Friday"},
        {"title": "Book flights", "due": None, "evidence": "invented by the model"},
    ], "close": []}
    result = open_loops.capture_from_message(
        "I need to renew my passport by Friday", session_id="s1",
        origin={"platform": "telegram", "chat_id": "42"}, now=NOW)
    assert result == {"added": 1, "closed": 0}
    [loop] = loops()
    assert loop["title"] == "Renew passport" and loop["deliver"] == "origin"
    assert loop["origin"] == {"platform": "telegram", "chat_id": "42"}
    assert store.parse_iso(loop["due_at"]) == datetime(2026, 10, 16, 18, 0, tzinfo=TZ)
    assert "Current local time: Thursday 2026-10-15 10:00" in model.calls[0]


def test_capture_closes_tracked_loop_and_its_items(home, model):
    from cron import attention

    with store.transaction() as conn:
        loop = store.add_open_loop(conn, title="Renew passport", due_at=None, evidence="x",
                                   session_id="", deliver="local", origin=None, now=NOW)
    attention.capture(kind="ask", title="Still open: Renew passport", body="", source="open_loop",
                      category="open_loop", urgency=4, dedup_key="loop:x", loop_id=loop["id"])
    model.reply = {"add": [], "close": [
        {"id": loop["id"], "status": "done", "evidence": "renewed the passport"},
        {"id": "not-tracked", "status": "done", "evidence": "renewed the passport"},
    ]}
    result = open_loops.capture_from_message("I renewed the passport today", now=NOW)
    assert result == {"added": 0, "closed": 1}
    assert loops()[0]["status"] == "done"
    assert attention.inbox() == []


def test_no_model_call_when_prefilter_or_settings_say_no(home, model, tmp_path):
    assert open_loops.capture_from_message("What's the weather?", now=NOW) == {"added": 0, "closed": 0}
    (tmp_path / "config.yaml").write_text("attention:\n  enabled: true\n  open_loops: false\n")
    open_loops.capture_from_message("Remind me to call mom tomorrow", now=NOW)
    assert model.calls == []


def test_unparseable_model_output_adds_nothing(home, monkeypatch):
    monkeypatch.setattr("agent.auxiliary_client.call_llm", lambda **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="sure! I'll remember"))]))
    assert open_loops.capture_from_message("Remind me to call mom", now=NOW) == {"added": 0, "closed": 0}


@pytest.mark.parametrize("attrs", [
    {"skip_background_review": True}, {"skip_memory": True}, {"platform": "cron"},
    {"_delegate_depth": 1},
])
def test_hook_skips_non_interactive_agents(home, model, attrs):
    agent = SimpleNamespace(session_id="s", platform="cli", skip_background_review=False,
                            skip_memory=False, _delegate_depth=0)
    for key, value in attrs.items():
        setattr(agent, key, value)
    open_loops.maybe_capture_after_turn(agent, "Remind me to call mom")
    assert model.calls == []


def test_hook_captures_on_a_background_thread(home, model):
    model.reply = {"add": [{"title": "Call mom", "due": None, "evidence": "call mom"}], "close": []}
    agent = SimpleNamespace(session_id="s9", platform="cli", skip_background_review=False,
                            skip_memory=False, _delegate_depth=0)
    open_loops.maybe_capture_after_turn(agent, "Remind me to call mom")
    wait_until(lambda: store.current_attention_file().exists() and loops(), what="open loop stored")
    [loop] = loops()
    assert loop["session_id"] == "s9" and loop["deliver"] == "local"


def test_oneshot_exit_waits_for_a_started_capture(home, model, monkeypatch):
    """`hermes -z` hard-exits after the reply; its cleanup must let the capture commit first."""
    import threading

    from hermes_cli import oneshot

    release = threading.Event()
    original = open_loops.capture_from_message

    def slow_capture(*args, **kwargs):
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(open_loops, "capture_from_message", slow_capture)
    model.reply = {"add": [{"title": "Call mom", "due": None, "evidence": "call mom"}], "close": []}
    agent = SimpleNamespace(session_id="s1", platform="cli", skip_background_review=False,
                            skip_memory=False, _delegate_depth=0)
    open_loops.maybe_capture_after_turn(agent, "Remind me to call mom")
    threading.Timer(0.2, release.set).start()
    monkeypatch.setattr(oneshot, "_linger_for_background_completions", lambda: None)
    oneshot._close_agent(SimpleNamespace(shutdown_memory_provider=lambda *a: None, close=lambda: None), None)
    assert [loop["title"] for loop in loops()] == ["Call mom"] and not open_loops._pending
