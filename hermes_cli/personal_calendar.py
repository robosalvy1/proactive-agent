"""Google Calendar for the personal home, connected through Hermes's Google Workspace sign-in.

The tile does not keep a grant of its own. It drives the same OAuth flow as the google-workspace
skill's ``setup.py`` (same client file, scopes, pending-session file and ``google_token.json``), so
connecting from the home connects Hermes to Google once, and a grant made in chat lights the tile up.
The person still configures the tile; the agent never adds or changes it. Implemented with httpx so
the home works without the optional Google client libraries installed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from hermes_constants import get_hermes_home

# Mirrors skills/productivity/google-workspace/scripts/setup.py SCOPES (a test keeps them in step).
WORKSPACE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]
CALENDAR_SCOPES = {"https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/calendar.readonly"}
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
EVENTS_URI = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
# setup.py's redirect. Google rejects non-loopback http redirects for Desktop clients, so remote
# dashboards paste the browser's final URL, exactly like the skill's manual flow.
MANUAL_REDIRECT = "http://localhost:1"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
CALLBACK_PATH = "/home"
# Marks a sign-in the home started, so /home only consumes its own callbacks.
STATE_PREFIX = "cal_"
PENDING_TTL_S = 15 * 60
MAX_DAYS = 14


class CalendarError(Exception):
    """A user-actionable failure; the message is shown in the tile."""


def _home() -> Path:
    return get_hermes_home()


def client_path() -> Path:
    return _home() / "google_client_secret.json"


def token_path() -> Path:
    return _home() / "google_token.json"


def pending_path() -> Path:
    return _home() / "google_oauth_pending.json"


def _write_private(path: Path, payload: dict) -> None:
    from utils import atomic_write_text

    atomic_write_text(path, json.dumps(payload, indent=2), mode=0o600)


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _client() -> dict:
    data = _read_json(client_path()) or {}
    client = data.get("installed") or data.get("web")
    if not isinstance(client, dict) or not client.get("client_id"):
        raise CalendarError("Add a Google OAuth client first.")
    return client


def store_client(raw: str) -> None:
    """Validate and save a downloaded client_secret JSON. Never replaces an existing client,
    because Hermes's Google token is bound to it."""
    if client_path().exists():
        raise CalendarError("A Google OAuth client is already configured for this profile.")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise CalendarError("That isn't valid JSON. Paste the downloaded client file as-is.") from exc
    client = data.get("installed") or data.get("web") if isinstance(data, dict) else None
    if not isinstance(client, dict) or not client.get("client_id") or not client.get("client_secret"):
        raise CalendarError("That isn't a Google OAuth client file (expected a Desktop app client).")
    _write_private(client_path(), data)


def _redirect_for(origin: str | None) -> tuple[str, bool]:
    """(redirect_uri, manual). Only a loopback http origin can receive Google's redirect directly."""
    parsed = urlparse(origin or "")
    if parsed.scheme == "http" and (parsed.hostname or "") in LOOPBACK_HOSTS and not parsed.path.strip("/"):
        return f"{parsed.scheme}://{parsed.netloc}{CALLBACK_PATH}", False
    return MANUAL_REDIRECT, True


def start(origin: str | None) -> dict:
    client = _client()
    redirect_uri, manual = _redirect_for(origin)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = STATE_PREFIX + secrets.token_urlsafe(24)
    # setup.py's pending format, so `setup.py --auth-code` can finish a sign-in started here too.
    _write_private(pending_path(), {
        "state": state, "code_verifier": verifier, "redirect_uri": redirect_uri, "created_at": time.time(),
    })
    query = urlencode({
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(WORKSPACE_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })
    return {"auth_url": f"{client.get('auth_uri') or AUTH_URI}?{query}", "manual": manual}


def _code_from(code_or_url: str) -> tuple[str, str | None]:
    text = code_or_url.strip()
    if not text.startswith("http"):
        return text, None
    params = parse_qs(urlparse(text).query)
    if params.get("error"):
        raise CalendarError("Google didn't grant access.")
    if not params.get("code"):
        raise CalendarError("That URL has no authorization code. Copy the full address after consenting.")
    return params["code"][0], (params.get("state") or [None])[0]


def _post_token(client: dict, data: dict) -> dict:
    response = httpx.post(client.get("token_uri") or TOKEN_URI, data={
        "client_id": client["client_id"], "client_secret": client.get("client_secret", ""), **data,
    }, timeout=20)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or "access_token" not in body:
        raise CalendarError(f"Google refused the request ({body.get('error') or response.status_code}).")
    return body


def _expiry(expires_in: Any) -> str:
    """google-auth's authorized_user expiry: naive UTC ISO with a Z, which from_authorized_user_info parses."""
    moment = datetime.now(UTC) + timedelta(seconds=float(expires_in or 3600))
    return moment.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")


def finish(code_or_url: str) -> None:
    pending = _read_json(pending_path())
    if not pending or not pending.get("code_verifier"):
        raise CalendarError("That sign-in expired. Start connecting again.")
    if time.time() - float(pending.get("created_at", time.time())) > PENDING_TTL_S:
        raise CalendarError("That sign-in expired. Start connecting again.")
    code, state = _code_from(code_or_url)
    if state is not None and state != pending.get("state"):
        raise CalendarError("That sign-in doesn't match this request. Start connecting again.")
    client = _client()
    body = _post_token(client, {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": pending.get("redirect_uri", MANUAL_REDIRECT), "code_verifier": pending["code_verifier"],
    })
    if not body.get("refresh_token"):
        raise CalendarError("Google didn't return a refresh token. Remove Hermes's access in your Google account and retry.")
    granted = str(body.get("scope") or "").split() or list(WORKSPACE_SCOPES)
    # The authorized_user shape the skill (google-auth) and the gws bridge read.
    _write_private(token_path(), {
        "type": "authorized_user",
        "token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "token_uri": client.get("token_uri") or TOKEN_URI,
        "client_id": client["client_id"],
        "client_secret": client.get("client_secret", ""),
        "scopes": granted,
        "expiry": _expiry(body.get("expires_in")),
    })
    pending_path().unlink(missing_ok=True)


def disconnect() -> None:
    """Sign Hermes out of Google: revoke the grant, then forget the token (like `setup.py --revoke`)."""
    token = _read_json(token_path()) or {}
    secret = token.get("refresh_token") or token.get("token")
    if secret:
        try:
            httpx.post(REVOKE_URI, data={"token": secret}, timeout=10)
        except httpx.HTTPError:
            pass  # Forgetting locally still disconnects; Google expires an unused grant.
    token_path().unlink(missing_ok=True)
    pending_path().unlink(missing_ok=True)


def _scopes(token: dict) -> list[str]:
    raw = token.get("scopes") or token.get("scope") or []
    return raw.split() if isinstance(raw, str) else list(raw)


def _expired(token: dict) -> bool:
    try:
        expiry = datetime.strptime(str(token["expiry"]).rstrip("Z").split(".")[0], "%Y-%m-%dT%H:%M:%S")
    except (KeyError, ValueError):
        return True
    return expiry.replace(tzinfo=UTC) <= datetime.now(UTC) + timedelta(seconds=60)


def _access_token(token: dict) -> str:
    """A live access token, refreshing and writing back the shared token like the skill does."""
    if token.get("token") and not _expired(token):
        return token["token"]
    client = {"client_id": token.get("client_id"), "client_secret": token.get("client_secret"),
              "token_uri": token.get("token_uri")}
    if not client["client_id"]:
        client = _client()
    body = _post_token(client, {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
    token.update(token=body["access_token"], expiry=_expiry(body.get("expires_in")))
    _write_private(token_path(), token)
    return token["token"]


def _event(item: dict) -> dict:
    start, end = item.get("start") or {}, item.get("end") or {}
    meet = item.get("hangoutLink") or next(
        (e.get("uri") for e in (item.get("conferenceData") or {}).get("entryPoints", []) if e.get("entryPointType") == "video"),
        None,
    )
    return {
        "id": item.get("id"),
        "title": item.get("summary") or "(No title)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start and "dateTime" not in start,
        "location": item.get("location"),
        "meeting_url": meet,
        "url": item.get("htmlLink"),
    }


def status(days: int = 3, limit: int = 8) -> dict:
    """What the tile should show right now. Never raises for ordinary not-connected states."""
    try:
        return _status(days, limit)
    except httpx.HTTPError:
        return {"state": "error", "error": "Couldn't reach Google. Check your connection and try again."}


def _status(days: int, limit: int) -> dict:
    token = _read_json(token_path())
    if not token or not token.get("refresh_token"):
        return {"state": "needs_auth" if client_path().exists() else "needs_client"}
    if not CALENDAR_SCOPES.intersection(_scopes(token)):
        return {"state": "needs_scope"}
    try:
        access_token = _access_token(token)
    except CalendarError as exc:
        return {"state": "error", "error": str(exc)}
    now = datetime.now(UTC)
    days = max(1, min(int(days), MAX_DAYS))
    response = httpx.get(EVENTS_URI, headers={"Authorization": f"Bearer {access_token}"}, params={
        "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": str(max(1, min(int(limit), 25))),
    }, timeout=20)
    if response.status_code == 403:
        return {"state": "error",
                "error": "Calendar access was refused. Make sure the Google Calendar API is enabled for your OAuth project."}
    if response.status_code != 200:
        return {"state": "error", "error": f"Google Calendar is unavailable ({response.status_code})."}
    items: list[dict[str, Any]] = response.json().get("items", [])
    return {"state": "connected", "events": [_event(i) for i in items if i.get("status") != "cancelled"]}
