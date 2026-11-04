"""/inbox: the shared handler behind the CLI, messaging gateway and TUI/Desktop slash command."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cron import attention, attention_store as store
from hermes_cli.inbox_cmd import handle_inbox_command, parse_duration


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def enabled(home):
    (home / "config.yaml").write_text(
        "attention:\n  enabled: true\n  level: balanced\n  quiet_hours: ''\n")
    return home


def capture(key, title, **extra):
    return attention.capture(kind=extra.pop("kind", "inform"), title=title, body=extra.pop("body", ""),
                             source="test", category=extra.pop("category", "test"),
                             urgency=extra.pop("urgency", 5), dedup_key=key, deliver="telegram", **extra)


def test_off_by_default_explains_how_to_enable(home):
    for args in ("", "status", "loops"):
        assert "inbox is off" in handle_inbox_command(args)
    assert not store.current_attention_file().exists()


def test_status_reports_policy(enabled):
    out = handle_inbox_command("status")
    assert "Attention: balanced" in out and "Quiet hours: none" in out
    assert "Interruptions today: 0/3" in out and "Digests: 08:30, 13:00, 18:30" in out


def test_list_show_and_done(enabled):
    capture("a", "Low priority note", urgency=4)
    capture("b", "Flight delayed", kind="alert", urgency=9, body="New departure 14:10",
            why_now="departure moved")
    out = handle_inbox_command("")
    lines = out.splitlines()
    assert lines[0] == "Inbox · 2 open"
    assert lines[1].startswith("1. [") and "Flight delayed — sending now" in lines[1]
    assert "Low priority note — next digest" in lines[2]
    shown = handle_inbox_command("show 1")
    assert "New departure 14:10" in shown and "Why: departure moved" in shown
    assert handle_inbox_command("done 1") == "Done: Flight delayed."
    assert handle_inbox_command("").startswith("Inbox · 1 open")
    assert "No open item" in handle_inbox_command("done 9")


def test_ids_resolve_by_prefix(enabled):
    item = capture("a", "Pay rent")
    assert handle_inbox_command(f"dismiss {item['id'][:6]}") == "Dismissed: Pay rent."
    assert handle_inbox_command("") == "Inbox is empty."


def test_snooze(enabled):
    capture("a", "Pay rent")
    assert "Snooze for a duration" in handle_inbox_command("snooze 1 soonish")
    assert handle_inbox_command("snooze 1 2h").startswith("Snoozed until")
    assert handle_inbox_command("") == "Inbox is empty."


def test_less_and_more(enabled):
    capture("a", "Daily news", category="cron:News")
    assert handle_inbox_command("less 1").startswith("Muted cron:News")
    assert "inbox only" in handle_inbox_command("")
    assert handle_inbox_command("more") == "Muted: cron:News"
    assert handle_inbox_command("more cron:News") == "Unmuted cron:News."


def test_loops_list_and_close(enabled):
    from hermes_time import now

    with store.transaction() as conn:
        store.add_open_loop(conn, title="Renew passport", due_at=now() + timedelta(days=3),
                            evidence="renew my passport", session_id="", deliver="local",
                            origin=None, now=now())
    out = handle_inbox_command("loops")
    assert out.startswith("Open loops · 1") and "1. Renew passport — due" in out
    assert handle_inbox_command("") == "Inbox is empty · 1 open loop (/inbox loops)."
    assert handle_inbox_command("loops done 1") == "Done: Renew passport."
    assert handle_inbox_command("loops").startswith("No open loops")


def test_log_and_digest_preview(enabled):
    capture("a", "Weekly review")
    assert "captured: Weekly review — route=digest" in handle_inbox_command("log")
    assert handle_inbox_command("digest").startswith("Digest · 1 item")


def test_unknown_verb_shows_usage(enabled):
    assert handle_inbox_command("frobnicate").startswith("Usage: /inbox")


@pytest.mark.parametrize("text,expected", [
    ("30m", timedelta(minutes=30)), ("2h", timedelta(hours=2)), ("1d", timedelta(days=1)),
    ("3days", timedelta(days=3)), ("0h", None), ("soon", None),
])
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


def test_registered_on_every_surface():
    from gateway.run_busy import GatewayBusySessionMixin
    from gateway.session_commands import command_verdict
    from hermes_cli.commands import GATEWAY_KNOWN_COMMANDS, resolve_command

    assert resolve_command("inbox").name == "inbox"
    assert "inbox" in GATEWAY_KNOWN_COMMANDS
    assert "inbox" in GatewayBusySessionMixin._IDLE_COMMANDS
    assert command_verdict("inbox") == "control"


@pytest.fixture
def watchable(enabled, monkeypatch):
    from cron import attention_sources

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(attention_sources, "_connector_sources", list)
    (enabled / "config.yaml").write_text(
        "attention:\n  enabled: true\nmcp_servers:\n  gmail:\n    command: echo\n")
    return enabled


def test_watch_on_status_and_off(watchable):
    from cron import jobs

    assert "Proactive watch is off" in handle_inbox_command("watch")
    assert "every 15m, 30m" in handle_inbox_command("watch on 5m")
    out = handle_inbox_command("watch on 2h")
    assert "every 120m" in out and "Watching: gmail (MCP)" in out and "New watchers: 1" in out
    assert "Proactive watch: on · every 120m · 1 source(s)" in handle_inbox_command("status")
    assert len(jobs.list_jobs()) == 2  # the watcher and weekly discovery
    assert "Checking 1 source(s)" in handle_inbox_command("watch now")
    assert "Removed 1 watcher job(s)" in handle_inbox_command("watch off")
    assert jobs.list_jobs(include_disabled=True) == []


def test_sources_list_remove_restore(watchable):
    handle_inbox_command("watch on")
    out = handle_inbox_command("sources")
    assert "1. gmail (MCP) [email] · watching" in out and "found by index" in out
    assert handle_inbox_command("sources remove 1") == "Removed: gmail (MCP)."
    assert "gmail (MCP) [email] — removed" in handle_inbox_command("sources")
    assert handle_inbox_command("sources restore 1") == "Restored: gmail (MCP)."
    assert handle_inbox_command("sources bogus").startswith("Usage: /inbox sources")
    assert "next tick" in handle_inbox_command("sources discover")
