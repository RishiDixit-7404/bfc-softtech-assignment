"""HTTP-level tests for the transport layer.

``app.py`` has one job in each direction: give a message to the session named
by the request and return that session's reply untouched. So these assert
routing, identity and status codes - never conversation behaviour, which
``test_session.py`` covers against the same stub and without a server.

The provider is swapped for the stub and the session store is emptied per
test, so nothing here needs a key, a network, or a running uvicorn.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

import app as app_module
from test_session import LOAN_ROUTES, StubLLM


@pytest.fixture
def client(monkeypatch):
    """A client whose sessions use the stub, with no state carried between tests."""
    monkeypatch.setattr(app_module, "_LLM", StubLLM(routes=LOAN_ROUTES))
    monkeypatch.setattr(app_module, "_SESSIONS", {})
    return TestClient(app_module.app)


def test_session_returns_an_id_and_the_opening_message(client):
    response = client.post("/session")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert "Where would you like to start?" in body["reply"]


def test_two_sessions_get_different_ids(client):
    first = client.post("/session").json()["session_id"]
    second = client.post("/session").json()["session_id"]

    assert first != second


def test_chat_round_trips_a_message_to_its_own_session(client):
    """The id comes back, and the conversation is where the last turn left it."""
    session_id = client.post("/session").json()["session_id"]

    opening = client.post(
        "/chat", json={"session_id": session_id, "message": "calculate my loan tenure"}
    )
    assert opening.status_code == 200
    assert opening.json() == {
        "session_id": session_id,
        "reply": "How much is the loan?",
    }

    answered = client.post(
        "/chat", json={"session_id": session_id, "message": "5 lakh"}
    )
    assert answered.json()["reply"] == "What monthly EMI do you plan to pay?"


def test_one_session_cannot_see_another_ones_state(client):
    """Two conversations, two state machines. The id is the only thing joining them."""
    first = client.post("/session").json()["session_id"]
    second = client.post("/session").json()["session_id"]

    client.post(
        "/chat", json={"session_id": first, "message": "calculate my loan tenure"}
    )
    reply = client.post(
        "/chat", json={"session_id": second, "message": "5 lakh"}
    ).json()["reply"]

    assert reply != "What monthly EMI do you plan to pay?"


def test_an_unknown_session_id_is_a_404(client):
    response = client.post(
        "/chat", json={"session_id": "nosuchsession", "message": "hello"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown session"


def test_a_404_says_nothing_about_the_sessions_that_do_exist(client):
    known = client.post("/session").json()["session_id"]

    body = client.post(
        "/chat", json={"session_id": "nosuchsession", "message": "hello"}
    ).text

    assert known not in body


def test_the_static_mount_does_not_shadow_the_post_routes(client):
    """StaticFiles is mounted at "/" and would otherwise answer everything.

    It is registered last for exactly that reason. Moving it above the two
    routes turns the whole API into 404s from the static handler while the
    page itself keeps loading, which is a failure that looks like success.
    """
    assert client.post("/session").status_code == 200

    session_id = client.post("/session").json()["session_id"]
    chat = client.post("/chat", json={"session_id": session_id, "message": "hi"})
    assert chat.status_code == 200
    assert "reply" in chat.json()

    page = client.get("/")
    assert page.status_code == 200
    assert "<html" in page.text.lower()


def test_the_static_mount_is_registered_after_both_routes():
    """The ordering the test above depends on, asserted directly."""
    routes = app_module.app.routes
    mount = next(i for i, route in enumerate(routes) if isinstance(route, Mount))
    api = [
        i
        for i, route in enumerate(routes)
        if getattr(route, "path", None) in ("/session", "/chat")
    ]

    assert len(api) == 2
    assert max(api) < mount
