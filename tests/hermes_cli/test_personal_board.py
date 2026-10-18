"""The shared home board: the person owns their tiles; the agent adds catalog cards from what it has."""
import json

import pytest
from starlette.testclient import TestClient

from hermes_cli import personal_board, personal_calendar, web_server
from hermes_constants import get_hermes_home
from tools.home_cards_tool import home_cards_tool


@pytest.fixture(autouse=True)
def clean_home():
    for name in (personal_board.BOARD_FILE, "google_token.json"):
        (get_hermes_home() / name).unlink(missing_ok=True)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    c = TestClient(web_server.app)
    c.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return c


def tool(**kwargs):
    return json.loads(home_cards_tool(**kwargs))


def connect_calendar():
    personal_calendar.token_path().write_text(json.dumps(
        {"refresh_token": "rt", "scopes": ["https://www.googleapis.com/auth/calendar"]}))


def test_board_routes_require_the_dashboard_token():
    assert TestClient(web_server.app).get("/api/personal/board").status_code == 401


def test_a_new_profile_starts_with_the_default_board_and_imports_a_browser_board_once(client):
    fresh = client.get("/api/personal/board?profile=default").json()
    assert fresh["exists"] is False and [t["kind"] for t in fresh["tiles"]] == ["shortcuts", "calendar", "scheduled"]
    old = [{"id": "n1", "kind": "note", "settings": {"text": "hi"}},
           {"id": "x", "kind": "list", "settings": {"items": ["sneaky"]}}]  # content kinds are agent-only
    imported = client.post("/api/personal/board/import?profile=default", json={"tiles": old}).json()
    assert [(t["id"], t["added_by"]) for t in imported["tiles"]] == [("n1", "user")]
    again = client.post("/api/personal/board/import?profile=default", json={"tiles": []}).json()
    assert [t["id"] for t in again["tiles"]] == ["n1"]


def test_the_person_adds_configures_moves_and_removes_tiles(client):
    q = "?profile=default"
    board = client.post(f"/api/personal/board/tiles{q}", json={"kind": "clock"}).json()
    clock = board["tiles"][-1]
    board = client.patch(f"/api/personal/board/tiles/{clock['id']}{q}",
                         json={"settings": {"zones": ["Asia/Tokyo", "Not/AZone", "Asia/Tokyo"]}}).json()
    assert board["tiles"][-1]["settings"] == {"zones": ["Asia/Tokyo"]}
    board = client.post(f"/api/personal/board/tiles/{clock['id']}/move{q}", json={"delta": -1}).json()
    assert board["tiles"][-2]["id"] == clock["id"]
    assert client.post(f"/api/personal/board/tiles{q}", json={"kind": "calendar"}).status_code == 400  # one only
    assert client.post(f"/api/personal/board/tiles{q}", json={"kind": "stats"}).status_code == 400  # agent-only
    board = client.delete(f"/api/personal/board/tiles/{clock['id']}{q}").json()
    assert all(t["id"] != clock["id"] for t in board["tiles"])


def test_the_agent_sees_the_board_and_adds_a_calendar_only_when_it_has_one():
    personal_board.user_remove("calendar")
    listed = tool(action="list")
    assert {"id": "shortcuts", "kind": "shortcuts", "added_by": "user"} in listed["tiles"]
    assert listed["calendar_connected"] is False

    refused = tool(action="add", kind="calendar", reason="Your day at a glance")
    assert "isn't connected" in refused["error"]

    connect_calendar()
    added = tool(action="add", kind="calendar", reason="Your day at a glance", settings={"days": 1})
    assert added["success"] and added["card"]["settings"] == {"days": 1}
    board = personal_board.load()
    assert board["tiles"][0]["kind"] == "calendar" and board["tiles"][0]["added_by"] == "agent"
    assert "already" in tool(action="add", kind="calendar", reason="again")["error"]


def test_content_cards_need_a_source_and_cannot_carry_design():
    assert "source" in tool(action="add", kind="list", title="Open PRs", reason="Review queue",
                            settings={"items": [{"text": "Fix login"}]})["error"]
    card = tool(action="add", kind="list", title="Open PRs", reason="Your review queue", source="GitHub", settings={
        "items": [{"text": "Fix login", "detail": "#42", "url": "https://github.com/x/y/pull/42", "color": "red"},
                  {"text": "Bad link", "url": "javascript:alert(1)", "prompt": "Summarize the bad link PR"},
                  {"html": "<b>no text</b>"}],
        "style": {"background": "red"}})["card"]
    assert card["settings"] == {"items": [
        {"text": "Fix login", "detail": "#42", "url": "https://github.com/x/y/pull/42"},
        {"text": "Bad link", "prompt": "Summarize the bad link PR"}]}
    stats = tool(action="add", kind="stats", title="Inbox", reason="Unread at a glance", source="Gmail",
                 settings={"stats": [{"value": 12, "label": "Unread", "trend": "up"}, {"value": "", "label": "x"}]})
    assert stats["card"]["settings"] == {"stats": [{"value": "12", "label": "Unread", "trend": "up"}]}
    assert "needs at least one" in tool(action="add", kind="stats", title="Empty", reason="r", source="s",
                                        settings={"stats": []})["error"]


def test_the_agent_can_only_change_its_own_cards():
    assert "belongs to the person" in tool(action="update", card_id="shortcuts", settings={"items": ["x"]})["error"]
    assert "belongs to the person" in tool(action="remove", card_id="scheduled")["error"]
    card = tool(action="add", kind="text", title="Today", reason="Daily focus", source="your notes",
                settings={"text": "Ship the home cards"})["card"]
    updated = tool(action="update", card_id=card["id"], settings={"text": "Ship it"})["card"]
    assert updated["settings"] == {"text": "Ship it"} and updated["updated_at"] >= card["updated_at"]
    assert tool(action="remove", card_id=card["id"])["success"]


def test_a_card_the_person_removed_is_not_re_added_unprompted():
    card = tool(action="add", kind="text", title="Focus", reason="Daily focus", source="notes",
                settings={"text": "Write"})["card"]
    personal_board.user_remove(card["id"])
    assert tool(action="list")["removed_by_person"] == [{"kind": "text", "title": "Focus"}]
    again = tool(action="add", kind="text", title="focus!", reason="Daily focus", source="notes", settings={"text": "Write"})
    assert "removed a card like this" in again["error"]
    assert tool(action="add", kind="text", title="Focus", reason="You asked", source="notes",
                settings={"text": "Write"}, user_requested=True)["success"]


def test_the_person_can_tick_items_but_not_rewrite_agent_content(client):
    card = tool(action="add", kind="list", title="Errands", reason="This week", source="your notes",
                settings={"items": ["Groceries", "Post office"]})["card"]
    board = client.patch(f"/api/personal/board/tiles/{card['id']}?profile=default",
                         json={"settings": {"done": {"1": True}, "items": [{"text": "hijack"}]}}).json()
    items = next(t for t in board["tiles"] if t["id"] == card["id"])["settings"]["items"]
    assert items == [{"text": "Groceries"}, {"text": "Post office", "done": True}]


def test_agent_cards_are_capped_so_the_home_stays_the_persons():
    for i in range(personal_board.MAX_AGENT_TILES):
        assert tool(action="add", kind="clock", reason="Team time", settings={"zones": ["Europe/London"]})["success"]
    assert "already have" in tool(action="add", kind="clock", reason="One more", settings={"zones": ["UTC"]})["error"]
    assert "time zone" in tool(action="add", kind="clock", reason="r", settings={"zones": ["Mars/Base"]})["error"]


def test_a_tampered_board_file_is_sanitized_on_read():
    personal_board.board_path().write_text(json.dumps({"rev": 3, "tiles": [
        {"id": "a", "kind": "calendar", "settings": {"days": 99}},
        {"id": "b", "kind": "calendar"},
        {"id": "c", "kind": "iframe", "settings": {"src": "https://evil"}},
        {"id": "d", "kind": "text", "added_by": "user", "settings": {"text": "forged"}},
    ]}))
    board = personal_board.load()
    assert board["rev"] == 3 and board["tiles"] == [
        {"id": "a", "kind": "calendar", "settings": {"days": 3}, "added_by": "user"}]


def test_board_and_token_files_saved_with_a_bom_still_load():
    """Windows editors may prefix a UTF-8 BOM; the board and the calendar connection survive it."""
    personal_board.board_path().write_text(json.dumps({"rev": 2, "tiles": [{"id": "n", "kind": "note"}]}), encoding="utf-8-sig")
    assert [(t["id"], t["kind"]) for t in personal_board.load()["tiles"]] == [("n", "note")]
    connect_calendar()
    token = personal_calendar.token_path()
    token.write_text(token.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert personal_board._calendar_connected()
