"""Dashboard Home uses existing auth and the ready owner; offline writes reserve ownership."""
import pytest
from starlette.testclient import TestClient

from hermes_cli import web_server
from hermes_state import SessionDB
from hermes_state_home import HomeStore


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return client


def test_dashboard_home_is_authenticated_and_idempotent_offline(client, monkeypatch):
    from hermes_cli import sessions_owner
    monkeypatch.setattr(sessions_owner, "live_owner", lambda: None)
    unauthorized = TestClient(web_server.app).post("/api/home/open")
    assert unauthorized.status_code == 401
    first = client.post("/api/home/open?profile=default")
    assert first.status_code == 200, first.text
    second = client.post("/api/home/open?profile=default")
    assert first.json() == second.json()
    with SessionDB() as db:
        assert HomeStore(db).status()["session_id"] == first.json()["session_id"]


def test_dashboard_home_uses_the_live_owner_instead_of_a_second_writer(client, monkeypatch):
    from hermes_cli import gateway_client, sessions_owner
    from hermes_cli.web_routers import home
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def rpc(self, name):
            calls.append(name)
            return {"session_id": "owner-home", "output": "Home is ready."}

    monkeypatch.setattr(sessions_owner, "live_owner", lambda: object())
    monkeypatch.setattr(gateway_client, "connect_gateway", lambda _endpoint: Client())
    monkeypatch.setattr(home, "_open_home_db", lambda *_a, **_k: pytest.fail("must use owner"))
    result = client.post("/api/home/open?profile=default")
    assert result.status_code == 200, result.text
    assert result.json() == {"session_id": "owner-home"}
    assert calls == ["home.action"]


def test_multiplexed_home_requires_an_explicit_profile(client, monkeypatch):
    monkeypatch.setattr("agent.secret_scope.is_multiplex_active", lambda: True)
    result = client.post("/api/home/open")
    assert result.status_code == 400
    assert "explicit profile" in result.json()["detail"]
