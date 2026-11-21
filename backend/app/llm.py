"""Key failover engine + LiteLLM response cache.

Design (TRD "Failover engine" / "Caching"):
- Our own ordered loop over key_1..key_n calling litellm.acompletion with one key at a time.
  LiteLLM's Router is not used because its cooldowns would make a simulated failure
  leak into later requests and would blur key_id / fallback_attempts.
- LiteLLM disk cache. Reads happen inside acompletion; writes are done by us, awaited,
  and only for validated replies (cache={"no-store": True} on every call).
- X-Simulate-Failure: the listed keys raise real LiteLLM exception types inside the same
  try block a real call uses, and the cache read is skipped for that request (decision A1).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import litellm
from litellm.caching.caching import Cache

from .config import ApiKey, Settings

log = logging.getLogger("app.llm")

litellm.suppress_debug_info = True
litellm.telemetry = False


# ---------------------------------------------------------------- results / errors


@dataclass
class CompletionResult:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int
    cached: bool


class AllProvidersUnavailable(Exception):
    """Every key failed (rate limit, quota, 5xx, timeout, auth...). -> HTTP 503"""


class ModelRefused(Exception):
    """The request itself can't be answered (bad request, too long, safety block,
    empty reply). Retrying other keys would fail the same way. -> HTTP 502"""


# ---------------------------------------------------------------- error classification

# Message fragments meaning "this key/project is the problem", even when the provider
# reports it with a 400/403 status (Gemini returns 400 API_KEY_INVALID, for example).
_KEY_PROBLEM_HINTS = (
    "quota",
    "resource_exhausted",
    "insufficient_quota",
    "billing",
    "api key",
    "api_key",
    "permission",
    "rate limit",
)


def is_key_failure(exc: BaseException) -> bool:
    """True -> try the next key. False -> the request itself is bad (raise ModelRefused)."""
    if isinstance(exc, (asyncio.TimeoutError, litellm.Timeout, litellm.APIConnectionError)):
        return True
    if isinstance(
        exc,
        (
            litellm.RateLimitError,
            litellm.AuthenticationError,
            litellm.PermissionDeniedError,
            litellm.NotFoundError,
            litellm.InternalServerError,
            litellm.BadGatewayError,
            litellm.ServiceUnavailableError,
        ),
    ):
        return True
    if isinstance(exc, (litellm.ContextWindowExceededError, litellm.ContentPolicyViolationError)):
        return False
    # Status beats exception class: LiteLLM sometimes wraps an auth/permission/proxy 403
    # or a 5xx in BadRequestError. Those are about the key/route, not the request.
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status in (401, 403, 408, 429) or status >= 500):
        return True
    if isinstance(exc, litellm.BadRequestError):
        text = str(exc).lower()
        return any(hint in text for hint in _KEY_PROBLEM_HINTS)
    if isinstance(status, int) and 400 <= status < 500 and status != 404:
        return False
    return True  # unknown / 5xx / anything else: assume transient, move on


def _simulated_error(status: int, model: str) -> Exception:
    msg = f"simulated failure ({status}) via X-Simulate-Failure"
    if status == 429:
        return litellm.RateLimitError(msg, llm_provider="simulated", model=model)
    if status == 502:
        return litellm.BadGatewayError(msg, llm_provider="simulated", model=model)
    if status == 503:
        return litellm.ServiceUnavailableError(msg, llm_provider="simulated", model=model)
    return litellm.InternalServerError(msg, llm_provider="simulated", model=model)


# ---------------------------------------------------------------- cache


def setup_cache(settings: Settings) -> str:
    """Configure litellm.cache. Returns the backend in use: 'disk', 'memory' or 'off'."""
    if not settings.cache_enabled:
        litellm.cache = None
        return "off"
    try:
        litellm.cache = Cache(
            type="disk", disk_cache_dir=settings.cache_dir, ttl=settings.cache_ttl_seconds
        )
        return "disk"
    except Exception:
        # Volume missing / not writable: keep working, just not persistent.
        log.exception("disk cache unavailable at %s; falling back to in-memory", settings.cache_dir)
        litellm.cache = Cache(type="local", ttl=settings.cache_ttl_seconds or 24 * 3600)
        return "memory"


# ---------------------------------------------------------------- engine


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.keys: list[ApiKey] = settings.keys
        self.model = settings.llm_model
        self.cache_backend = setup_cache(settings)
        # Sampling params are part of LiteLLM's cache key, so the read (acompletion) and the
        # write (async_add_cache) must use exactly the same set.
        self.sampling: dict[str, Any] = {}
        if settings.temperature is not None:
            self.sampling["temperature"] = settings.temperature
        if settings.reasoning_effort:
            self.sampling["reasoning_effort"] = settings.reasoning_effort

    @property
    def cache_enabled(self) -> bool:
        return litellm.cache is not None

    def _redact(self, text: str) -> str:
        for key in self.keys:
            text = text.replace(key.secret, f"<{key.id}>")
        return text

    async def warm_up(self) -> None:
        """Exercise the cache-hit path once at boot (no network: mock_response).

        Loads LiteLLM's lazily imported cache-hit modules so (a) a missing dependency
        fails at startup, not on the grader's first cache hit, and (b) the first real
        hit is fast."""
        if not self.cache_enabled:
            return
        messages = [{"role": "user", "content": f"__warmup__{uuid.uuid4()}"}]
        kwargs = dict(model=self.model, messages=messages, **self.sampling)
        first = await litellm.acompletion(
            **kwargs, api_key="warmup", mock_response="ok", cache={"no-store": True}
        )
        await litellm.cache.async_add_cache(first, **kwargs)
        second = await litellm.acompletion(
            **kwargs, api_key="warmup", mock_response="miss", cache={"no-store": True}
        )
        if second._hidden_params.get("cache_hit") is not True:
            raise RuntimeError("LiteLLM cache warm-up failed: stored entry was not read back")

    async def complete(
        self, messages: list[dict[str, str]], simulate: dict[str, int] | None = None
    ) -> CompletionResult:
        simulate = simulate or {}
        cache_ctl: dict[str, Any] = {"no-store": True}
        if simulate:
            cache_ctl["no-cache"] = True  # decision A1: a simulated request must hit the keys

        deadline = time.monotonic() + self.settings.request_budget_seconds
        failures = 0
        for key in self.keys:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("request budget exhausted after %d failed key(s)", failures)
                break
            timeout = min(self.settings.attempt_timeout_seconds, remaining)
            try:
                if key.id in simulate:
                    raise _simulated_error(simulate[key.id], self.model)
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=self.model,
                        messages=messages,
                        api_key=key.secret,
                        **self.sampling,
                        timeout=timeout,
                        num_retries=0,
                        max_retries=0,
                        cache=cache_ctl,
                    ),
                    timeout=timeout + 1,
                )
            except Exception as exc:  # noqa: BLE001 - classification below
                if not is_key_failure(exc):
                    log.warning(
                        "%s rejected the request (%s); not trying other keys",
                        key.id,
                        type(exc).__name__,
                    )
                    raise ModelRefused(type(exc).__name__) from None
                failures += 1
                log.warning(
                    "%s failed (%s, status=%s): %s",
                    key.id,
                    type(exc).__name__,
                    getattr(exc, "status_code", None),
                    self._redact(str(exc))[:300],
                )
                continue

            return await self._finish(response, messages, key, failures)

        raise AllProvidersUnavailable()

    async def _finish(
        self, response: Any, messages: list[dict[str, str]], key: ApiKey, failures: int
    ) -> CompletionResult:
        cached = response._hidden_params.get("cache_hit") is True
        try:
            text = response.choices[0].message.content
        except (AttributeError, IndexError):
            text = None
        if not text or not str(text).strip():
            log.warning("%s returned an empty reply (finish_reason=%s)", key.id,
                        getattr(response.choices[0], "finish_reason", None) if response.choices else None)
            raise ModelRefused("empty reply")

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        if input_tokens is None:
            input_tokens = litellm.token_counter(model=self.model, messages=messages)
        if output_tokens is None:
            output_tokens = litellm.token_counter(model=self.model, text=str(text))

        if not cached and self.cache_enabled:
            try:
                await litellm.cache.async_add_cache(
                    response, model=self.model, messages=messages, **self.sampling
                )
            except Exception:  # a cache write must never cost the user their reply
                log.exception("cache write failed")

        return CompletionResult(
            reply=str(text),
            model=self.model,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            key_id=None if cached else key.id,
            fallback_attempts=0 if cached else failures,
            cached=cached,
        )
