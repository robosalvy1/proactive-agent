"""The calendar tile signs in through Hermes's Google Workspace OAuth and reads the shared token."""
import ast
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.testclient import TestClient

from hermes_cli import personal_calendar, web_server
from hermes_constants import get_hermes_home

CLIENT = json.dumps({"installed": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "shh"}})
SETUP_PY = Path(__file__).resolve().parents[2] / "skills/productivity/google-workspace/scripts/setup.py"


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    for name in ("google_client_secret.json", "google_token.json", "google_oauth_pending.json"):
        (get_hermes_home() / name).unlink(missing_ok=True)
    c = TestClient(web_server.app)
    c.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return c


@pytest.fixture
def google(monkeypatch):
    calls = {"post": [], "get": [], "revoke": []}

    def post(url, data=None, timeout=None):
        if url == personal_calendar.REVOKE_URI:
            calls["revoke"].append(data["token"])
            return FakeResponse(200, {})
        calls["post"].append(data)
        if data["grant_type"] == "authorization_code":
            return FakeResponse(200, {"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600,
                                      "scope": " ".join(personal_calendar.WORKSPACE_SCOPES)})
        return FakeResponse(200, {"access_token": f"refreshed-{data['refresh_token']}", "expires_in": 3600})

    def get(url, headers=None, params=None, timeout=None):
        calls["get"].append(headers["Authorization"])
        return FakeResponse(200, {"items": [
            {"id": "a", "summary": "Standup", "start": {"dateTime": "2026-10-17T09:00:00-04:00"},
             "end": {"dateTime": "2026-10-17T09:15:00-04:00"}, "hangoutLink": "https://meet.google.com/x"},
            {"id": "b", "summary": "Mom's birthday", "start": {"date": "2026-10-18"}, "end": {"date": "2026-10-19"}},
            {"id": "c", "summary": "Gone", "status": "cancelled", "start": {"date": "2026-10-18"}},
        ]})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    return calls


def connect(client, origin="http://127.0.0.1:9119"):
    assert client.post("/api/personal/calendar/client?profile=default", json={"client_json": CLIENT}).status_code == 200
    started = client.post("/api/personal/calendar/start?profile=default", json={"origin": origin}).json()
    query = parse_qs(urlparse(started["auth_url"]).query)
    return started, query


def finish(client, query):
    callback = f"http://127.0.0.1:9119/home?code=c0de&state={query['state'][0]}"
    return client.post("/api/personal/calendar/finish?profile=default", json={"code_or_url": callback})


def test_scopes_match_the_google_workspace_skill():
    tree = ast.parse(SETUP_PY.read_text(encoding="utf-8"))
    skill = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "SCOPES")
    assert personal_calendar.WORKSPACE_SCOPES == skill


def test_calendar_requires_the_dashboard_token():
    assert TestClient(web_server.app).get("/api/personal/calendar").status_code == 401


def test_sign_in_writes_the_shared_workspace_token(client, google):
    started, query = connect(client)
    assert started["manual"] is False
    assert query["redirect_uri"] == ["http://127.0.0.1:9119/home"]
    assert query["scope"] == [" ".join(personal_calendar.WORKSPACE_SCOPES)]
    assert query["code_challenge_method"] == ["S256"]
    pending = json.loads(personal_calendar.pending_path().read_text())
    assert personal_calendar.pending_path().name == "google_oauth_pending.json"
    assert {"state", "code_verifier", "redirect_uri"} <= pending.keys()  # what setup.py --auth-code reads
    assert client.get("/api/personal/calendar?profile=default").json() == {"state": "needs_auth"}

    assert finish(client, query).status_code == 200
    assert google["post"][0]["code_verifier"] == pending["code_verifier"]
    token = json.loads((get_hermes_home() / "google_token.json").read_text())
    assert token["type"] == "authorized_user" and token["refresh_token"] == "rt1" and token["token"] == "at1"
    assert token["client_id"] == "cid.apps.googleusercontent.com" and token["scopes"] == personal_calendar.WORKSPACE_SCOPES
    assert token["expiry"].endswith("Z")
    assert not personal_calendar.pending_path().exists()

    result = client.get("/api/personal/calendar?profile=default&days=3").json()
    assert result["state"] == "connected"
    assert [e["title"] for e in result["events"]] == ["Standup", "Mom's birthday"]
    assert result["events"][0]["meeting_url"] == "https://meet.google.com/x"
    assert result["events"][1]["all_day"] is True
    assert google["get"] == ["Bearer at1"]


def test_remote_origins_fall_back_to_pasting_the_redirect(client, google):
    started, query = connect(client, origin="https://agent.example.com")
    assert started["manual"] is True
    assert query["redirect_uri"] == [personal_calendar.MANUAL_REDIRECT]


def test_mismatched_or_expired_sign_in_is_refused(client, google):
    _, query = connect(client)
    bad = client.post("/api/personal/calendar/finish?profile=default",
                      json={"code_or_url": "http://127.0.0.1:9119/home?code=x&state=other"})
    assert bad.status_code == 400 and "doesn't match" in bad.json()["detail"]
    pending = json.loads(personal_calendar.pending_path().read_text())
    pending["created_at"] = time.time() - 3600
    personal_calendar.pending_path().write_text(json.dumps(pending))
    late = finish(client, query)
    assert late.status_code == 400 and "expired" in late.json()["detail"]
    assert google["post"] == []


def test_client_file_is_validated_and_never_replaced(client):
    bad = client.post("/api/personal/calendar/client?profile=default", json={"client_json": '{"nope": 1}'})
    assert bad.status_code == 400
    assert client.get("/api/personal/calendar?profile=default").json() == {"state": "needs_client"}
    assert client.post("/api/personal/calendar/client?profile=default", json={"client_json": CLIENT}).status_code == 200
    again = client.post("/api/personal/calendar/client?profile=default", json={"client_json": CLIENT})
    assert again.status_code == 400


def test_a_grant_made_in_chat_lights_up_the_tile_and_is_refreshed_in_place(client, google):
    connect(client)
    skill_token = {"type": "authorized_user", "token": "stale", "refresh_token": "ws-rt", "client_id": "cid",
                   "client_secret": "shh", "token_uri": personal_calendar.TOKEN_URI, "expiry": "2020-01-01T00:00:00.000000Z",
                   "scopes": ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/gmail.readonly"]}
    personal_calendar.token_path().write_text(json.dumps(skill_token))
    assert client.get("/api/personal/calendar?profile=default").json()["state"] == "connected"
    assert google["get"] == ["Bearer refreshed-ws-rt"]
    refreshed = json.loads(personal_calendar.token_path().read_text())
    assert refreshed["token"] == "refreshed-ws-rt" and refreshed["scopes"] == skill_token["scopes"]
    assert refreshed["refresh_token"] == "ws-rt" and refreshed["expiry"] > "2026"


def test_a_grant_without_calendar_asks_to_sign_in_again(client, google):
    connect(client)
    personal_calendar.token_path().write_text(json.dumps({
        "refresh_token": "ws-rt", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}))
    assert client.get("/api/personal/calendar?profile=default").json() == {"state": "needs_scope"}
    assert google["get"] == []


def test_disconnect_revokes_and_forgets_the_shared_token(client, google):
    _, query = connect(client)
    finish(client, query)
    assert client.delete("/api/personal/calendar?profile=default").status_code == 200
    assert google["revoke"] == ["rt1"]
    assert not personal_calendar.token_path().exists()
    assert client.get("/api/personal/calendar?profile=default").json() == {"state": "needs_auth"}


def test_network_failures_stay_readable(client, google, monkeypatch):
    _, query = connect(client)
    finish(client, query)

    def offline(*_a, **_k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", offline)
    result = client.get("/api/personal/calendar?profile=default").json()
    assert result["state"] == "error" and "reach Google" in result["error"]
