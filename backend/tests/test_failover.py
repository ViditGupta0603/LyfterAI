"""Failover on real-style provider errors and through the X-Simulate-Failure hook."""

import litellm
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import KEY_1, KEY_2, chat

P = dict(llm_provider="gemini", model="gemini-2.5-flash-lite")


def _status(exc, code):
    exc.status_code = code
    return exc


KEY_FAILURES = [
    pytest.param(litellm.RateLimitError("429 Too Many Requests", **P), id="429"),
    pytest.param(litellm.RateLimitError("RESOURCE_EXHAUSTED: quota exceeded", **P), id="quota"),
    pytest.param(litellm.InternalServerError("500", **P), id="500"),
    pytest.param(litellm.BadGatewayError("502", **P), id="502"),
    pytest.param(litellm.ServiceUnavailableError("503 model overloaded", **P), id="503"),
    pytest.param(litellm.Timeout("timed out", model="m", llm_provider="gemini"), id="timeout"),
    pytest.param(litellm.APIConnectionError("connection reset", **P), id="connection"),
    pytest.param(litellm.AuthenticationError("401 invalid key", **P), id="401"),
    pytest.param(litellm.BadRequestError("API key not valid. API_KEY_INVALID", model="m", llm_provider="gemini"), id="400-invalid-key"),
    pytest.param(_status(litellm.BadRequestError("Forbidden", model="m", llm_provider="gemini"), 403), id="403-wrapped"),
    pytest.param(litellm.NotFoundError("model not found", **P), id="404-model"),
]


@pytest.mark.parametrize("exc", KEY_FAILURES)
def test_key_failure_falls_over_to_next_key(client, provider, exc):
    provider.fail(KEY_1, exc)
    r = chat(client, "f", "hello")
    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert provider.calls == [KEY_2]


def test_all_keys_failing_returns_503_and_stores_nothing(client, provider):
    provider.fail(KEY_1, litellm.RateLimitError("429", **P))
    provider.fail(KEY_2, litellm.ServiceUnavailableError("503", **P))
    r = chat(client, "down", "hello")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/down/messages").status_code == 404


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(litellm.ContextWindowExceededError("too long", model="m", llm_provider="gemini"), id="context"),
        pytest.param(litellm.ContentPolicyViolationError("blocked", model="m", llm_provider="gemini"), id="safety"),
        pytest.param(litellm.BadRequestError("invalid argument", model="m", llm_provider="gemini"), id="bad-request"),
    ],
)
def test_request_errors_do_not_try_other_keys(client, provider, exc):
    provider.fail(KEY_1, exc)
    r = chat(client, "bad", "hello")
    assert r.status_code == 502
    assert r.json() == {"detail": "model could not answer this request"}
    assert provider.calls == []  # key_2 was never tried
    assert client.get("/sessions/bad/messages").status_code == 404


def test_empty_reply_is_refused_and_never_cached(client, provider):
    provider.behaviour[KEY_1] = "   "
    assert chat(client, "e1", "say nothing").status_code == 502
    provider.behaviour.pop(KEY_1)
    r = chat(client, "e2", "say nothing").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["reply"].strip()


# ------------------------------------------------------------------ X-Simulate-Failure


@pytest.mark.parametrize("header", ["key_1=429", "key_1=500", "key_1=502", "key_1=503"])
def test_simulated_key_1_failure_is_answered_by_key_2(client, provider, header):
    r = chat(client, "sim", "simulate me", simulate=header)
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    assert body["reply"].startswith("[")  # a real answer, not an error wrapped in a 200
    assert provider.calls == [KEY_2]


@pytest.mark.parametrize("header", ["*=429", "key_1=429,key_2=500"])
def test_simulated_total_failure_is_503_and_not_stored(client, provider, header):
    r = chat(client, "sim-down", "simulate me", simulate=header)
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert provider.calls == []
    assert client.get("/sessions/sim-down/messages").status_code == 404


def test_simulated_failure_in_existing_session_adds_nothing(client):
    chat(client, "keep", "first")
    chat(client, "keep", "second", simulate="*=429")
    assert len(client.get("/sessions/keep/messages").json()["messages"]) == 2


def test_simulation_bypasses_cache_so_failover_is_really_exercised(client):
    chat(client, "a", "What is the capital of France?")  # now cached
    r = chat(client, "b", "What is the capital of France?", simulate="key_1=429").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["metadata"]["key_id"] == "key_2"


def test_simulation_affects_only_that_request(client):
    chat(client, "x", "one", simulate="key_1=429")
    r = chat(client, "y", "two").json()
    assert r["metadata"]["key_id"] == "key_1"
    assert r["metadata"]["fallback_attempts"] == 0


def test_garbage_header_is_ignored(client):
    r = chat(client, "g", "hello", simulate="abc,,key_9=500,key_1=418")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_1"


def test_header_ignored_when_simulation_disabled(provider, make_settings):
    with TestClient(create_app(make_settings(ENABLE_FAILURE_SIMULATION="false"))) as c:
        r = chat(c, "off", "hello", simulate="*=429")
        assert r.status_code == 200
        assert r.json()["metadata"]["key_id"] == "key_1"
