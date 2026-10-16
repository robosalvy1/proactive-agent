"""Open loops: commitments and deadlines the user states in chat, tracked so the attention layer can
check in before they lapse (``cron/attention_flush.py::sweep_open_loops``).

Cheap gate first, model second: a regex/token pre-filter decides whether the user's message could
contain a new commitment or close a tracked one; only then one auxiliary ``open_loops`` call
extracts candidates as JSON. Every candidate must quote the user's own words (checked verbatim
against the message), so assistant suggestions and invented tasks never become loops. Runs after
the turn on a daemon thread, outside the conversation: no prompt or toolset changes, cache-safe.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time as time_module
from datetime import datetime, time, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Captures started but not finished; one-shot exit waits for them (wait_for_pending_captures).
_pending: set[threading.Thread] = set()
_pending_guard = threading.Lock()

MAX_NEW_PER_TURN = 3
MAX_OPEN_LOOPS = 50
MAX_MESSAGE_CHARS = 4000
MIN_EVIDENCE_CHARS = 6
DATE_ONLY_DUE_TIME = time(18, 0)

_COMMITMENT = re.compile(
    r"\b(remind me|don'?t (let me )?forget|need to|needs to|have to|has to|got to|gotta|must|"
    r"i'?ll|i will|i'?m going to|going to|promised|deadline|due|appointment|renew|"
    r"pay|submit|book|sign up|register|apply|file|cancel|call|email|send|follow up|expires?)\b",
    re.IGNORECASE)
_TIME = re.compile(
    r"\b(today|tonight|tomorrow|this (morning|afternoon|evening|week|weekend|month)|"
    r"next (week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(rs(day)?)?|fri(day)?|sat(urday)?|sun(day)?|"
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|"
    r"oct(ober)?|nov(ember)?|dec(ember)?|by|before|until|end of|in \d+ (days?|weeks?|months?)|"
    r"\d{1,2}(st|nd|rd|th)|\d{1,2}[/.-]\d{1,2}|\d{1,2}(:\d{2})?\s?(am|pm)|deadline|due)\b",
    re.IGNORECASE)
_ALWAYS = re.compile(r"\b(remind me|don'?t (let me )?forget)\b", re.IGNORECASE)
_COMPLETION = re.compile(
    r"\b(done|did|finished|completed|booked|paid|renewed|submitted|sent|signed|filed|handled|"
    r"sorted|took care|cancel(l?ed)?|no longer|never ?mind|not (doing|going)|already)\b",
    re.IGNORECASE)
_STOPWORDS = frozenset({"the", "a", "an", "to", "my", "for", "and", "of", "on", "in", "at", "by",
                        "with", "up", "get", "do", "make"})

_SYSTEM_PROMPT = (
    "You track the user's own open commitments for a personal assistant. Read ONLY the user's "
    "latest message. Extract tasks, appointments or deadlines the USER states they need to do "
    "or must remember. Do not extract: suggestions, hypotheticals, things other people must do, "
    "questions to the assistant, or tasks the assistant is doing right now in this chat. Also "
    "report which already-tracked loops the message says are done or cancelled.\n"
    "Return JSON only: {\"add\": [{\"title\": short imperative phrase, \"due\": "
    "\"YYYY-MM-DD\" or \"YYYY-MM-DDTHH:MM\" in the user's local time or null, \"evidence\": the "
    "exact words copied from the message}], \"close\": [{\"id\": tracked loop id, \"status\": "
    "\"done\" or \"cancelled\", \"evidence\": exact words copied from the message}]}. "
    "Use empty lists when there is nothing. Resolve relative dates against the current time."
)


def message_text(message: Any) -> str:
    """Plain text of a user message (string or multimodal content parts)."""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return "\n".join(
            str(part.get("text") or "") for part in message
            if isinstance(part, dict) and part.get("type") in ("text", "input_text"))
    return ""


def _significant_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in _STOPWORDS}


def needs_extraction(text: str, open_titles: list[str]) -> bool:
    """Deterministic pre-filter: a new commitment (commitment + time cue, or an explicit
    "remind me"), or a completion cue that overlaps a tracked loop's title."""
    if not text.strip():
        return False
    if _ALWAYS.search(text) or (_COMMITMENT.search(text) and _TIME.search(text)):
        return True
    if open_titles and _COMPLETION.search(text):
        words = _significant_tokens(text)
        return any(words & _significant_tokens(title) for title in open_titles)
    return False


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[‘’]", "'", re.sub(r"[“”]", '"', text)).lower().split())


def evidence_in_message(evidence: str, message: str) -> bool:
    quote = _normalize(str(evidence or "")).strip(" \"'.,!?")
    return len(quote) >= MIN_EVIDENCE_CHARS and quote in _normalize(message)


def parse_due(value: Any, now: datetime) -> Optional[datetime]:
    """A local due instant from ``YYYY-MM-DD[THH:MM]``; None when absent, malformed, or more than a
    day in the past (a misread date is worse than no date)."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if "T" in raw or " " in raw:
            parsed = datetime.fromisoformat(raw.replace(" ", "T"))
        else:
            parsed = datetime.combine(datetime.fromisoformat(raw).date(), DATE_ONLY_DUE_TIME)
    except ValueError:
        return None
    due = parsed.replace(tzinfo=now.tzinfo) if parsed.tzinfo is None else parsed.astimezone(now.tzinfo)
    return None if due < now - timedelta(days=1) else due


def _build_user_prompt(text: str, open_loops: list[dict], now: datetime) -> str:
    from hermes_time import safe_strftime

    tracked = [{"id": loop["id"], "title": loop["title"]} for loop in open_loops]
    return (
        f"Current local time: {safe_strftime(now, '%A %Y-%m-%d %H:%M')}\n"
        f"Tracked open loops: {json.dumps(tracked)}\n\n"
        f"User message:\n{text[:MAX_MESSAGE_CHARS]}"
    )


def _parse_payload(content: str) -> dict[str, list]:
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return {"add": [], "close": []}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {"add": [], "close": []}
    if not isinstance(data, dict):
        return {"add": [], "close": []}
    return {key: [x for x in data.get(key) or [] if isinstance(x, dict)] for key in ("add", "close")}


def extract(text: str, open_loops: list[dict], now: datetime) -> dict[str, list]:
    """One auxiliary call; returns validated ``{"add": [...], "close": [...]}``."""
    from agent.auxiliary_client import call_llm

    response = call_llm(
        task="open_loops",
        messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                  {"role": "user", "content": _build_user_prompt(text, open_loops, now)}],
        max_tokens=800, temperature=0)
    content = response.choices[0].message.content
    payload = _parse_payload(content if isinstance(content, str) else str(content or ""))
    tracked_ids = {loop["id"] for loop in open_loops}
    adds = []
    for entry in payload["add"][:MAX_NEW_PER_TURN]:
        title = " ".join(str(entry.get("title") or "").split())
        if title and evidence_in_message(entry.get("evidence"), text):
            adds.append({"title": title, "due": parse_due(entry.get("due"), now),
                         "evidence": str(entry.get("evidence")).strip()})
    closes = [
        {"id": entry["id"], "status": entry.get("status")}
        for entry in payload["close"]
        if entry.get("id") in tracked_ids and entry.get("status") in ("done", "cancelled")
        and evidence_in_message(entry.get("evidence"), text)
    ]
    return {"add": adds, "close": closes}


def capture_from_message(message: Any, *, session_id: str = "", origin: Optional[dict] = None,
                         now: Optional[datetime] = None) -> dict[str, int]:
    """Run the gate and, when it passes, extraction + store writes. Returns counts."""
    from cron import attention_policy as policy
    from cron import attention_store as store
    from cron.attention import close_loop_items
    from hermes_time import now as hermes_now

    settings = policy.load_settings()
    if not (settings.active and settings.open_loops):
        return {"added": 0, "closed": 0}
    text = message_text(message)
    now = now or hermes_now()
    open_loops = []
    if store.current_attention_file().exists():
        with store.transaction() as conn:
            open_loops = store.list_open_loops(conn)
    if not needs_extraction(text, [loop["title"] for loop in open_loops]):
        return {"added": 0, "closed": 0}
    result = extract(text, open_loops, now)
    added = closed = 0
    with store.transaction() as conn:
        for close in result["close"]:
            if store.set_loop_status(conn, close["id"], close["status"], now):
                closed += 1
                store.log_event(conn, now, None, f"loop_{close['status']}", f"{close['id']}: from chat")
                close_loop_items(conn, close["id"], now)
        remaining = MAX_OPEN_LOOPS - len(store.list_open_loops(conn))
        for entry in result["add"][:max(0, remaining)]:
            loop = store.add_open_loop(
                conn, title=entry["title"], due_at=entry["due"], evidence=entry["evidence"],
                session_id=session_id, deliver="origin" if origin else "local", origin=origin, now=now)
            if loop is not None:
                added += 1
                store.log_event(conn, now, None, "loop_added", f"{loop['id']}: {loop['title']}")
    return {"added": added, "closed": closed}


def _eligible(agent: Any) -> bool:
    return not (
        getattr(agent, "skip_background_review", False)
        or getattr(agent, "skip_memory", False)
        or getattr(agent, "platform", "") == "cron"
        or getattr(agent, "_delegate_depth", 0)
    )


def maybe_capture_after_turn(agent: Any, user_message: Any) -> None:
    """Post-turn hook: start capture on a daemon thread when the agent is an interactive one.

    The delivery origin is read here, on the turn's thread, where the session context is bound."""
    if not _eligible(agent) or not message_text(user_message).strip():
        return
    from cron.attention_policy import load_settings

    settings = load_settings()
    if not (settings.active and settings.open_loops):
        return
    from agent.memory_provider import spawn_context_thread
    from tools.cronjob_job_args import _origin_from_env

    origin = _origin_from_env()
    session_id = str(getattr(agent, "session_id", "") or "")

    def _run() -> None:
        try:
            capture_from_message(user_message, session_id=session_id, origin=origin)
        except Exception:  # background capture must never surface into the chat
            logger.warning("Open-loop capture failed (non-fatal)", exc_info=True)
        finally:
            with _pending_guard:
                _pending.discard(threading.current_thread())

    thread = spawn_context_thread(_run, name="open-loops")
    with _pending_guard:
        _pending.add(thread)
    thread.start()


def wait_for_pending_captures(timeout: float = 20.0) -> None:
    """Let started captures commit before a one-shot process hard-exits (``hermes -z``)."""
    deadline = time_module.monotonic() + timeout
    with _pending_guard:
        threads = list(_pending)
    for thread in threads:
        thread.join(max(0.0, deadline - time_module.monotonic()))
