"""Attention layer facade: every proactive output becomes an *item* that a deterministic gate routes
to an immediate interruption, the next digest, or the inbox only.

Producers call :func:`capture` (cron results via :func:`capture_cron_result`, open-loop check-ins
from ``cron/attention_flush.py``). The gateway's cron tick calls ``attention_flush.flush`` to send
due interruptions and digests. ``/inbox`` (``hermes_cli/inbox_cmd.py``) reads and resolves items.
Nothing here runs a model, and nothing is captured unless ``attention.enabled`` is true.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from cron import attention_policy as policy
from cron import attention_store as store
from hermes_time import now as _hermes_now

logger = logging.getLogger(__name__)

KINDS = ("inform", "ask", "propose", "alert")
DEFAULT_TTL = timedelta(days=7)
MUTED_STATE_KEY = "muted_categories"

# An agent marks a time-critical cron result by starting it with [ALERT] (any case).
_ALERT_MARKER = re.compile(r"^\s*\[alert\]\s*", re.IGNORECASE)
CRON_ALERT_URGENCY = 8
CRON_DEFAULT_URGENCY = 5


def _now(now: Optional[datetime]) -> datetime:
    return now or _hermes_now()


def capture(
    *, kind: str, title: str, body: str, source: str, category: str, urgency: int, dedup_key: str,
    why_now: str = "", deliver: str = "local", origin: Optional[dict] = None, source_ref: str = "",
    loop_id: Optional[str] = None, ttl: timedelta = DEFAULT_TTL,
    settings: Optional[policy.AttentionSettings] = None, now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Record a proactive item and its route. Returns the item, or None when the layer is inactive
    or ``dedup_key`` was already captured (the duplicate is logged)."""
    if kind not in KINDS:
        raise ValueError(f"unknown attention kind: {kind!r}")
    settings = settings or policy.load_settings()
    if not settings.active:
        return None
    now = _now(now)
    urgency = max(0, min(10, int(urgency)))
    with store.transaction() as conn:
        muted = category in store.get_json_state(conn, MUTED_STATE_KEY, [])
        route, reason = policy.decide_route(settings, kind=kind, urgency=urgency, muted=muted)
        item = store.insert_item(conn, {
            "kind": kind, "title": title, "body": body, "why_now": why_now, "source": source,
            "source_ref": source_ref, "category": category, "urgency": urgency,
            "dedup_key": dedup_key, "deliver": deliver, "origin": origin, "status": "pending",
            "route": route, "loop_id": loop_id, "created_at": store.iso(now),
            "expires_at": store.iso(now + ttl),
        })
        if item is None:
            store.log_event(conn, now, None, "duplicate", f"{category}: {title}"[:200])
            return None
        store.log_event(conn, now, item["id"], "captured", f"route={route}: {reason}")
    return item


# ── Cron integration ──────────────────────────────────────────────────


def routes_cron_job(job: dict, settings: Optional[policy.AttentionSettings] = None) -> bool:
    """Whether a successful run of ``job`` goes through the gate instead of direct delivery.

    Only recurring jobs: a one-shot is a reminder the user timed explicitly and delivers as asked."""
    from cron.constants import is_recurring

    if not is_recurring(job):
        return False
    settings = settings or policy.load_settings()
    return settings.active and settings.route_cron


def split_alert_marker(text: str) -> tuple[bool, str]:
    match = _ALERT_MARKER.match(text or "")
    if not match:
        return False, text
    return True, text[match.end():]


def _cron_title(job: dict, body: str) -> str:
    name = str(job.get("name") or "").strip()
    first_line = next((line.strip(" #*") for line in body.splitlines() if line.strip()), "")
    if name and first_line and first_line.lower() != name.lower():
        return f"{name}: {first_line[:120]}"
    return name or first_line[:120] or str(job.get("id") or "Scheduled job")


def capture_cron_result(job: dict, content: str, *, settings: Optional[policy.AttentionSettings] = None,
                        now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Capture a successful cron result. Identical output from the same job is a duplicate."""
    is_alert, body = split_alert_marker(content)
    body = body.strip()
    digest = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:16]
    job_id = str(job.get("id") or "")
    name = str(job.get("name") or job_id)
    return capture(
        kind="alert" if is_alert else "inform",
        title=_cron_title(job, body),
        body=body,
        source="cron",
        source_ref=job_id,
        category=f"cron:{name}",
        urgency=CRON_ALERT_URGENCY if is_alert else CRON_DEFAULT_URGENCY,
        dedup_key=f"cron:{job_id}:{digest}",
        why_now="marked time-critical by the job" if is_alert else f"new result from “{name}”",
        deliver=str(job.get("deliver") or "local"),
        origin=job.get("origin") if isinstance(job.get("origin"), dict) else None,
        settings=settings,
        now=now,
    )


CRON_ATTENTION_GUIDANCE = (
    "ATTENTION: This result goes to the user's inbox and next digest unless it is time-critical. "
    "If the user must act within the next few hours, start your response with \"[ALERT]\" "
    "(a literal ASCII token) followed by the result; otherwise do not use it."
)


# ── Inbox operations (used by /inbox) ─────────────────────────────────


def inbox(now: Optional[datetime] = None) -> list[dict[str, Any]]:
    with store.transaction() as conn:
        return store.open_items(conn, _now(now))


def resolve_ref(ref: str, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """An open item by 1-based inbox number or id (prefix of at least 4 characters)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    items = inbox(now)
    if ref.isdigit() and 0 < int(ref) <= len(items):
        return items[int(ref) - 1]
    matches = [item for item in items if len(ref) >= 4 and item["id"].startswith(ref)]
    return matches[0] if len(matches) == 1 else None


def resolve_item(item: dict[str, Any], status: str, now: Optional[datetime] = None) -> None:
    """Close an item (``done`` or ``dismissed``). Closing an open-loop check-in closes its loop."""
    if status not in ("done", "dismissed"):
        raise ValueError(f"cannot resolve an item as {status!r}")
    now = _now(now)
    with store.transaction() as conn:
        store.update_item(conn, item["id"], status=status, resolved_at=store.iso(now))
        store.log_event(conn, now, item["id"], status, "by user")
        if item.get("loop_id"):
            loop_status = "done" if status == "done" else "cancelled"
            if store.set_loop_status(conn, item["loop_id"], loop_status, now):
                _close_loop_items(conn, item["loop_id"], now, exclude=item["id"])


def _close_loop_items(conn, loop_id: str, now: datetime, *, exclude: Optional[str] = None) -> None:
    for other in store.select_items(conn, "loop_id=? AND status IN ('pending', 'sent')", (loop_id,)):
        if other["id"] != exclude:
            store.update_item(conn, other["id"], status="done", resolved_at=store.iso(now))
            store.log_event(conn, now, other["id"], "done", "open loop closed")


def snooze_item(item: dict[str, Any], until: datetime, now: Optional[datetime] = None) -> None:
    """Hide until ``until``; it returns to the inbox and the next digest after that."""
    now = _now(now)
    with store.transaction() as conn:
        store.update_item(conn, item["id"], snooze_until=store.iso(until), status="pending",
                          route=policy.ROUTE_DIGEST, delivered_at=None)
        store.log_event(conn, now, item["id"], "snoozed", f"until {store.iso(until)}")


def muted_categories() -> list[str]:
    with store.transaction() as conn:
        return list(store.get_json_state(conn, MUTED_STATE_KEY, []))


def set_category_muted(category: str, muted: bool, now: Optional[datetime] = None) -> bool:
    """Mute ("less like this") or unmute a category. Returns whether anything changed."""
    now = _now(now)
    with store.transaction() as conn:
        current = list(store.get_json_state(conn, MUTED_STATE_KEY, []))
        if (category in current) == muted:
            return False
        current = sorted({*current, category}) if muted else [c for c in current if c != category]
        store.set_state(conn, MUTED_STATE_KEY, json.dumps(current))
        if muted:
            # Already-captured items of the category stop being pushed or digested too.
            conn.execute(
                "UPDATE attention_items SET route=? WHERE category=? AND status='pending'",
                (policy.ROUTE_INBOX, category),
            )
        store.log_event(conn, now, None, "muted" if muted else "unmuted", category)
    return True


def activity(limit: int = 20) -> list[dict[str, Any]]:
    with store.transaction() as conn:
        return store.recent_events(conn, limit)


def open_loops() -> list[dict[str, Any]]:
    with store.transaction() as conn:
        return store.list_open_loops(conn)


def close_open_loop(loop_id: str, status: str, now: Optional[datetime] = None) -> bool:
    if status not in ("done", "cancelled"):
        raise ValueError(f"cannot close an open loop as {status!r}")
    now = _now(now)
    with store.transaction() as conn:
        changed = store.set_loop_status(conn, loop_id, status, now)
        if changed:
            store.log_event(conn, now, None, f"loop_{status}", loop_id)
            _close_loop_items(conn, loop_id, now)
    return changed
