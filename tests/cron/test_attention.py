"""Attention layer: settings, the capture gate, interruptions, digests and open-loop check-ins.

Everything runs against the real SQLite store in an isolated HERMES_HOME with a recording send
function — no model, no gateway, no external delivery.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cron import attention, attention_flush as flush_mod, attention_policy as policy
from cron import attention_store as store

TZ = ZoneInfo("Europe/Amsterdam")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def settings(**overrides):
    return policy.settings_from_config({"attention": {"enabled": True, **overrides}})


class Recorder:
    def __init__(self, error=None, no_target=False):
        self.sent: list[tuple[str, object, str]] = []
        self.error, self.no_target = error, no_target

    def __call__(self, deliver, origin, text, adapters, loop):
        if self.no_target:
            raise flush_mod.NoTarget(deliver)
        self.sent.append((deliver, origin, text))
        return self.error


@pytest.fixture
def home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    return hermes_home


def capture(s, *, kind="inform", urgency=5, key="k1", deliver="telegram", now=None, **extra):
    return attention.capture(
        kind=kind, title=extra.pop("title", f"title {key}"), body=extra.pop("body", "body"),
        source="test", category=extra.pop("category", "test"), urgency=urgency, dedup_key=key,
        deliver=deliver, settings=s, now=now or at(15, 9), **extra)


# ── Settings and pure policy ──────────────────────────────────────────


def test_defaults_are_off_and_quiet():
    s = policy.settings_from_config({})
    assert not s.enabled and not s.active
    assert s.level == "quiet" and s.interrupt_threshold is None and s.max_interrupts_per_day == 0
    assert [t.strftime("%H:%M") for t in s.digest_times] == ["08:30", "13:00", "18:30"]


def test_settings_read_through_profile_config(home):
    (home / "config.yaml").write_text(
        "attention:\n  enabled: true\n  level: balanced\n  quiet_hours: '23:00-07:30'\n"
        "  digest_times: ['07:45', 'bogus']\n  deliver: telegram\n")
    s = policy.load_settings()
    assert s.active and s.level == "balanced" and s.max_interrupts_per_day == 3
    assert (s.quiet_start.strftime("%H:%M"), s.quiet_end.strftime("%H:%M")) == ("23:00", "07:30")
    assert [t.strftime("%H:%M") for t in s.digest_times] == ["07:45"]
    assert s.deliver == "telegram"


def test_malformed_settings_fall_back_to_safe_values():
    s = settings(level="loud", quiet_hours="whenever", max_interrupts_per_day=-2, digest_times="8")
    assert s.level == "quiet" and s.quiet_start is None and s.max_interrupts_per_day == 0
    assert len(s.digest_times) == 3


def test_quiet_hours_wrap_midnight():
    s = settings(quiet_hours="22:00-08:00")
    assert policy.in_quiet_hours(s, at(15, 23))
    assert policy.in_quiet_hours(s, at(15, 7, 59))
    assert not policy.in_quiet_hours(s, at(15, 8))
    assert not policy.in_quiet_hours(settings(quiet_hours=""), at(15, 23))


def test_digest_slots():
    s = settings(digest_times=["08:30", "18:30"])
    assert policy.latest_digest_slot(s, at(15, 7)) == at(14, 18, 30)
    assert policy.latest_digest_slot(s, at(15, 9)) == at(15, 8, 30)
    assert policy.next_digest_slot(s, at(15, 19)) == at(16, 8, 30)


@pytest.mark.parametrize("level,kind,urgency,muted,expected", [
    ("balanced", "alert", 8, False, policy.ROUTE_NOW),
    ("balanced", "alert", 6, False, policy.ROUTE_DIGEST),
    ("eager", "alert", 5, False, policy.ROUTE_NOW),
    ("quiet", "alert", 10, False, policy.ROUTE_DIGEST),
    ("balanced", "inform", 9, False, policy.ROUTE_DIGEST),
    ("balanced", "alert", 9, True, policy.ROUTE_INBOX),
    ("balanced", "inform", 2, False, policy.ROUTE_INBOX),
])
def test_capture_route_matrix(level, kind, urgency, muted, expected):
    route, reason = policy.decide_route(settings(level=level), kind=kind, urgency=urgency, muted=muted)
    assert route == expected and reason


# ── Capture ───────────────────────────────────────────────────────────


def test_inactive_layer_captures_nothing_and_creates_no_store(home):
    assert capture(policy.settings_from_config({})) is None
    assert capture(settings(level="off")) is None
    assert not store.current_attention_file().exists()


def test_duplicate_is_dropped_and_logged(home):
    s = settings()
    assert capture(s, key="same") is not None
    assert capture(s, key="same") is None
    assert [e["event"] for e in attention.activity()][:2] == ["duplicate", "captured"]
    assert len(attention.inbox(at(15, 9))) == 1


# ── Interruptions ─────────────────────────────────────────────────────


def test_alert_interrupts_once(home):
    s, send = settings(level="balanced"), Recorder()
    capture(s, kind="alert", urgency=8, title="Server down")
    flush_mod.flush(now=at(15, 10), settings=s, send=send)
    flush_mod.flush(now=at(15, 10, 1), settings=s, send=send)
    assert len(send.sent) == 1
    deliver, _origin, text = send.sent[0]
    assert deliver == "telegram" and text.startswith("Server down") and "Why now" not in text
    [item] = attention.inbox(at(15, 10, 2))
    assert item["status"] == "sent"


def test_quiet_hours_hold_alert_until_they_end(home):
    s, send = settings(level="balanced"), Recorder()
    capture(s, kind="alert", urgency=8, now=at(15, 23))
    for minute in (0, 1, 2):
        flush_mod.flush(now=at(15, 23, minute), settings=s, send=send)
    assert send.sent == []
    assert [e["event"] for e in attention.activity()].count("held_quiet_hours") == 1
    flush_mod.flush(now=at(16, 8, 5), settings=s, send=send)
    assert len(send.sent) == 1


def test_interrupt_budget_moves_excess_to_digest(home):
    s, send = settings(level="balanced", digest_times=["18:00"]), Recorder()
    for i in range(4):
        capture(s, kind="alert", urgency=9, key=f"a{i}", title=f"alert {i}")
    flush_mod.flush(now=at(15, 10), settings=s, send=send)
    assert len(send.sent) == 3
    held = [i for i in attention.inbox(at(15, 10)) if i["status"] == "pending"]
    assert len(held) == 1 and held[0]["route"] == policy.ROUTE_DIGEST
    flush_mod.flush(now=at(15, 18, 1), settings=s, send=send)
    assert send.sent[-1][2].startswith("Digest · 1 item")


def test_quiet_level_never_interrupts(home):
    s, send = settings(level="quiet"), Recorder()
    capture(s, kind="alert", urgency=10)
    flush_mod.flush(now=at(15, 10), settings=s, send=send)
    assert send.sent == []


def test_failed_sends_retry_then_fall_back_to_digest(home):
    s, send = settings(level="balanced"), Recorder(error="adapter offline")
    capture(s, kind="alert", urgency=8)
    for minute in range(flush_mod.MAX_SEND_ATTEMPTS + 1):
        flush_mod.flush(now=at(15, 10, minute), settings=s, send=send)
    assert len(send.sent) == flush_mod.MAX_SEND_ATTEMPTS
    [item] = attention.inbox(at(15, 11))
    assert item["status"] == "pending" and item["route"] == policy.ROUTE_DIGEST


def test_digest_that_keeps_failing_stops_after_the_attempt_cap(home):
    s, send = settings(digest_times=["09:00", "13:00", "18:00"]), Recorder(error="chat revoked")
    flush_mod.flush(now=at(14, 19), settings=s, send=send)  # baseline
    capture(s, key="a", now=at(14, 20))
    slots = [at(day, hour, 1) for day in (15, 16, 17) for hour in (9, 13, 18)]
    for when in slots:
        flush_mod.flush(now=when, settings=s, send=send)
    assert len(send.sent) == flush_mod.MAX_TOTAL_ATTEMPTS
    [item] = attention.inbox(at(17, 19))
    assert item["status"] == "pending" and item["route"] == policy.ROUTE_INBOX


def test_item_without_target_stays_in_inbox(home):
    s, send = settings(level="balanced"), Recorder()
    capture(s, kind="alert", urgency=8, deliver="local")
    flush_mod.flush(now=at(15, 10), settings=s, send=send)
    [item] = attention.inbox(at(15, 10))
    assert send.sent == [] and item["status"] == "pending" and item["route"] == policy.ROUTE_INBOX


def test_fallback_target_used_for_local_items(home):
    s, send = settings(level="balanced", deliver="telegram"), Recorder()
    capture(s, kind="alert", urgency=8, deliver="local")
    flush_mod.flush(now=at(15, 10), settings=s, send=send)
    assert [(d, o) for d, o, _ in send.sent] == [("telegram", None)]


def test_unresolvable_origin_is_not_reported_as_delivered(home):
    """Real cron resolver: deliver=origin with no origin or home channel resolves to nothing."""
    s = settings(level="balanced")
    capture(s, kind="alert", urgency=8, deliver="origin")
    flush_mod.flush(now=at(15, 10), settings=s)
    [item] = attention.inbox(at(15, 10))
    assert item["status"] == "pending"
    assert "inbox_only" in [e["event"] for e in attention.activity()]


# ── Digests ───────────────────────────────────────────────────────────


def test_digest_baseline_then_once_per_slot(home):
    s, send = settings(digest_times=["08:30", "13:00"]), Recorder()
    capture(s, key="a", title="first", now=at(15, 9))
    flush_mod.flush(now=at(15, 9, 1), settings=s, send=send)
    assert send.sent == []  # first observation records the 08:30 baseline only
    capture(s, key="b", title="second", now=at(15, 10))
    flush_mod.flush(now=at(15, 13, 0), settings=s, send=send)
    flush_mod.flush(now=at(15, 13, 1), settings=s, send=send)  # same slot, e.g. after restart
    assert len(send.sent) == 1
    text = send.sent[0][2]
    assert text.startswith("Digest · 2 items") and "first" in text and "second" in text


def test_missed_slots_coalesce_into_one_digest(home):
    s, send = settings(digest_times=["08:30", "13:00", "18:30"]), Recorder()
    capture(s, key="a", now=at(14, 9))
    flush_mod.flush(now=at(14, 9, 1), settings=s, send=send)
    capture(s, key="b", now=at(14, 10))
    flush_mod.flush(now=at(15, 9), settings=s, send=send)  # 13:00, 18:30, 08:30 all missed
    assert len(send.sent) == 1


def test_digest_groups_by_target(home):
    s, send = settings(digest_times=["13:00"]), Recorder()
    capture(s, key="a", deliver="telegram")
    flush_mod.flush(now=at(15, 9, 1), settings=s, send=send)
    capture(s, key="b", deliver="discord")
    capture(s, key="c", deliver="telegram")
    flush_mod.flush(now=at(15, 13, 1), settings=s, send=send)
    assert sorted((d, t.splitlines()[0]) for d, _, t in send.sent) == [
        ("discord", "Digest · 1 item"), ("telegram", "Digest · 2 items")]


# ── Inbox controls ────────────────────────────────────────────────────


def test_mute_routes_existing_and_new_items_to_inbox_only(home):
    s, send = settings(digest_times=["13:00"]), Recorder()
    capture(s, key="a", category="cron:News")
    flush_mod.flush(now=at(15, 9, 1), settings=s, send=send)
    assert attention.set_category_muted("cron:News", True, at(15, 9, 2))
    capture(s, key="b", category="cron:News", now=at(15, 9, 3))
    flush_mod.flush(now=at(15, 13, 1), settings=s, send=send)
    assert send.sent == []
    assert {i["route"] for i in attention.inbox(at(15, 13, 2))} == {policy.ROUTE_INBOX}


def test_snooze_hides_until_due_then_returns_to_digest(home):
    s, send = settings(digest_times=["13:00", "18:00"]), Recorder()
    item = capture(s, key="a")
    flush_mod.flush(now=at(15, 9, 1), settings=s, send=send)
    attention.snooze_item(item, at(15, 15), at(15, 9, 2))
    assert attention.inbox(at(15, 12)) == []
    flush_mod.flush(now=at(15, 13, 1), settings=s, send=send)
    assert send.sent == []
    flush_mod.flush(now=at(15, 18, 1), settings=s, send=send)
    assert len(send.sent) == 1


def test_items_expire(home):
    s = settings()
    capture(s, key="a", now=at(1, 9))
    summary = flush_mod.flush(now=at(9, 9), settings=s, send=Recorder())
    assert summary["expired"] == 1 and attention.inbox(at(9, 9)) == []


# ── Open loops ────────────────────────────────────────────────────────


def add_loop(title="Renew passport", due=None, now=None, evidence="I need to renew my passport"):
    with store.transaction() as conn:
        return store.add_open_loop(conn, title=title, due_at=due, evidence=evidence, session_id="s1",
                                   deliver="telegram", origin=None, now=now or at(15, 9))


def test_open_loop_titles_unique_only_while_open(home):
    first = add_loop()
    assert add_loop() is None
    attention.close_open_loop(first["id"], "done", at(15, 10))
    assert add_loop(now=at(15, 11)) is not None


def test_loop_checkin_stages_supersede_and_never_repeat(home):
    s, send = settings(level="balanced"), Recorder()
    loop = add_loop(due=at(17, 18))
    assert flush_mod.flush(now=at(16, 12), settings=s, send=send)["checkins"] == 0
    assert flush_mod.flush(now=at(16, 19), settings=s, send=send)["checkins"] == 1  # soon
    assert flush_mod.flush(now=at(16, 20), settings=s, send=send)["checkins"] == 0
    [soon] = attention.inbox(at(16, 20))
    assert soon["title"] == "Coming up: Renew passport" and soon["loop_id"] == loop["id"]
    assert "I need to renew my passport" in soon["body"]
    flush_mod.flush(now=at(17, 16, 30), settings=s, send=send)  # urgent alert interrupts
    [urgent] = attention.inbox(at(17, 16, 31))
    assert urgent["kind"] == "alert" and urgent["title"].startswith("Due today at 18:00")
    assert send.sent and send.sent[-1][2].startswith("Due today at 18:00")


def test_overdue_loop_follows_up_once_without_log_noise(home):
    """Regression (found in the dry run): past the deadline the sweep re-attempted the urgent
    check-in every tick and logged a duplicate each minute."""
    s, send = settings(level="balanced"), Recorder()
    add_loop(due=at(16, 18))
    for when in (at(16, 16, 30), at(16, 18, 30), at(16, 19), at(17, 18, 30), at(17, 19), at(18, 9)):
        flush_mod.flush(now=when, settings=s, send=send)
    assert "duplicate" not in [e["event"] for e in attention.activity(100)]
    assert [i["title"] for i in attention.inbox(at(18, 9))] == ["Overdue: Renew passport"]
    # One urgent alert before the deadline; the overdue follow-up arrives in a digest, not alone.
    assert [text.splitlines()[0] for _, _, text in send.sent] == [
        "Due today at 18:00: Renew passport", "Digest · 1 item"]
    assert "Overdue: Renew passport" in send.sent[1][2]


def test_undated_loop_checks_in_after_three_days(home):
    s = settings()
    add_loop(due=None, now=at(10, 9))
    flush_mod.flush(now=at(12, 9), settings=s, send=Recorder())
    assert attention.inbox(at(12, 9)) == []
    flush_mod.flush(now=at(13, 10), settings=s, send=Recorder())
    [item] = attention.inbox(at(13, 10))
    assert item["title"] == "Still open: Renew passport" and item["urgency"] == 4


def test_resolving_checkin_closes_loop_and_stops_checkins(home):
    s = settings()
    add_loop(due=at(16, 18))
    flush_mod.flush(now=at(16, 9), settings=s, send=Recorder())
    [item] = attention.inbox(at(16, 9))
    attention.resolve_item(item, "done", at(16, 9, 1))
    assert attention.open_loops() == []
    flush_mod.flush(now=at(16, 17), settings=s, send=Recorder())
    assert attention.inbox(at(16, 17)) == []


def test_open_loops_switch_off(home):
    s = settings(open_loops=False)
    add_loop(due=at(15, 10))
    assert flush_mod.flush(now=at(15, 9, 30), settings=s, send=Recorder())["checkins"] == 0


# ── Profile isolation ─────────────────────────────────────────────────


def test_stores_are_per_profile(tmp_path, monkeypatch):
    s = settings()
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "a"))
    capture(s, key="only-in-a")
    assert len(attention.inbox(at(15, 9))) == 1
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "b"))
    assert attention.inbox(at(15, 9)) == []
    assert (tmp_path / "a" / "cron" / "attention.db").exists()
