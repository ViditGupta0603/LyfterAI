import pytest

from tests.conftest import chat


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"session_id": "s"}, id="missing-message"),
        pytest.param({"session_id": "s", "message": ""}, id="empty-message"),
        pytest.param({"session_id": "s", "message": " \n\t "}, id="whitespace-message"),
        pytest.param({"session_id": "s", "message": "x" * 4001}, id="message-4001"),
        pytest.param({"session_id": "s", "message": 123}, id="message-not-string"),
        pytest.param({"message": "hi"}, id="missing-session"),
        pytest.param({"session_id": "", "message": "hi"}, id="empty-session"),
        pytest.param({"session_id": "   ", "message": "hi"}, id="blank-session"),
        pytest.param({"session_id": "s" * 129, "message": "hi"}, id="session-129"),
        pytest.param({"session_id": "s", "message": "hi", "system_prompt": "p" * 4001}, id="system-prompt-too-long"),
    ],
)
def test_invalid_chat_requests_return_422_json(client, provider, body):
    r = client.post("/chat", json=body)
    assert r.status_code == 422
    assert "detail" in r.json()
    assert provider.calls == []  # nothing reached the provider


def test_malformed_json_returns_422(client):
    r = client.post("/chat", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()


def test_limits_are_inclusive_and_message_is_trimmed(client):
    assert chat(client, "s" * 128, "x" * 4000).status_code == 200
    r = chat(client, "trim", "   padded question   ")
    assert r.status_code == 200
    history = client.get("/sessions/trim/messages").json()["messages"]
    assert history[0]["content"] == "padded question"


def test_extra_fields_are_ignored(client):
    assert chat(client, "s", "hi", unexpected="field").status_code == 200


def test_failed_validation_stores_nothing(client):
    client.post("/chat", json={"session_id": "never", "message": ""})
    assert client.get("/sessions/never/messages").status_code == 404


def test_oversized_body_returns_413_json(client):
    r = client.post("/chat", content="x" * 70_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and "detail" in r.json()


def test_unknown_route_and_wrong_method_are_json(client):
    r = client.get("/does-not-exist")
    assert r.status_code == 404 and "detail" in r.json()
    r = client.put("/chat")
    assert r.status_code == 405 and "detail" in r.json()
