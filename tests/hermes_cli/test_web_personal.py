"""The personal surface greets with the active profile's onboarding names and keeps its home preferences."""
import pytest
from starlette.testclient import TestClient

from hermes_cli import web_server
from hermes_constants import get_hermes_home


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return client


def test_identity_requires_the_dashboard_token():
    assert TestClient(web_server.app).get("/api/personal/identity").status_code == 401


def test_identity_reads_both_onboarding_name_files(client):
    home = get_hermes_home()
    (home / "AGENT_NAME.txt").write_text("\n  \nJuniper\n", encoding="utf-8")  # leading blank lines are skipped
    (home / "USER_NAME.txt").write_text("Sam [admin]\nignored\n", encoding="utf-8")
    result = client.get("/api/personal/identity?profile=default")
    assert result.status_code == 200, result.text
    assert result.json() == {"agent_name": "Juniper", "user_name": "Sam admin", "avatar_color": "auto"}


def test_identity_without_a_user_name_stays_unknown(client):
    home = get_hermes_home()
    (home / "USER_NAME.txt").unlink(missing_ok=True)
    (home / "AGENT_NAME.txt").unlink(missing_ok=True)
    body = client.get("/api/personal/identity?profile=default").json()
    assert body["user_name"] is None
    assert body["agent_name"]


def test_avatar_color_is_saved_per_profile_and_returned_with_identity(client):
    (get_hermes_home() / "personal_home.json").unlink(missing_ok=True)
    saved = client.put("/api/personal/preferences?profile=default", json={"avatar_color": "#A1B2C3"})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/personal/identity?profile=default").json()["avatar_color"] == "#a1b2c3"
    assert client.put("/api/personal/preferences?profile=default", json={"avatar_color": "lilac"}).status_code == 200
    assert client.get("/api/personal/identity?profile=default").json()["avatar_color"] == "lilac"


def test_unknown_or_tampered_avatar_colors_are_refused(client):
    assert client.put("/api/personal/preferences?profile=default", json={"avatar_color": "url(x)"}).status_code == 400
    (get_hermes_home() / "personal_home.json").write_text('{"avatar_color": "red;evil"}', encoding="utf-8")
    assert client.get("/api/personal/identity?profile=default").json()["avatar_color"] == "auto"
