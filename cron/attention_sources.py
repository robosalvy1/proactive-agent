"""Connected-source registry for proactive watching (``cron/attention_watch.py``).

Two producers keep the list current:

- the **index** (no model): enabled MCP servers, managed connector accounts the gateway reports as
  connected, and a few credentialed skills (Google Workspace token, himalaya, gh, Notion, Apple
  Reminders). It runs at most hourly from the cron tick, on a background thread.
- the weekly **discovery** run (a model with tools), for sources the index cannot see: a
  half-configured CLI, credentials in an unusual place, a connector that only works one way. Each
  discovered source records how it was verified.

A source the user removed is never re-added by either producer. An indexed source that disappears
is marked ``missing`` (its watcher stops); discovered sources stay until the user removes them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cron import attention_store as store

logger = logging.getLogger(__name__)

ACTIVE, MISSING, REMOVED = "active", "missing", "removed"
FOUND_BY_INDEX, FOUND_BY_DISCOVERY = "index", "discovery"
NO_MCP = "no_mcp"  # cron sentinel: a per-job allowlist without every enabled MCP server merged in
CONNECTOR_LIST_TIMEOUT = 5.0

# What a watcher looks for, per kind. A source may have several kinds ("calendar,email").
KIND_FOCUS = {
    "calendar": "new, moved or cancelled events; conflicts and tight transitions; meetings in the "
                "next 24h that need preparation, travel or a reply to an invitation",
    "email": "messages that need a reply or a decision from the user; deadlines, bills, renewals, "
             "deliveries and travel changes; security or account alerts. Ignore newsletters and "
             "promotions",
    "tasks": "tasks due soon or overdue; newly assigned work; blocked items",
    "code": "review requests, mentions, failing checks on the user's work, assigned issues",
    "notes": "pages or databases with due dates or items assigned to the user",
    "chat": "direct mentions and unanswered direct messages",
    "files": "files shared with the user or comments that ask something of them",
    "home": "devices offline, alarms, unusual states",
    "other": "anything that needs the user's attention or a decision soon",
}
_KIND_WORDS = (
    ("calendar", ("calendar", "gcal", "cal", "caldav", "ical", "outlook-calendar")),
    ("email", ("gmail", "mail", "email", "outlook", "imap", "himalaya", "fastmail", "proton")),
    ("tasks", ("todoist", "linear", "jira", "asana", "trello", "clickup", "tasks", "reminders",
               "things", "ticktick")),
    ("code", ("github", "gitlab", "bitbucket", "sentry")),
    ("notes", ("notion", "obsidian", "confluence", "coda", "evernote")),
    ("chat", ("slack", "discord", "teams", "telegram", "whatsapp")),
    ("files", ("drive", "dropbox", "box", "onedrive", "sharepoint")),
    ("home", ("homeassistant", "home-assistant", "hass", "nest", "hue")),
)


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    kind: str
    toolsets: tuple[str, ...]
    skills: tuple[str, ...] = ()
    hint: str = ""
    evidence: str = ""
    found_by: str = FOUND_BY_INDEX
    extra: dict = field(default_factory=dict, compare=False)


def guess_kind(name: str) -> str:
    tokens = set(re.split(r"[^a-z0-9]+", name.lower())) | {name.lower()}
    kinds = [kind for kind, words in _KIND_WORDS if tokens & set(words)]
    return ",".join(kinds) or "other"


def focus_for(kind: str) -> list[str]:
    return [KIND_FOCUS.get(k.strip(), KIND_FOCUS["other"]) for k in kind.split(",") if k.strip()]


# ── Headless index ────────────────────────────────────────────────────


def _mcp_sources(cfg: dict) -> list[Source]:
    from hermes_cli.tools_config import enabled_mcp_server_names

    return [Source(key=f"mcp:{name}", label=f"{name} (MCP)", kind=guess_kind(name), toolsets=(name,),
                   hint=f"Use the tools of the MCP server “{name}”.",
                   evidence="enabled in config.yaml mcp_servers")
            for name in sorted(enabled_mcp_server_names(cfg))]


def _connector_sources() -> list[Source]:
    """Managed connectors the gateway reports as connected. One bounded network read, no model."""
    from tools.connectors.gateway.config import connectors_available, guest_identity_pending

    if not connectors_available() or guest_identity_pending():
        return []
    from tools.connectors.gateway.client import ConnectorClient

    items = ConnectorClient().list_connectors(timeout=CONNECTOR_LIST_TIMEOUT)
    return [Source(key=f"connector:{item['connector']}", label=f"{item['connector']} (connected app)",
                   kind=guess_kind(item["connector"]), toolsets=("connections", NO_MCP),
                   hint=(f"Use tool_search for “connectors__{item['connector']}__” tools, "
                         "then call the read-only ones."),
                   evidence="reported connected by the connector gateway")
            for item in items if item.get("connected") and item.get("enabled", True)]


def _env(key: str) -> bool:
    if os.environ.get(key):
        return True
    try:
        from hermes_cli.config import get_env_value
        return bool(get_env_value(key))
    except Exception:  # an unreadable .env just means "not configured"
        logger.debug("env lookup for %s failed", key, exc_info=True)
        return False


def _skill_checks(home: Path) -> list[tuple[Source, bool]]:
    user = Path.home()
    skill = ("terminal", "skills", NO_MCP)
    return [
        (Source("skill:google-workspace", "Google Workspace (Gmail, Calendar, Drive)", "calendar,email,files",
                skill, ("google-workspace",), "Use the google-workspace skill's google_api.py (read-only commands).",
                "google_token.json present"),
         (home / "google_token.json").exists()),
        (Source("skill:himalaya", "Email (himalaya)", "email", skill, ("himalaya",),
                "Use himalaya to list recent envelopes; read only what matters.",
                "himalaya installed and configured"),
         bool(shutil.which("himalaya")) and (user / ".config" / "himalaya" / "config.toml").exists()),
        (Source("skill:github", "GitHub (gh)", "code", skill, ("github",),
                "Use `gh` read-only: notifications, review requests, assigned issues, failing checks.",
                "gh installed and authenticated"),
         bool(shutil.which("gh")) and ((user / ".config" / "gh" / "hosts.yml").exists()
                                       or _env("GH_TOKEN") or _env("GITHUB_TOKEN"))),
        (Source("skill:notion", "Notion", "notes,tasks", skill, ("notion",),
                "Use the notion skill (read-only queries).", "NOTION_API_KEY set"),
         _env("NOTION_API_KEY")),
        (Source("skill:apple-reminders", "Apple Reminders", "tasks", skill, ("apple-reminders",),
                "Use `remindctl` to list due and overdue reminders.", "remindctl installed"),
         sys.platform == "darwin" and bool(shutil.which("remindctl"))),
    ]


def index_sources(cfg: Optional[dict] = None) -> list[Source]:
    """Every source the index can see. A failing detector costs only its own sources."""
    from hermes_cli.config import load_config_readonly
    from hermes_constants import get_hermes_home

    cfg = cfg if cfg is not None else (load_config_readonly() or {})
    found: list[Source] = []
    for detector in (lambda: _mcp_sources(cfg), _connector_sources,
                     lambda: [s for s, ok in _skill_checks(get_hermes_home()) if ok]):
        try:
            found.extend(detector())
        except Exception:  # one broken connector must not hide the others
            logger.warning("attention source detector failed", exc_info=True)
    return found


# ── Registry ──────────────────────────────────────────────────────────


def _row(row) -> dict[str, Any]:
    record = dict(row)
    record["toolsets"] = json.loads(record["toolsets"] or "[]")
    record["skills"] = json.loads(record["skills"] or "[]")
    return record


def list_sources(conn, statuses: tuple[str, ...] = (ACTIVE,)) -> list[dict[str, Any]]:
    marks = ", ".join("?" for _ in statuses)
    rows = conn.execute(f"SELECT * FROM attention_sources WHERE status IN ({marks}) ORDER BY key",
                        statuses).fetchall()
    return [_row(row) for row in rows]


def get_source(conn, key: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM attention_sources WHERE key=?", (key,)).fetchone()
    return _row(row) if row else None


def source_for_job(conn, job_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM attention_sources WHERE job_id=?", (job_id,)).fetchone()
    return _row(row) if row else None


def set_source(conn, key: str, **fields: Any) -> None:
    assignments = ", ".join(f"{name}=?" for name in fields)
    conn.execute(f"UPDATE attention_sources SET {assignments} WHERE key=?", (*fields.values(), key))


def _upsert(conn, source: Source, now: datetime) -> str:
    """Insert or refresh ``source``. Returns "added", "updated" or "removed" (user latch kept)."""
    existing = get_source(conn, source.key)
    if existing and existing["status"] == REMOVED:
        return REMOVED
    values = (source.label, source.kind, json.dumps(list(source.toolsets)), json.dumps(list(source.skills)),
              source.hint[:500], source.evidence[:500])
    if existing is None:
        conn.execute(
            "INSERT INTO attention_sources (key, label, kind, toolsets, skills, hint, evidence, found_by, "
            "status, job_id, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (source.key, *values, source.found_by, ACTIVE, store.iso(now), store.iso(now)))
        return "added"
    # The index is authoritative for what it can see; discovery never overwrites an indexed source.
    if existing["found_by"] == FOUND_BY_INDEX and source.found_by == FOUND_BY_DISCOVERY:
        return "updated"
    conn.execute(
        "UPDATE attention_sources SET label=?, kind=?, toolsets=?, skills=?, hint=?, evidence=?, "
        "found_by=?, status=?, last_seen=? WHERE key=?",
        (*values, source.found_by, ACTIVE, store.iso(now), source.key))
    return "updated"


def apply_index(sources: list[Source], now: datetime) -> dict[str, list[str]]:
    """Merge an index pass. Indexed sources not seen this time become ``missing``."""
    changes: dict[str, list[str]] = {"added": [], "missing": []}
    seen = {source.key for source in sources}
    with store.transaction() as conn:
        for source in sources:
            if _upsert(conn, source, now) == "added":
                changes["added"].append(source.label)
        for row in list_sources(conn):
            if row["found_by"] == FOUND_BY_INDEX and row["key"] not in seen:
                set_source(conn, row["key"], status=MISSING)
                changes["missing"].append(row["label"])
        for label in changes["added"]:
            store.log_event(conn, now, None, "source_added", f"index: {label}")
        for label in changes["missing"]:
            store.log_event(conn, now, None, "source_missing", label)
    return changes


def apply_discovered(sources: list[Source], now: datetime) -> list[str]:
    """Merge a discovery run's verified sources. Returns the labels that are new."""
    added = []
    with store.transaction() as conn:
        for source in sources:
            if _upsert(conn, source, now) == "added":
                added.append(source.label)
                store.log_event(conn, now, None, "source_added", f"discovery: {source.label} — {source.evidence}")
    return added


def remove_source(key: str, now: datetime) -> bool:
    with store.transaction() as conn:
        row = get_source(conn, key)
        if row is None or row["status"] == REMOVED:
            return False
        set_source(conn, key, status=REMOVED)
        store.log_event(conn, now, None, "source_removed", f"by user: {row['label']}")
    return True


def restore_source(key: str, now: datetime) -> bool:
    with store.transaction() as conn:
        row = get_source(conn, key)
        if row is None or row["status"] != REMOVED:
            return False
        set_source(conn, key, status=ACTIVE, last_seen=store.iso(now))
        store.log_event(conn, now, None, "source_restored", row["label"])
    return True
