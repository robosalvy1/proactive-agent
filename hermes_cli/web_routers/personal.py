"""The personal web surface: onboarding identity, home preferences, the tile board, and the calendar tile."""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes_cli.web_routers._common import destructive_profile, scoped_to_thread

router = APIRouter()


# "auto", a named swatch, or any #rrggbb; mirrors web/src/personal/lib/avatar.ts.
AVATAR_COLOR = re.compile(r"^(auto|oat|peach|sage|lilac|sky|rose|#[0-9a-fA-F]{6})$")
PREFERENCES_FILE = "personal_home.json"


class Preferences(BaseModel):
    avatar_color: str


def _read_preferences(home) -> dict:
    try:
        data = json.loads((home / PREFERENCES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class CalendarClient(BaseModel):
    client_json: str


class CalendarStart(BaseModel):
    origin: str | None = None


class CalendarFinish(BaseModel):
    code_or_url: str


@router.get("/api/personal/identity")
async def personal_identity(profile: str | None = None):
    """Read-only; a missing user name stays null so the UI can ask instead of guessing."""

    def read():
        from hermes_cli.cli_identity import get_agent_name, read_agent_name
        from hermes_constants import get_hermes_home

        home = get_hermes_home()
        color = _read_preferences(home).get("avatar_color")
        return {
            "agent_name": get_agent_name(),
            "user_name": read_agent_name(home / "USER_NAME.txt"),
            "avatar_color": color if isinstance(color, str) and AVATAR_COLOR.match(color) else "auto",
        }

    return await scoped_to_thread(profile, read)


@router.put("/api/personal/preferences")
async def personal_preferences(body: Preferences, profile: str | None = None):
    """Presentation choices the person makes for their home; stored per profile so every device agrees."""
    if not AVATAR_COLOR.match(body.avatar_color):
        raise HTTPException(status_code=400, detail="Unknown avatar color.")

    def write():
        from hermes_constants import get_hermes_home
        from utils import atomic_write_text

        home = get_hermes_home()
        prefs = {**_read_preferences(home), "avatar_color": body.avatar_color.lower()}
        atomic_write_text(home / PREFERENCES_FILE, json.dumps(prefs, indent=2) + "\n")
        return prefs

    return await scoped_to_thread(destructive_profile(profile, "PUT /api/personal/preferences"), write)


async def _calendar(profile: str | None, route: str, action):
    """Credential writes name their profile explicitly; tile errors surface as 400 with a readable detail."""
    from hermes_cli.personal_calendar import CalendarError

    def run():
        try:
            return action()
        except CalendarError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await scoped_to_thread(destructive_profile(profile, route), run)


@router.get("/api/personal/calendar")
async def calendar_status(profile: str | None = None, days: int = 3, limit: int = 8):
    from hermes_cli import personal_calendar

    return await scoped_to_thread(profile, lambda: personal_calendar.status(days, limit))


@router.post("/api/personal/calendar/client")
async def calendar_client(body: CalendarClient, profile: str | None = None):
    from hermes_cli import personal_calendar

    await _calendar(profile, "POST /api/personal/calendar/client", lambda: personal_calendar.store_client(body.client_json))
    return {"ok": True}


@router.post("/api/personal/calendar/start")
async def calendar_start(body: CalendarStart, profile: str | None = None):
    from hermes_cli import personal_calendar

    return await _calendar(profile, "POST /api/personal/calendar/start", lambda: personal_calendar.start(body.origin))


@router.post("/api/personal/calendar/finish")
async def calendar_finish(body: CalendarFinish, profile: str | None = None):
    from hermes_cli import personal_calendar

    await _calendar(profile, "POST /api/personal/calendar/finish", lambda: personal_calendar.finish(body.code_or_url))
    return {"ok": True}


@router.delete("/api/personal/calendar")
async def calendar_disconnect(profile: str | None = None):
    from hermes_cli import personal_calendar

    await _calendar(profile, "DELETE /api/personal/calendar", personal_calendar.disconnect)
    return {"ok": True}


class BoardImport(BaseModel):
    tiles: list


class BoardAdd(BaseModel):
    kind: str


class BoardUpdate(BaseModel):
    settings: dict


class BoardMove(BaseModel):
    delta: int


def _public_board(board: dict) -> dict:
    return {"rev": board["rev"], "exists": board["exists"], "tiles": board["tiles"]}


async def _board(profile: str | None, route: str | None, action):
    """Reads use the request's profile; changes name it explicitly. Refusals surface as 400s."""
    from hermes_cli.personal_board import BoardError

    def run():
        try:
            return _public_board(action())
        except BoardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await scoped_to_thread(destructive_profile(profile, route) if route else profile, run)


@router.get("/api/personal/board")
async def board_read(profile: str | None = None):
    from hermes_cli import personal_board

    return await _board(profile, None, personal_board.load)


@router.post("/api/personal/board/import")
async def board_import(body: BoardImport, profile: str | None = None):
    from hermes_cli import personal_board

    return await _board(profile, "POST /api/personal/board/import", lambda: personal_board.import_tiles(body.tiles))


@router.post("/api/personal/board/tiles")
async def board_add(body: BoardAdd, profile: str | None = None):
    from hermes_cli import personal_board

    return await _board(profile, "POST /api/personal/board/tiles", lambda: personal_board.user_add(body.kind))


@router.patch("/api/personal/board/tiles/{tile_id}")
async def board_update(tile_id: str, body: BoardUpdate, profile: str | None = None):
    from hermes_cli import personal_board

    return await _board(profile, "PATCH /api/personal/board/tiles",
                        lambda: personal_board.user_update(tile_id, body.settings))


@router.delete("/api/personal/board/tiles/{tile_id}")
async def board_remove(tile_id: str, profile: str | None = None):
    from hermes_cli import personal_board

    return await _board(profile, "DELETE /api/personal/board/tiles", lambda: personal_board.user_remove(tile_id))


@router.post("/api/personal/board/tiles/{tile_id}/move")
async def board_move(tile_id: str, body: BoardMove, profile: str | None = None):
    from hermes_cli import personal_board

    return await _board(profile, "POST /api/personal/board/tiles/move",
                        lambda: personal_board.user_move(tile_id, body.delta))
