"""FastAPI app: exactly three endpoints (GET /health, POST /chat, GET /sessions/{id}/messages).

Error contract: every error is JSON with a `detail` field, never a stack trace or HTML.
A request that fails is never added to the session history.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .db import Database
from .llm import AllProvidersUnavailable, LLMService, ModelRefused
from .logging_setup import setup_logging
from .schemas import ChatMetadata, ChatRequest, ChatResponse, HealthResponse
from .simulation import parse_simulation_header

log = logging.getLogger("app")

MAX_BODY_BYTES = 64 * 1024


class SessionLocks:
    """One asyncio.Lock per session, so concurrent requests in the same session are
    handled one at a time (history order stays correct). Unused locks are dropped."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._users: defaultdict[str, int] = defaultdict(int)

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        self._users[session_id] += 1
        try:
            async with lock:
                yield
        finally:
            self._users[session_id] -= 1
            if self._users[session_id] == 0:
                self._users.pop(session_id, None)
                self._locks.pop(session_id, None)


def error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(settings.log_level, settings.keys)
        if len(settings.keys) < 2:
            log.warning("only %d API key(s) configured; failover needs at least 2", len(settings.keys))
        db = Database(settings.database_path)
        await db.connect()
        llm = LLMService(settings)
        await llm.warm_up()  # fail fast if the cache-hit path is broken
        app.state.db, app.state.llm, app.state.locks = db, llm, SessionLocks()
        log.info(
            "ready: %d key(s), model=%s, cache=%s, failure_simulation=%s, db=%s",
            len(settings.keys), settings.llm_model, llm.cache_backend,
            settings.enable_failure_simulation, settings.database_path,
        )
        try:
            yield
        finally:
            await db.close()

    app = FastAPI(title="Lyftr LLM Chatbot", version="1.0.0", lifespan=lifespan)

    origins = settings.origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
        max_age=600,
    )

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return error(413, f"request body larger than {MAX_BODY_BYTES} bytes")
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return error(500, "internal server error")

    # ------------------------------------------------------------------ routes

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request):
        state = request.app.state
        db: Database | None = getattr(state, "db", None)
        llm: LLMService | None = getattr(state, "llm", None)
        if db is None or llm is None:
            return error(503, "starting up")
        if not await db.ping():
            return error(503, "database unreachable")
        if not llm.keys:
            return error(503, "no API keys configured")
        return HealthResponse(
            status="ok",
            keys_configured=len(llm.keys),
            cache_enabled=llm.cache_enabled,
            cache_backend=llm.cache_backend,
            model=llm.model,
            failure_simulation=settings.enable_failure_simulation,
        )

    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest,
        request: Request,
        x_simulate_failure: str | None = Header(default=None),
    ):
        started = time.perf_counter()
        db: Database = request.app.state.db
        llm: LLMService = request.app.state.llm

        simulate: dict[str, int] = {}
        if settings.enable_failure_simulation and x_simulate_failure:
            simulate = parse_simulation_header(x_simulate_failure, [k.id for k in llm.keys])

        async with request.app.state.locks.hold(body.session_id):
            stored_prompt = await db.get_system_prompt(body.session_id)
            session_prompt = body.system_prompt if body.system_prompt is not None else stored_prompt
            history = await db.get_recent_messages(body.session_id, settings.max_history_messages)
            messages = [
                {"role": "system", "content": session_prompt or settings.default_system_prompt},
                *history,
                {"role": "user", "content": body.message},
            ]

            try:
                result = await llm.complete(messages, simulate)
            except AllProvidersUnavailable:
                return error(503, "all providers unavailable")
            except ModelRefused:
                return error(502, "model could not answer this request")

            metadata = ChatMetadata(
                resolution_source="LLM_CACHE" if result.cached else "LIVE_INFERENCE",
                model=result.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                key_id=result.key_id,
                fallback_attempts=result.fallback_attempts,
            )
            await db.save_turn(
                body.session_id, session_prompt, body.message, result.reply, metadata.model_dump()
            )

        return ChatResponse(session_id=body.session_id, reply=result.reply, metadata=metadata)

    @app.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str, request: Request):
        history = await request.app.state.db.get_history(session_id)
        if history is None:
            return error(404, "session not found")
        return {"session_id": session_id, "messages": history}

    return app


app = create_app()
