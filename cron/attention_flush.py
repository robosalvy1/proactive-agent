"""Attention flush: runs once per cron tick (under the per-home tick lock) for each served profile.

Order per flush: expire stale items → turn open loops into due check-ins → send immediate items
(outside quiet hours, within the daily interrupt budget) → send a digest when a digest slot has
passed. Sends reuse cron delivery (``_deliver_result``); an item without a resolvable target stays
in ``/inbox``. A digest slot is recorded BEFORE sending, so a crash can skip one digest but never
repeat it; undelivered items simply wait for the next slot.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from itertools import groupby
from typing import Any, Callable, Optional

from cron import attention as attention_api
from cron import attention_policy as policy
from cron import attention_store as store
from hermes_time import now as _hermes_now, safe_strftime

logger = logging.getLogger("cron.attention")

MAX_SEND_ATTEMPTS = 3
LAST_DIGEST_SLOT_KEY = "last_digest_slot"
DIGEST_MAX_CHARS = 3500
INTERRUPT_MAX_BODY_CHARS = 1500
# Open-loop check-in horizons.
LOOP_SOON = timedelta(hours=24)
LOOP_URGENT = timedelta(hours=2)
LOOP_OVERDUE_AFTER = timedelta(hours=24)
LOOP_UNDATED_AFTER = timedelta(days=3)

# (deliver, origin, text, adapters, loop) -> error string or None. Raises NoTarget when nothing
# resolves, so the item stays in the inbox instead of reading as delivered.
SendFn = Callable[[str, Optional[dict], str, Any, Any], Optional[str]]


class NoTarget(Exception):
    """The item's delivery value resolves to no concrete target."""


def short_id(item: dict) -> str:
    return str(item["id"])[:6]


def _effective_deliver(item_deliver: str, settings: policy.AttentionSettings) -> str:
    value = (item_deliver or "").strip()
    if value in ("", "local"):
        return settings.deliver or "local"
    return value


def send_via_cron_delivery(deliver: str, origin: Optional[dict], text: str, adapters=None,
                           loop=None) -> Optional[str]:
    """Send through the cron delivery path. The text is also mirrored into the target chat's
    transcript (user role, at a turn boundary), so a reply such as "yes, draft it" has context."""
    from cron.scheduler_delivery import _deliver_result, _resolve_delivery_targets

    job = {"id": "attention", "name": "Inbox", "deliver": deliver, "origin": origin,
           "attach_to_session": True}
    if not _resolve_delivery_targets(job):
        raise NoTarget(deliver)
    return _deliver_result(job, text, adapters=adapters, loop=loop)


# ── Composition ───────────────────────────────────────────────────────


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def display_body(item: dict) -> str:
    """The body without a leading line the title already shows."""
    lines = (item.get("body") or "").strip().splitlines()
    if lines and lines[0].strip(" #*").strip() and lines[0].strip(" #*").strip() in item["title"]:
        lines = lines[1:]
    return "\n".join(lines).strip()


def compose_interrupt(item: dict) -> str:
    parts = [item["title"]]
    if body := display_body(item):
        parts.append(_clip(body, INTERRUPT_MAX_BODY_CHARS))
    footer = f"Why now: {item['why_now']}" if item.get("why_now") else ""
    parts.append(f"{footer}{' · ' if footer else ''}/inbox done {short_id(item)}")
    return "\n\n".join(parts)


def compose_digest(items: list[dict]) -> str:
    header = f"Digest · {len(items)} item{'s' if len(items) != 1 else ''}"
    per_item = max(240, DIGEST_MAX_CHARS // max(1, len(items)) - 80)
    blocks = []
    for item in items:
        block = f"• {item['title']} [{short_id(item)}]"
        if body := display_body(item):
            block += "\n" + _clip(body, per_item)
        blocks.append(block)
    footer = "/inbox to review · /inbox done <id> · /inbox less <id> · /inbox snooze <id>"
    return "\n\n".join([header, *blocks, footer])


# ── Steps ─────────────────────────────────────────────────────────────


def _expire(now: datetime) -> int:
    with store.transaction() as conn:
        stale = store.select_items(
            conn, "status IN ('pending', 'sent') AND expires_at IS NOT NULL AND expires_at <= ?",
            (store.iso(now),))
        for item in stale:
            store.update_item(conn, item["id"], status="expired", resolved_at=store.iso(now))
            store.log_event(conn, now, item["id"], "expired", "")
        store.prune_events(conn)
    return len(stale)


def _fmt_due(due: datetime, now: datetime) -> str:
    local = due.astimezone(now.tzinfo)
    if local.date() == now.date():
        return safe_strftime(local, "today at %H:%M")
    if local.date() == (now + timedelta(days=1)).date():
        return safe_strftime(local, "tomorrow at %H:%M")
    return safe_strftime(local, "%a %d %b at %H:%M")


def loop_checkins(loop: dict, now: datetime) -> list[dict[str, Any]]:
    """Check-in item specs due for one open loop at ``now`` (each deduped by stage)."""
    title = loop["title"]
    evidence = loop.get("evidence") or ""
    said = f"You said: “{evidence}”\n\n" if evidence else ""
    due = store.parse_iso(loop.get("due_at"))
    if due is None:
        created = store.parse_iso(loop["created_at"])
        if created is not None and now - created >= LOOP_UNDATED_AFTER:
            return [{"stage": "stale", "kind": "ask", "urgency": 4,
                     "title": f"Still open: {title}",
                     "body": f"{said}Is this still on your list? Tell me if I can help, or close it.",
                     "why_now": f"open for {(now - created).days} days with no deadline"}]
        return []
    remaining = due - now
    when = _fmt_due(due, now)
    if remaining <= -LOOP_OVERDUE_AFTER:
        return [{"stage": "overdue", "kind": "ask", "urgency": 5, "title": f"Overdue: {title}",
                 "body": f"{said}This was due {when}. Still open, or already handled?",
                 "why_now": "deadline passed a day ago"}]
    if remaining <= LOOP_URGENT:
        overdue = remaining < timedelta(0)
        return [{"stage": "urgent", "kind": "alert", "urgency": 8,
                 "title": f"{'Overdue' if overdue else 'Due ' + when}: {title}",
                 "body": f"{said}Done already? Close it, or tell me how I can help.",
                 "why_now": "deadline passed" if overdue else f"due {when}"}]
    if remaining <= LOOP_SOON:
        return [{"stage": "soon", "kind": "ask", "urgency": 6, "title": f"Coming up: {title}",
                 "body": f"{said}Due {when}. Want help getting it done?",
                 "why_now": f"due {when}"}]
    return []


def sweep_open_loops(settings: policy.AttentionSettings, now: datetime) -> int:
    if not settings.open_loops:
        return 0
    with store.transaction() as conn:
        due = [(loop, spec) for loop in store.list_open_loops(conn) for spec in loop_checkins(loop, now)
               if not store.has_dedup_key(conn, f"loop:{loop['id']}:{spec['stage']}")]
    created = 0
    for loop, spec in due:
        item = attention_api.capture(
            kind=spec["kind"], title=spec["title"], body=spec["body"], source="open_loop",
            source_ref=loop.get("session_id") or "", category="open_loop",
            urgency=spec["urgency"], dedup_key=f"loop:{loop['id']}:{spec['stage']}",
            why_now=spec["why_now"], deliver=loop.get("deliver") or "local",
            origin=loop.get("origin"), loop_id=loop["id"], settings=settings, now=now,
        )
        if item is None:
            continue
        created += 1
        # A newer stage supersedes an earlier, still-open check-in for the same loop.
        with store.transaction() as conn:
            for older in store.select_items(
                    conn, "loop_id=? AND id<>? AND status IN ('pending', 'sent')",
                    (loop["id"], item["id"])):
                store.update_item(conn, older["id"], status="done", resolved_at=store.iso(now))
                store.log_event(conn, now, older["id"], "superseded", f"by {item['id']}")
    return created


def _send(send: SendFn, item_deliver: str, origin: Optional[dict], text: str,
          settings: policy.AttentionSettings, adapters, loop) -> tuple[str, Optional[str]]:
    """``("sent"|"no_target"|"failed", error)``."""
    deliver = _effective_deliver(item_deliver, settings)
    if deliver == "local":
        return "no_target", None
    try:
        error = send(deliver, origin if deliver == item_deliver else None, text, adapters, loop)
    except NoTarget:
        return "no_target", None
    except Exception as exc:  # delivery must never break the tick; retried, then digested
        logger.warning("Attention delivery to %s failed", deliver, exc_info=True)
        return "failed", str(exc)
    return ("failed", error) if error else ("sent", None)


def _send_interruptions(settings, now, send, adapters, loop, summary) -> None:
    with store.transaction() as conn:
        items = store.select_items(
            conn, "status='pending' AND route=? AND (snooze_until IS NULL OR snooze_until <= ?)",
            (policy.ROUTE_NOW, store.iso(now)))
        used = store.count_events_since(conn, "interrupted", policy.local_day_start(now))
    if not items:
        return
    if policy.in_quiet_hours(settings, now):
        with store.transaction() as conn:
            for item in items:
                if not store.has_event(conn, item["id"], "held_quiet_hours"):
                    store.log_event(conn, now, item["id"], "held_quiet_hours",
                                    "waits for quiet hours to end or the next digest")
        summary["held"] += len(items)
        return
    for item in items:
        if used >= settings.max_interrupts_per_day:
            with store.transaction() as conn:
                store.update_item(conn, item["id"], route=policy.ROUTE_DIGEST)
                store.log_event(conn, now, item["id"], "held_budget",
                                f"{used}/{settings.max_interrupts_per_day} interruptions used today")
            summary["held"] += 1
            continue
        outcome, error = _send(send, item["deliver"], item.get("origin"), compose_interrupt(item),
                               settings, adapters, loop)
        with store.transaction() as conn:
            if outcome == "sent":
                used += 1
                store.update_item(conn, item["id"], status="sent", delivered_at=store.iso(now))
                store.log_event(conn, now, item["id"], "interrupted", "sent immediately")
                summary["interrupted"] += 1
            elif outcome == "no_target":
                store.update_item(conn, item["id"], route=policy.ROUTE_INBOX)
                store.log_event(conn, now, item["id"], "inbox_only", "no delivery target configured")
            else:
                attempts = int(item.get("attempts") or 0) + 1
                fields: dict[str, Any] = {"attempts": attempts}
                if attempts >= MAX_SEND_ATTEMPTS:
                    fields["route"] = policy.ROUTE_DIGEST
                store.update_item(conn, item["id"], **fields)
                store.log_event(conn, now, item["id"], "delivery_failed", str(error or "")[:300])
                summary["failed"] += 1


def _origin_key(item: dict) -> str:
    return json.dumps(item.get("origin") or {}, sort_keys=True)


def _send_digest_if_due(settings, now, send, adapters, loop, summary) -> None:
    slot = policy.latest_digest_slot(settings, now)
    if slot is None:
        return
    with store.transaction() as conn:
        last = store.parse_iso(store.get_state(conn, LAST_DIGEST_SLOT_KEY))
        if last is not None and slot <= last:
            return
        store.set_state(conn, LAST_DIGEST_SLOT_KEY, store.iso(slot))
        if last is None:
            # First observation after enabling: start from the next slot, not a backlog.
            store.log_event(conn, now, None, "digest_baseline", store.iso(slot))
            return
        items = store.select_items(
            conn,
            "status='pending' AND route IN (?, ?) AND (snooze_until IS NULL OR snooze_until <= ?)",
            (policy.ROUTE_DIGEST, policy.ROUTE_NOW, store.iso(now)),
            order="deliver, origin, urgency DESC, created_at, id")
    def group_key(item: dict) -> tuple[str, str]:
        return _effective_deliver(item["deliver"], settings), _origin_key(item)

    for _key, grouped in groupby(items, key=group_key):
        group = list(grouped)
        outcome, error = _send(send, group[0]["deliver"], group[0].get("origin"),
                               compose_digest(group), settings, adapters, loop)
        with store.transaction() as conn:
            for item in group:
                if outcome == "sent":
                    store.update_item(conn, item["id"], status="sent", delivered_at=store.iso(now))
                    store.log_event(conn, now, item["id"], "digested", safe_strftime(slot, "%H:%M digest"))
                elif outcome == "failed":
                    store.log_event(conn, now, item["id"], "delivery_failed", str(error or "")[:300])
        if outcome == "sent":
            summary["digested"] += len(group)
        elif outcome == "failed":
            summary["failed"] += len(group)


def preview_digest(now: Optional[datetime] = None) -> str:
    """The digest text the next slot would send for the current inbox (no state change)."""
    now = now or _hermes_now()
    with store.transaction() as conn:
        items = store.select_items(
            conn,
            "status='pending' AND route IN (?, ?) AND (snooze_until IS NULL OR snooze_until <= ?)",
            (policy.ROUTE_DIGEST, policy.ROUTE_NOW, store.iso(now)),
            order="urgency DESC, created_at, id")
    return compose_digest(items) if items else ""


def flush(adapters=None, loop=None, *, now: Optional[datetime] = None,
          settings: Optional[policy.AttentionSettings] = None,
          send: Optional[SendFn] = None) -> dict[str, int]:
    """One attention pass for the active profile. Returns per-step counts (empty when inactive)."""
    # No store means nothing was ever captured: skip without loading config or creating the DB.
    if not store.current_attention_file().exists():
        return {}
    settings = settings or policy.load_settings()
    if not settings.active:
        return {}
    now = now or _hermes_now()
    send = send or send_via_cron_delivery
    summary = {"expired": _expire(now), "checkins": sweep_open_loops(settings, now),
               "interrupted": 0, "digested": 0, "held": 0, "failed": 0}
    _send_interruptions(settings, now, send, adapters, loop, summary)
    _send_digest_if_due(settings, now, send, adapters, loop, summary)
    _refresh_watch(settings, now)
    return summary


def _refresh_watch(settings: policy.AttentionSettings, now: datetime) -> None:
    """Hourly headless re-index of connected sources (``cron/attention_watch.py``), off-thread."""
    from cron import attention_watch

    try:
        attention_watch.maybe_refresh(now, settings)
    except Exception:  # watching is best-effort; delivery above already happened
        logger.warning("attention watch refresh failed", exc_info=True)
