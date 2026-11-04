"""Profile-local SQLite store for the attention layer: items, the activity log, small state and
open loops. Same connection/pragma pattern as ``cron/notepad.py``; the path resolves at call time
so a multiplexed tick (profile scope bound per home) never writes another profile's store.

Timestamps are stored as UTC ISO-8601 strings so SQL comparisons order correctly; callers pass
tz-aware datetimes and format for display in the profile timezone.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from hermes_constants import get_hermes_home

# Optional test override; production resolves per call (see module docstring).
ATTENTION_FILE: Optional[Path] = None
_lock = threading.RLock()

OPEN_STATUSES = ("pending", "sent")
MAX_TITLE_CHARS = 200
MAX_BODY_CHARS = 16_000
MAX_EVENTS_KEPT = 2000

_ITEM_COLUMNS = (
    "id", "kind", "title", "body", "why_now", "source", "source_ref", "category", "urgency",
    "dedup_key", "deliver", "origin", "status", "route", "attempts", "loop_id", "created_at",
    "expires_at", "delivered_at", "resolved_at", "snooze_until",
)


def current_attention_file() -> Path:
    return ATTENTION_FILE or (get_hermes_home().resolve() / "cron" / "attention.db")


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS attention_items (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            why_now TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            source_ref TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            urgency INTEGER NOT NULL,
            dedup_key TEXT NOT NULL UNIQUE,
            deliver TEXT NOT NULL DEFAULT 'local',
            origin TEXT,
            status TEXT NOT NULL,
            route TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            loop_id TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            delivered_at TEXT,
            resolved_at TEXT,
            snooze_until TEXT
        );
        CREATE INDEX IF NOT EXISTS attention_items_status ON attention_items(status, route);
        CREATE TABLE IF NOT EXISTS attention_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            item_id TEXT,
            event TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS attention_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS open_loops (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            norm_title TEXT NOT NULL,
            due_at TEXT,
            evidence TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            deliver TEXT NOT NULL DEFAULT 'local',
            origin TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS open_loops_open_title
            ON open_loops(norm_title) WHERE status = 'open';
        CREATE TABLE IF NOT EXISTS attention_sources (
            key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            kind TEXT NOT NULL,
            toolsets TEXT NOT NULL DEFAULT '[]',
            skills TEXT NOT NULL DEFAULT '[]',
            hint TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            found_by TEXT NOT NULL,
            status TEXT NOT NULL,
            job_id TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        """
    )


def _connect() -> sqlite3.Connection:
    from cron.jobs import _ensure_cron_dir
    from hermes_cli.sqlite_util import open_db

    path = current_attention_file()
    _ensure_cron_dir(path.parent)
    return open_db(path, db_label="cron/attention.db", initialize=_initialize_schema)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    from hermes_cli.sqlite_util import transaction as _sqlite_transaction

    with _lock, _sqlite_transaction(_connect(), immediate=True) as conn:
        yield conn


def _item_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["origin"] = json.loads(item["origin"]) if item.get("origin") else None
    return item


def log_event(conn: sqlite3.Connection, at: datetime, item_id: Optional[str], event: str,
              detail: str = "") -> None:
    conn.execute(
        "INSERT INTO attention_events (at, item_id, event, detail) VALUES (?, ?, ?, ?)",
        (iso(at), item_id, event, detail[:500]),
    )


def insert_item(conn: sqlite3.Connection, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Insert a new item; None when ``dedup_key`` was already seen (any status)."""
    record = {column: None for column in _ITEM_COLUMNS}
    record.update(fields)
    record["id"] = record["id"] or uuid.uuid4().hex[:12]
    record["title"] = str(record["title"] or "").strip()[:MAX_TITLE_CHARS] or "(untitled)"
    record["body"] = str(record["body"] or "")[:MAX_BODY_CHARS]
    record["attempts"] = record["attempts"] or 0
    for key in ("why_now", "source_ref"):
        record[key] = record[key] or ""
    record["deliver"] = record["deliver"] or "local"
    stored = dict(record)
    stored["origin"] = json.dumps(record["origin"]) if record["origin"] else None
    try:
        conn.execute(
            f"INSERT INTO attention_items ({', '.join(_ITEM_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _ITEM_COLUMNS)})",
            tuple(stored[column] for column in _ITEM_COLUMNS),
        )
    except sqlite3.IntegrityError:
        return None
    return record


def has_dedup_key(conn: sqlite3.Connection, dedup_key: str) -> bool:
    return conn.execute("SELECT 1 FROM attention_items WHERE dedup_key=?", (dedup_key,)).fetchone() is not None


def update_item(conn: sqlite3.Connection, item_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key}=?" for key in fields)
    conn.execute(f"UPDATE attention_items SET {assignments} WHERE id=?", (*fields.values(), item_id))


def select_items(conn: sqlite3.Connection, where: str = "1=1", params: tuple = (),
                 order: str = "created_at, id") -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT * FROM attention_items WHERE {where} ORDER BY {order}", params).fetchall()
    return [_item_from_row(row) for row in rows]


def open_items(conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    """Unresolved, un-snoozed items in inbox order (most urgent first, then oldest)."""
    return select_items(
        conn,
        "status IN ('pending', 'sent') AND (snooze_until IS NULL OR snooze_until <= ?)",
        (iso(now),),
        order="urgency DESC, created_at, id",
    )


def count_events_since(conn: sqlite3.Connection, event: str, since: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM attention_events WHERE event=? AND at>=?", (event, iso(since)),
    ).fetchone()
    return int(row[0])


def has_event(conn: sqlite3.Connection, item_id: str, event: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM attention_events WHERE item_id=? AND event=? LIMIT 1", (item_id, event),
    ).fetchone()
    return row is not None


def recent_events(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.at, e.item_id, e.event, e.detail, i.title
             FROM attention_events e LEFT JOIN attention_items i ON i.id = e.item_id
            ORDER BY e.seq DESC LIMIT ?""",
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def prune_events(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM attention_events WHERE seq <= "
        "(SELECT COALESCE(MAX(seq), 0) - ? FROM attention_events)",
        (MAX_EVENTS_KEPT,),
    )


def get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM attention_state WHERE key=?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO attention_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_json_state(conn: sqlite3.Connection, key: str, default: Any) -> Any:
    raw = get_state(conn, key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


# ── Open loops ────────────────────────────────────────────────────────


def normalize_title(title: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in title).split())


def _loop_from_row(row: sqlite3.Row) -> dict[str, Any]:
    loop = dict(row)
    loop["origin"] = json.loads(loop["origin"]) if loop.get("origin") else None
    return loop


def add_open_loop(conn: sqlite3.Connection, *, title: str, due_at: Optional[datetime], evidence: str,
                  session_id: str, deliver: str, origin: Optional[dict], now: datetime,
                  ) -> Optional[dict[str, Any]]:
    """Insert an open loop; None when an equivalent title is already open."""
    title = title.strip()[:MAX_TITLE_CHARS]
    norm = normalize_title(title)
    if not norm:
        return None
    loop_id = uuid.uuid4().hex[:12]
    try:
        conn.execute(
            """INSERT INTO open_loops (id, title, norm_title, due_at, evidence, session_id,
                   deliver, origin, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (loop_id, title, norm, iso(due_at) if due_at else None, evidence[:500], session_id or "",
             deliver or "local", json.dumps(origin) if origin else None, iso(now), iso(now)),
        )
    except sqlite3.IntegrityError:
        return None
    row = conn.execute("SELECT * FROM open_loops WHERE id=?", (loop_id,)).fetchone()
    return _loop_from_row(row)


def list_open_loops(conn: sqlite3.Connection, statuses: tuple[str, ...] = ("open",)) -> list[dict[str, Any]]:
    marks = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM open_loops WHERE status IN ({marks}) "
        "ORDER BY due_at IS NULL, due_at, created_at",
        statuses,
    ).fetchall()
    return [_loop_from_row(row) for row in rows]


def set_loop_status(conn: sqlite3.Connection, loop_id: str, status: str, now: datetime) -> bool:
    cur = conn.execute(
        "UPDATE open_loops SET status=?, updated_at=? WHERE id=? AND status='open'",
        (status, iso(now), loop_id),
    )
    return cur.rowcount > 0
