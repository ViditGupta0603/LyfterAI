"""Shared fixtures. No test ever calls a real provider.

The provider is faked by replacing litellm.acompletion with a wrapper that calls the REAL
litellm.acompletion with `mock_response` (a reply string or a LiteLLM exception). So the
cache, the cache-hit flag, usage and exception types are all LiteLLM's own code paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY_1 = "test-secret-key-AAAA-1111"
KEY_2 = "test-secret-key-BBBB-2222"

_real_acompletion = litellm.acompletion


def default_reply(messages: list[dict[str, str]]) -> str:
    """Deterministic fake model: answers from the conversation so multi-turn is testable."""
    last = messages[-1]["content"]
    if last == "what is my name?":
        names = [m["content"] for m in messages if m["role"] == "user" and m["content"].startswith("my name is ")]
        return f"Your name is {names[-1].removeprefix('my name is ')}" if names else "I don't know your name"
    system = messages[0]["content"]
    return f"[{system}] answer to: {last}"


@dataclass
class FakeProvider:
    """Per-key behaviour: None -> answer normally; Exception -> raise it; str -> reply with it."""

    behaviour: dict[str, Any] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)  # secrets of keys that reached the "provider"
    reply_fn: Callable[[list[dict[str, str]]], str] = default_reply

    def fail(self, secret: str, exc: Exception) -> None:
        self.behaviour[secret] = exc

    async def __call__(self, **kwargs: Any):
        if "mock_response" in kwargs:  # warm-up already mocks itself
            return await _real_acompletion(**kwargs)
        secret = kwargs["api_key"]
        b = self.behaviour.get(secret)
        mock = b if b is not None else self.reply_fn(kwargs["messages"])
        response = await _real_acompletion(**kwargs, mock_response=mock)
        # Only count calls that were not served from cache (a hit never reaches a provider).
        if response._hidden_params.get("cache_hit") is not True:
            self.calls.append(secret)
        return response


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    fake = FakeProvider()
    monkeypatch.setattr(litellm, "acompletion", fake)
    return fake


@pytest.fixture
def make_settings(tmp_path) -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        values = dict(
            LLM_API_KEYS=f"{KEY_1},{KEY_2}",
            LLM_MODEL="gemini/gemini-3.5-flash-lite",
            DATABASE_URL=f"sqlite:///{tmp_path / 'data' / 'app.db'}",
            CACHE_DIR=str(tmp_path / "data" / "llm_cache"),
            ALLOWED_ORIGINS="https://frontend.example.app",
            ENABLE_FAILURE_SIMULATION="true",
            LOG_LEVEL="WARNING",
        )
        values.update(overrides)
        return Settings(_env_file=None, **values)  # never read the developer's real .env

    return _make


@pytest.fixture
def client(provider: FakeProvider, make_settings) -> TestClient:
    with TestClient(create_app(make_settings())) as c:
        yield c


def chat(client: TestClient, session_id: str, message: str, simulate: str | None = None, **extra: Any):
    headers = {"X-Simulate-Failure": simulate} if simulate else {}
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers)
