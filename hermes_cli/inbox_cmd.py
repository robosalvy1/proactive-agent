"""Shared ``/inbox`` command logic for CLI and gateway: review and resolve proactive items, open
loops, the activity log and attention status. Both surfaces present the returned text."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

_USAGE = (
    "Usage: /inbox [show|done|dismiss|snooze|less|more|loops|watch|sources|log|digest|status] …\n"
    "  /inbox                 open items\n"
    "  /inbox show <n|id>     full text and why it was sent\n"
    "  /inbox done <n|id>     mark handled (closes its open loop)\n"
    "  /inbox dismiss <n|id>  not relevant (cancels its open loop)\n"
    "  /inbox snooze <n|id> [30m|2h|1d]\n"
    "  /inbox less <n|id>     stop pushing this kind of item (inbox only)\n"
    "  /inbox more <category> undo /inbox less\n"
    "  /inbox loops [done|cancel <n>]  tracked commitments\n"
    "  /inbox watch [on [1h]|off|now]  watch every connected source\n"
    "  /inbox sources          connected sources (remove|restore N, refresh, discover)\n"
    "  /inbox log             recent decisions with reasons\n"
    "  /inbox digest          preview the next digest\n"
    "  /inbox status          level, quiet hours, digests, budget"
)
_DURATION = re.compile(r"^(\d+)\s*(m|min|h|hr|d|day)s?$", re.IGNORECASE)
_UNITS = {"m": "minutes", "min": "minutes", "h": "hours", "hr": "hours", "d": "days", "day": "days"}


def _now() -> datetime:
    from hermes_time import now
    return now()


def _local(value: Optional[str], now: datetime) -> str:
    from cron.attention_store import parse_iso
    from hermes_time import safe_strftime

    dt = parse_iso(value)
    if dt is None:
        return "?"
    local = dt.astimezone(now.tzinfo)
    return safe_strftime(local, "%H:%M" if local.date() == now.date() else "%a %d %b %H:%M")


def parse_duration(text: str) -> Optional[timedelta]:
    match = _DURATION.match((text or "").strip())
    if not match or int(match.group(1)) <= 0:
        return None
    return timedelta(**{_UNITS[match.group(2).lower()]: int(match.group(1))})


def _state_label(item: dict, settings, now: datetime) -> str:
    from cron import attention_policy as policy

    if item["status"] == "sent":
        return f"sent {_local(item['delivered_at'], now)}"
    if item["route"] == policy.ROUTE_INBOX:
        return "inbox only"
    if item["route"] == policy.ROUTE_NOW:
        return "waiting for quiet hours to end" if policy.in_quiet_hours(settings, now) else "sending now"
    slot = policy.next_digest_slot(settings, now)
    return f"next digest {_local(slot.isoformat(), now)}" if slot else "inbox only (no digest times)"


def _list(settings, now: datetime) -> str:
    from cron import attention
    from cron.attention_flush import short_id

    items = attention.inbox(now)
    loops = attention.open_loops()
    if not items:
        tail = f" · {len(loops)} open loop{'s' if len(loops) != 1 else ''} (/inbox loops)" if loops else ""
        return f"Inbox is empty{tail}."
    lines = [f"Inbox · {len(items)} open"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. [{short_id(item)}] {item['title']} — {_state_label(item, settings, now)}")
    if loops:
        lines.append(f"{len(loops)} open loop{'s' if len(loops) != 1 else ''} · /inbox loops")
    lines.append("/inbox show N · done N · dismiss N · snooze N 2h · less N")
    return "\n".join(lines)


def _require(ref: str, now: datetime):
    from cron import attention

    return attention.resolve_ref(ref, now)


def _show(rest: str, settings, now: datetime) -> str:
    item = _require(rest, now)
    if item is None:
        return f"No open item {rest!r}. /inbox lists them."
    parts = [item["title"], f"{item['kind']} · {item['category']} · urgency {item['urgency']} · "
             f"{_state_label(item, settings, now)}"]
    if item.get("why_now"):
        parts.append(f"Why: {item['why_now']}")
    if item.get("body"):
        parts.append(item["body"])
    return "\n\n".join(parts)


def _resolve(verb: str, rest: str, now: datetime) -> str:
    from cron import attention

    item = _require(rest, now)
    if item is None:
        return f"No open item {rest!r}. /inbox lists them."
    attention.resolve_item(item, "done" if verb == "done" else "dismissed", now)
    loop_note = " Its open loop is closed." if item.get("loop_id") else ""
    return f"{'Done' if verb == 'done' else 'Dismissed'}: {item['title']}.{loop_note}"


def _snooze(rest: str, now: datetime) -> str:
    from cron import attention

    ref, _, duration_text = rest.partition(" ")
    duration = parse_duration(duration_text) if duration_text.strip() else timedelta(days=1)
    if duration is None:
        return "Snooze for a duration such as 30m, 2h or 1d."
    item = _require(ref, now)
    if item is None:
        return f"No open item {ref!r}. /inbox lists them."
    until = now + duration
    attention.snooze_item(item, until, now)
    return f"Snoozed until {_local(until.isoformat(), now)}: {item['title']}."


def _less(rest: str, now: datetime) -> str:
    from cron import attention

    item = _require(rest, now)
    category = item["category"] if item else rest.strip()
    if not category:
        return "Usage: /inbox less <n|id>"
    if item is None and category not in {i["category"] for i in attention.inbox(now)}:
        return f"No open item {rest!r}. /inbox lists them."
    changed = attention.set_category_muted(category, True, now)
    if not changed:
        return f"Already muted: {category}."
    return f"Muted {category}: new items stay in /inbox and are never pushed. Undo: /inbox more {category}"


def _more(rest: str, now: datetime) -> str:
    from cron import attention

    category = rest.strip()
    if not category:
        muted = attention.muted_categories()
        return "Muted: " + ", ".join(muted) if muted else "Nothing is muted."
    if attention.set_category_muted(category, False, now):
        return f"Unmuted {category}."
    return f"{category} is not muted."


def _loops(rest: str, now: datetime) -> str:
    from cron import attention

    loops = attention.open_loops()
    verb, _, ref = rest.strip().partition(" ")
    if verb in ("done", "cancel"):
        if not ref.strip().isdigit() or not 0 < int(ref) <= len(loops):
            return "Usage: /inbox loops done|cancel <n> (numbers from /inbox loops)"
        loop = loops[int(ref) - 1]
        attention.close_open_loop(loop["id"], "done" if verb == "done" else "cancelled", now)
        return f"{'Done' if verb == 'done' else 'Cancelled'}: {loop['title']}."
    if verb:
        return "Usage: /inbox loops [done|cancel <n>]"
    if not loops:
        return "No open loops. Commitments you mention in chat appear here when attention.open_loops is on."
    lines = [f"Open loops · {len(loops)}"]
    for i, loop in enumerate(loops, 1):
        due = f" — due {_local(loop['due_at'], now)}" if loop.get("due_at") else ""
        lines.append(f"{i}. {loop['title']}{due}")
    lines.append("/inbox loops done N · /inbox loops cancel N")
    return "\n".join(lines)


def _log(now: datetime) -> str:
    from cron import attention

    events = attention.activity(20)
    if not events:
        return "No attention activity yet."
    lines = ["Recent attention decisions (newest first)"]
    for event in events:
        subject = f": {event['title']}" if event.get("title") else ""
        detail = f" — {event['detail']}" if event.get("detail") else ""
        lines.append(f"{_local(event['at'], now)} {event['event']}{subject}{detail}")
    return "\n".join(lines)


def _status(settings, now: datetime) -> str:
    from cron import attention_policy as policy
    from cron import attention_store as store
    from hermes_cli.inbox_watch_cmd import watch_status_line

    if not settings.enabled:
        return _OFF_MESSAGE
    quiet = (f"{settings.quiet_start:%H:%M}-{settings.quiet_end:%H:%M}"
             if settings.quiet_start and settings.quiet_end else "none")
    used = 0
    if store.current_attention_file().exists():
        with store.transaction() as conn:
            used = store.count_events_since(conn, "interrupted", policy.local_day_start(now))
    slot = policy.next_digest_slot(settings, now)
    return "\n".join([
        f"Attention: {settings.level}" + (" (no interruptions)" if settings.interrupt_threshold is None else ""),
        f"Quiet hours: {quiet} · now {'quiet' if policy.in_quiet_hours(settings, now) else 'active'}",
        "Digests: " + (", ".join(f"{t:%H:%M}" for t in settings.digest_times) or "none")
        + (f" · next {_local(slot.isoformat(), now)}" if slot else ""),
        f"Interruptions today: {used}/{settings.max_interrupts_per_day}",
        f"Cron results routed: {'yes' if settings.route_cron else 'no'} · "
        f"open loops: {'on' if settings.open_loops else 'off'} · "
        f"fallback target: {settings.deliver or 'inbox only'}",
        watch_status_line(),
    ])


_OFF_MESSAGE = (
    "The proactive inbox is off. Turn it on with `hermes config set attention.enabled true` "
    "(starts at level \"quiet\": digests only). See /inbox status after enabling."
)


def handle_inbox_command(args: str = "") -> str:
    from cron.attention_flush import preview_digest
    from cron.attention_policy import load_settings
    from hermes_cli.inbox_watch_cmd import handle_sources, handle_watch

    settings = load_settings()
    verb, _, rest = (args or "").strip().partition(" ")
    verb, rest = verb.lower(), rest.strip()
    if verb in ("help", "-h", "--help"):
        return _USAGE
    if verb == "status":
        return _status(settings, _now())
    if not settings.enabled:
        return _OFF_MESSAGE
    now = _now()
    handlers = {
        "": lambda: _list(settings, now),
        "list": lambda: _list(settings, now),
        "show": lambda: _show(rest, settings, now),
        "done": lambda: _resolve("done", rest, now),
        "dismiss": lambda: _resolve("dismiss", rest, now),
        "snooze": lambda: _snooze(rest, now),
        "less": lambda: _less(rest, now),
        "more": lambda: _more(rest, now),
        "loops": lambda: _loops(rest, now),
        "watch": lambda: handle_watch(rest, settings, now),
        "sources": lambda: handle_sources(rest, settings, now),
        "log": lambda: _log(now),
        "digest": lambda: preview_digest(now) or "Nothing is waiting for the next digest.",
    }
    handler = handlers.get(verb)
    return handler() if handler else _USAGE
