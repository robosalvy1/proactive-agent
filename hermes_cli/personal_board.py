"""The personal home's tile board, stored per profile so the person and the agent share one view.

The person arranges and configures every tile. The agent may add cards too, but only from a fixed
catalog and only with what it actually has: *live* cards bind to a capability the profile already has
(Google Calendar, scheduled jobs, recent chats, clocks) and render with the home's own tiles; *content*
cards (list, stats, text) carry data the agent fetched with its own tools and must name that source.
The agent never chooses colors, icons, markup or layout, never touches tiles the person added, and a
card the person removes is remembered so it is not re-added unprompted.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from hermes_constants import get_hermes_home
from utils import atomic_write_text

BOARD_FILE = "personal_board.json"
LIVE_KINDS = ("calendar", "shortcuts", "scheduled", "recent", "note", "clock")
CONTENT_KINDS = ("list", "stats", "text")
KINDS = LIVE_KINDS + CONTENT_KINDS
# Only one of these on a board; the rest may repeat.
SINGLE = {"calendar", "shortcuts", "scheduled", "recent"}
# What the agent may add. Shortcuts and notes are the person's own words.
AGENT_KINDS = ("calendar", "scheduled", "recent", "clock") + CONTENT_KINDS
MAX_TILES = 16
MAX_AGENT_TILES = 6
MAX_DISMISSED = 20
MAX_SHORTCUTS = 6
MAX_ZONES = 4
MAX_ITEMS = 8
MAX_STATS = 3


class BoardError(Exception):
    """A refused change; the message is safe to show the person or return to the agent."""


def board_path() -> Path:
    return get_hermes_home() / BOARD_FILE


@contextlib.contextmanager
def _locked(home: Path):
    """Serialize read-modify-write across the dashboard and gateway processes."""
    fd = os.open(home / ".personal_board.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ── validation ───────────────────────────────────────────────────────────────────────────────────

def _text(value: Any, limit: int, *, required: str | None = None) -> str:
    text = " ".join(str(value).split()) if isinstance(value, (str, int, float)) else ""
    if required and not text:
        raise BoardError(required)
    return text[:limit]


def _url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    return value.strip()[:500] if parsed.scheme in ("http", "https") and parsed.netloc else None


def _zone(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        ZoneInfo(value)
    except (ValueError, KeyError, OSError):
        return False
    return True


def _list_item(raw: Any) -> dict | None:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict) or not _text(raw.get("text"), 120):
        return None
    item = {"text": _text(raw.get("text"), 120)}
    if detail := _text(raw.get("detail"), 80):
        item["detail"] = detail
    if url := _url(raw.get("url")):
        item["url"] = url
    elif prompt := _text(raw.get("prompt"), 200):
        item["prompt"] = prompt
    if isinstance(raw.get("done"), bool):
        item["done"] = raw["done"]
    return item


def _stat(raw: Any) -> dict | None:
    if not isinstance(raw, dict) or not _text(raw.get("value"), 24) or not _text(raw.get("label"), 40):
        return None
    stat = {"value": _text(raw.get("value"), 24), "label": _text(raw.get("label"), 40)}
    if raw.get("trend") in ("up", "down", "flat"):
        stat["trend"] = raw["trend"]
    return stat


SETTINGS: dict[str, Callable[[dict], dict]] = {
    "calendar": lambda raw: {"days": raw.get("days") if raw.get("days") in (1, 7) else 3},
    "shortcuts": lambda raw: {"items": [_text(i, 120) for i in raw["items"] if _text(i, 120)][:MAX_SHORTCUTS]
                              if isinstance(raw.get("items"), list) else None},
    "scheduled": lambda raw: {},
    "recent": lambda raw: {"count": 5 if raw.get("count") == 5 else 3},
    "note": lambda raw: {"text": raw["text"][:4000] if isinstance(raw.get("text"), str) else ""},
    "clock": lambda raw: {"zones": list(dict.fromkeys(z for z in raw.get("zones") or [] if _zone(z)))[:MAX_ZONES]
                          if isinstance(raw.get("zones"), list) else []},
    "list": lambda raw: {"items": [i for i in map(_list_item, raw.get("items") or []) if i][:MAX_ITEMS]
                         if isinstance(raw.get("items"), list) else []},
    "stats": lambda raw: {"stats": [s for s in map(_stat, raw.get("stats") or []) if s][:MAX_STATS]
                          if isinstance(raw.get("stats"), list) else []},
    "text": lambda raw: {"text": str(raw.get("text") or "").strip()[:600]},
}


def _content_error(kind: str, settings: dict) -> str | None:
    if kind == "list" and not settings["items"]:
        return "A list card needs at least one item with text."
    if kind == "stats" and not settings["stats"]:
        return "A stats card needs at least one stat with a value and a label."
    if kind == "text" and not settings["text"]:
        return "A text card needs text."
    return None


def _clean_tile(raw: Any) -> dict | None:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS or not isinstance(raw.get("id"), str):
        return None
    kind = raw["kind"]
    tile = {
        "id": raw["id"][:64],
        "kind": kind,
        "settings": SETTINGS[kind](raw.get("settings") if isinstance(raw.get("settings"), dict) else {}),
        "added_by": "agent" if raw.get("added_by") == "agent" else "user",
    }
    if tile["added_by"] == "agent":
        for key, limit in (("title", 40), ("reason", 160), ("source", 60)):
            if value := _text(raw.get(key), limit):
                tile[key] = value
        if isinstance(raw.get("updated_at"), (int, float)):
            tile["updated_at"] = float(raw["updated_at"])
    elif kind in CONTENT_KINDS:
        return None  # content cards only ever come from the agent
    return tile


def _clean_board(tiles: Any) -> list[dict]:
    out: list[dict] = []
    for tile in map(_clean_tile, tiles if isinstance(tiles, list) else []):
        if not tile or any(t["id"] == tile["id"] for t in out):
            continue
        if tile["kind"] in SINGLE and any(t["kind"] == tile["kind"] for t in out):
            continue
        out.append(tile)
    return out[:MAX_TILES]


def default_tiles() -> list[dict]:
    return [_clean_tile({"id": kind, "kind": kind}) for kind in ("shortcuts", "calendar", "scheduled")]


# ── storage ──────────────────────────────────────────────────────────────────────────────────────

def _read(home: Path) -> dict:
    try:
        data = json.loads((home / BOARD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        return {"exists": False, "rev": 0, "tiles": default_tiles(), "dismissed": []}
    dismissed = [d for d in data.get("dismissed") or [] if isinstance(d, dict) and d.get("kind") in KINDS]
    return {"exists": True, "rev": int(data.get("rev") or 0), "tiles": _clean_board(data.get("tiles")),
            "dismissed": dismissed[-MAX_DISMISSED:]}


def load() -> dict:
    return _read(get_hermes_home())


def _mutate(change: Callable[[dict], Any]) -> tuple[dict, Any]:
    home = get_hermes_home()
    with _locked(home):
        board = _read(home)
        result = change(board)
        board["tiles"] = _clean_board(board["tiles"])
        board["rev"] += 1
        atomic_write_text(home / BOARD_FILE, json.dumps(
            {"rev": board["rev"], "tiles": board["tiles"], "dismissed": board["dismissed"]}, indent=2) + "\n")
        board["exists"] = True
        return board, result


def _new_id(kind: str) -> str:
    return f"{kind}-{secrets.token_hex(4)}"


def _find(board: dict, tile_id: str) -> dict:
    tile = next((t for t in board["tiles"] if t["id"] == tile_id), None)
    if tile is None:
        raise BoardError(f"No tile {tile_id!r} on the home.")
    return tile


def _check_room(board: dict, kind: str) -> None:
    if len(board["tiles"]) >= MAX_TILES:
        raise BoardError("The home is full. Remove a tile first.")
    if kind in SINGLE and any(t["kind"] == kind for t in board["tiles"]):
        raise BoardError(f"There is already a {kind} tile on the home.")


# ── the person's changes ─────────────────────────────────────────────────────────────────────────

def import_tiles(tiles: Any) -> dict:
    """One-time adoption of a board kept in browser storage by an older home; never overwrites."""
    def change(board):
        if board["exists"]:
            return
        board["tiles"] = [{**t, "added_by": "user"} for t in _clean_board(tiles) if t["kind"] in LIVE_KINDS]
    return _mutate(change)[0]


def user_add(kind: str) -> dict:
    if kind not in LIVE_KINDS:
        raise BoardError(f"Unknown tile {kind!r}.")
    def change(board):
        _check_room(board, kind)
        board["tiles"].append({"id": _new_id(kind), "kind": kind, "settings": SETTINGS[kind]({}), "added_by": "user"})
    return _mutate(change)[0]


def user_update(tile_id: str, settings: dict) -> dict:
    def change(board):
        tile = _find(board, tile_id)
        if tile["kind"] in CONTENT_KINDS:
            # The person can tick list items off; the content itself stays the agent's.
            if tile["kind"] == "list" and isinstance(settings.get("done"), dict):
                for index, item in enumerate(tile["settings"]["items"]):
                    if isinstance(settings["done"].get(str(index)), bool):
                        item["done"] = settings["done"][str(index)]
            return
        tile["settings"] = SETTINGS[tile["kind"]]({**tile["settings"], **(settings or {})})
    return _mutate(change)[0]


def user_remove(tile_id: str) -> dict:
    def change(board):
        tile = _find(board, tile_id)
        board["tiles"].remove(tile)
        if tile["added_by"] == "agent":
            board["dismissed"] = [*board["dismissed"], {
                "kind": tile["kind"], "title": tile.get("title", ""), "at": time.time()}][-MAX_DISMISSED:]
    return _mutate(change)[0]


def user_move(tile_id: str, delta: int) -> dict:
    def change(board):
        tiles = board["tiles"]
        index = tiles.index(_find(board, tile_id))
        target = index + (1 if delta > 0 else -1)
        if 0 <= target < len(tiles):
            tiles[index], tiles[target] = tiles[target], tiles[index]
    return _mutate(change)[0]


# ── the agent's changes ──────────────────────────────────────────────────────────────────────────

def _calendar_connected() -> bool:
    from hermes_cli import personal_calendar

    try:
        token = json.loads(personal_calendar.token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    raw = token.get("scopes") or token.get("scope") or []
    scopes = raw.split() if isinstance(raw, str) else raw
    return bool(token.get("refresh_token")) and bool(personal_calendar.CALENDAR_SCOPES.intersection(scopes))


def _capability_error(kind: str) -> str | None:
    """Live cards only for what this profile actually has."""
    if kind == "calendar" and not _calendar_connected():
        return ("Google Calendar isn't connected for this profile, so a calendar card would be empty. "
                "The person can sign in with Google from the home's calendar setup or through Google Workspace setup.")
    return None


def _same_title(a: str, b: str) -> bool:
    return re.sub(r"\W+", "", a.lower()) == re.sub(r"\W+", "", b.lower())


def agent_add(kind: str, *, title: str = "", reason: str = "", source: str = "", settings: dict | None = None,
              user_requested: bool = False) -> tuple[dict, dict]:
    if kind not in AGENT_KINDS:
        raise BoardError(f"Cards the agent can add: {', '.join(AGENT_KINDS)}.")
    if error := _capability_error(kind):
        raise BoardError(error)
    clean = SETTINGS[kind](settings or {})
    if kind in CONTENT_KINDS:
        if error := _content_error(kind, clean):
            raise BoardError(error)
        title = _text(title, 40, required="Content cards need a short title.")
        source = _text(source, 60, required="Content cards must name where the data came from (source).")
    if kind == "clock" and not clean["zones"]:
        raise BoardError("A clock card needs at least one IANA time zone, like 'Europe/London'.")
    reason = _text(reason, 160, required="Say briefly why this card helps the person (reason).")
    title = _text(title, 40)

    def change(board):
        _check_room(board, kind)
        if sum(t["added_by"] == "agent" for t in board["tiles"]) >= MAX_AGENT_TILES:
            raise BoardError(f"You already have {MAX_AGENT_TILES} cards on the home. Update or remove one first.")
        if not user_requested and any(d["kind"] == kind and _same_title(d.get("title", ""), title)
                                      for d in board["dismissed"]):
            raise BoardError("The person removed a card like this before. Only add it again if they ask "
                             "(then pass user_requested=true).")
        tile = {"id": _new_id(kind), "kind": kind, "settings": clean, "added_by": "agent",
                "reason": reason, "updated_at": time.time()}
        if title:
            tile["title"] = title
        if source:
            tile["source"] = source
        board["tiles"].insert(0, tile)
        return tile
    return _mutate(change)


def agent_update(tile_id: str, *, title: str | None = None, reason: str | None = None, source: str | None = None,
                 settings: dict | None = None) -> tuple[dict, dict]:
    def change(board):
        tile = _find(board, tile_id)
        if tile["added_by"] != "agent":
            raise BoardError("That tile belongs to the person; only they can change it.")
        if settings is not None:
            merged = SETTINGS[tile["kind"]]({**tile["settings"], **settings})
            if tile["kind"] in CONTENT_KINDS and (error := _content_error(tile["kind"], merged)):
                raise BoardError(error)
            tile["settings"] = merged
        for key, value, limit in (("title", title, 40), ("reason", reason, 160), ("source", source, 60)):
            if value is not None and (text := _text(value, limit)):
                tile[key] = text
        tile["updated_at"] = time.time()
        return tile
    return _mutate(change)


def agent_remove(tile_id: str) -> dict:
    def change(board):
        tile = _find(board, tile_id)
        if tile["added_by"] != "agent":
            raise BoardError("That tile belongs to the person; only they can remove it.")
        board["tiles"].remove(tile)
    return _mutate(change)[0]


def summary(board: dict) -> dict:
    """What the agent sees: every tile (so it knows what's already there), whose it is, and recent removals."""
    def describe(tile):
        entry = {"id": tile["id"], "kind": tile["kind"], "added_by": tile["added_by"]}
        if tile["added_by"] == "agent":
            entry.update({k: tile[k] for k in ("title", "reason", "source") if k in tile})
            entry["settings"] = tile["settings"]
        return entry
    return {
        "tiles": [describe(t) for t in board["tiles"]],
        "removed_by_person": [{"kind": d["kind"], "title": d.get("title", "")} for d in board["dismissed"]],
        "calendar_connected": _calendar_connected(),
    }
