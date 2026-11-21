from tests.conftest import KEY_1, chat

METADATA_FIELDS = {
    "resolution_source", "model", "latency_ms", "input_tokens", "output_tokens", "key_id", "fallback_attempts",
}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["keys_configured"] == 2
    assert body["cache_enabled"] is True


def test_live_response_matches_contract(client, provider):
    r = chat(client, "s-7f3a", "What is the capital of France?")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s-7f3a"
    assert isinstance(body["reply"], str) and body["reply"]
    meta = body["metadata"]
    assert METADATA_FIELDS <= set(meta)
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-3.5-flash-lite"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    assert isinstance(meta["input_tokens"], int) and meta["input_tokens"] > 0
    assert isinstance(meta["output_tokens"], int) and meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert provider.calls == [KEY_1]


def test_same_first_message_in_new_session_is_a_cache_hit(client, provider):
    first = chat(client, "a", "What is the capital of France?").json()
    second = chat(client, "b", "What is the capital of France?").json()
    m1, m2 = first["metadata"], second["metadata"]
    assert m2["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert m2["key_id"] is None
    assert m2["fallback_attempts"] == 0
    assert (m2["input_tokens"], m2["output_tokens"]) == (m1["input_tokens"], m1["output_tokens"])
    assert m2["latency_ms"] <= m1["latency_ms"]
    assert len(provider.calls) == 1  # the hit never reached the provider


def test_different_message_is_never_served_from_cache(client):
    chat(client, "a", "What is the capital of France?")
    r = chat(client, "b", "What is the capital of Spain?").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert "Spain" in r["reply"]


def test_different_system_prompt_is_a_different_cache_key(client):
    chat(client, "a", "Hello there")
    r = chat(client, "b", "Hello there", system_prompt="Be terse").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["reply"].startswith("[Be terse]")


def test_same_message_later_in_a_session_is_live_because_history_differs(client):
    chat(client, "a", "Hello there")
    chat(client, "b", "Something else")
    r = chat(client, "b", "Hello there").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_system_prompt_persists_for_the_session(client):
    chat(client, "sp", "first", system_prompt="Pirate mode")
    r = chat(client, "sp", "second").json()
    assert r["reply"].startswith("[Pirate mode]")
    r = chat(client, "sp", "third", system_prompt="Robot mode").json()
    assert r["reply"].startswith("[Robot mode]")


def test_multi_turn_memory_and_session_isolation(client):
    chat(client, "mt", "my name is Advay")
    assert chat(client, "mt", "what is my name?").json()["reply"] == "Your name is Advay"
    assert chat(client, "other", "what is my name?").json()["reply"] == "I don't know your name"


def test_history_endpoint(client):
    chat(client, "h", "my name is Advay")
    chat(client, "h", "what is my name?")
    r = client.get("/sessions/h/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "h"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert body["messages"][0] == {"role": "user", "content": "my name is Advay"}
    meta = body["messages"][1]["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert {"input_tokens", "output_tokens"} <= set(meta)
    assert all(m["role"] != "system" for m in body["messages"])


def test_unknown_session_is_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_tokens_are_per_request_not_cumulative(client):
    a = chat(client, "t1", "aaaa bbbb cccc").json()["metadata"]["input_tokens"]
    b = chat(client, "t2", "dddd eeee ffff").json()["metadata"]["input_tokens"]
    assert abs(a - b) <= 2  # equal-length first messages -> about the same
    later = [chat(client, "t1", f"follow up {i}").json()["metadata"]["input_tokens"] for i in range(3)]
    history = client.get("/sessions/t1/messages").json()["messages"]
    stored = [m["metadata"]["input_tokens"] for m in history if m["role"] == "assistant"]
    assert stored == [a, *later]  # each turn reports its own usage


def test_cors_allows_only_configured_origin(client):
    ok = client.options(
        "/chat",
        headers={
            "Origin": "https://frontend.example.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://frontend.example.app"
    assert "x-simulate-failure" in ok.headers["access-control-allow-headers"].lower()
    other = client.options(
        "/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in other.headers
