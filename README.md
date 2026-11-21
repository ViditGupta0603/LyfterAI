# Lyftr AI — LLM Chatbot with Key Failover and Response Caching

React + FastAPI + SQLite + LiteLLM. A multi-turn chatbot that fails over between API keys
when one is rate-limited or down, serves repeated prompts from LiteLLM's cache, and shows
the source, model, latency and per-request token usage next to every reply.

## 1. Live URLs

| | URL |
| --- | --- |
| Frontend | _to be added after deployment_ |
| Backend | _to be added after deployment_ (`/health`) |
| Demo video | _to be added_ |

The deployed backend runs with `ENABLE_FAILURE_SIMULATION=true`, so the failover hook can
be tried directly against it.

## 2. Run locally

### With Docker (recommended)

Requires Docker (Docker Desktop on Windows/macOS).

```bash
cp .env.example .env        # then put your two API keys in LLM_API_KEYS
make up                     # frontend http://localhost:3000, backend http://localhost:8000
make logs                   # follow logs
make test                   # run the backend test suite inside Docker
make down                   # stop (history + cache are kept in the app_data volume)
```

Without `make` (e.g. plain PowerShell on Windows):

```bash
docker compose up -d --build
docker compose down
docker build --target test -t lyftr-backend-test ./backend && docker run --rm lyftr-backend-test
```

SQLite (`/data/app.db`) and the LiteLLM disk cache (`/data/llm_cache`) live on the named
volume `app_data`, so both survive `make down && make up`. `make clean` deletes the volume.

### Without Docker

Requires Python 3.10+ and Node 18+. In `.env`, use local paths:
`DATABASE_URL=sqlite:///./data/app.db` and `CACHE_DIR=./data/llm_cache`.

```bash
# backend (from backend/)
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt        # Windows: .venv\Scripts\python -m pip ...
.venv/bin/uvicorn app.main:app --port 8000           # Windows: .venv\Scripts\python -m uvicorn ...
.venv/bin/python -m pytest                           # 67 tests, no real API calls

# frontend (from frontend/), in a second terminal
npm install
npm run dev                                          # http://localhost:3000
```

The frontend calls `http://localhost:8000` by default (`VITE_API_URL` at build time or
`API_URL` in the Docker container overrides it).

### Configuration

All configuration is through environment variables; `.env.example` lists every one.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_API_KEYS` | (required) | Comma-separated key pool, ids `key_1`, `key_2`, … in order |
| `DATABASE_URL` | `sqlite:////data/app.db` | SQLite location |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `false` | Enables the `X-Simulate-Failure` hook |
| `LLM_MODEL` | `gemini/gemini-2.5-flash-lite` | LiteLLM model name |
| `CACHE_DIR` | `/data/llm_cache` | LiteLLM disk cache directory |
| `CACHE_ENABLED` / `CACHE_TTL_SECONDS` | `true` / unset | Cache switch and optional expiry |
| `DEFAULT_SYSTEM_PROMPT` | `You are a helpful assistant.` | Used when a session has none |
| `MAX_HISTORY_MESSAGES` | `40` | History sent to the model per request |
| `ATTEMPT_TIMEOUT_SECONDS` / `REQUEST_BUDGET_SECONDS` | `25` / `45` | Per-key and total time limits |
| `TEMPERATURE`, `REASONING_EFFORT` | unset | Optional sampling / thinking controls |
| `API_URL` (frontend container), `VITE_API_URL` (frontend build) | `http://localhost:8000` | Backend URL the browser calls |

## 3. Design decisions

### Request flow

```
POST /chat
  1. validate (pydantic)                         -> 422 JSON on bad input
  2. parse X-Simulate-Failure (if enabled)
  3. per-session lock; load system prompt + last 40 messages from SQLite
  4. failover loop over key_1..key_n, each call = litellm.acompletion(...)
       cache hit inside LiteLLM -> LLM_CACHE, no provider call
       429 / quota / 5xx / timeout / bad key -> next key
       all keys failed -> 503 {"detail": "all providers unavailable"}
  5. validate reply (non-empty), write it to the LiteLLM cache
  6. one SQLite transaction: user message + assistant message + metadata
```

### Key fallback

- **LiteLLM does the calls; a small loop picks the key.** Each attempt is
  `litellm.acompletion(api_key=...)`, and LiteLLM maps provider errors to typed exceptions
  (`RateLimitError`, `ServiceUnavailableError`, `AuthenticationError`, …) that drive the
  failover. I deliberately did not use `litellm.Router`: its cooldown puts a failed key
  aside for later requests too, which would make a simulated failure leak beyond "this
  request only", and it makes the exact `key_id` / `fallback_attempts` harder to report.
  An explicit ordered loop gives deterministic key order and exact metadata.
- **What fails over:** 429 and quota errors, 5xx (incl. Gemini's 503 "overloaded"),
  timeouts, connection errors, invalid or revoked keys (401/403, and Gemini's
  400 `API_KEY_INVALID`), and model-not-found. **What does not:** requests that would fail on
  every key (context too long, content policy, other 400s) return 502 at once instead of
  burning through the pool. An empty reply is also treated as a failed answer.
- **Retries:** LiteLLM's internal retries are off (`num_retries=0`), because they retry the
  same key. Each key gets a 25 s timeout and the whole request a 45 s budget, so the server
  always answers before the browser's 60 s timeout.
- **`X-Simulate-Failure`** raises the same LiteLLM exception types inside the same `try`
  block a real call uses, so the simulated path *is* the real path. Malformed pairs are
  ignored rather than rejected, so the test hook can never break a request.
- **Simulation skips the cache read.** If a cached message is sent with `key_1=429`,
  answering from cache would report `key_id: null`, contradicting the contract's
  `key_1=429 -> key_id = key_2`. With a valid simulation header the request always goes
  through the keys.
- **Keys** are never logged or returned: a global log-record hook replaces every key with
  its id (`<key_1>`) in all log output, from any library.
- The two keys come from **two separate Google projects**: Gemini rate limits apply per
  project, so two keys in one project would give no real redundancy.

### Caching

- **LiteLLM's built-in disk cache** (`litellm.Cache(type="disk")`), stored next to the
  database on the `/data` volume, so hits survive restarts. LiteLLM is pinned to
  `1.108.13` because the disk backend was removed in 1.109.0.
- **Cache key** = LiteLLM's hash of model + the full message list (system prompt + history
  + new message) + sampling parameters. The API key is not part of it, so a reply cached
  via `key_1` is served whichever key would have answered. The same first message in a new
  session is a hit; a different message, system prompt or history is a miss.
- **Explicit cache writes.** Calls use `cache={"no-store": True}` and the reply is written
  with `await litellm.cache.async_add_cache(...)` only after validation. LiteLLM's default
  write is asynchronous (an immediate repeat could miss), and this also guarantees that
  empty or refused replies are never cached.
- **Startup warm-up.** LiteLLM's cache-hit path imports extra modules lazily (`orjson`,
  `soundfile`, …). A mock round trip at boot loads them, so a missing dependency fails at
  startup instead of on the first real hit, and the first hit is fast (about 1-2 ms vs about
  1 s live).
- On a hit: `resolution_source = LLM_CACHE`, `key_id = null`, `fallback_attempts = 0`,
  identical reply text, and the token usage stored with the cached response.

### SQLite session storage

- The required `messages` table is kept exactly; a `sessions` table holds each session's
  system prompt (a later request can change it; omitting it keeps the stored one).
  Schema and index are created on startup.
- **A turn is written only after success**, in one transaction (session row + user row +
  assistant row). A 422/502/503 leaves nothing behind, and a session whose only request
  failed returns 404 from the history endpoint.
- WAL mode + `busy_timeout`, and a per-session `asyncio.Lock`, so concurrent requests in
  one session can't interleave history. The app runs a single uvicorn worker on purpose:
  the locks and the cache object are per process.
- History sent to the model is capped at the last 40 messages; the full history stays in
  SQLite.

### Model choice

`gemini/gemini-2.5-flash-lite`. Measured on 20 Nov 2026 with one tiny request per model:
2.5 Flash-Lite answered in about 1 s, the 3.5 / 3.6 Flash models took 10-30 s, and 3.7 /
3.8 returned 503 "overloaded". `gemini-2.0-flash` (the example in the brief) was shut down
by Google on 1 June 2026.

## 4. Verification

Examples use `bash` + `curl`; set `API=http://localhost:8000` or the deployed backend URL.

**Health**
```bash
curl -s $API/health
# {"status":"ok","keys_configured":2,"cache_enabled":true, ...}
```

**Cache hit** — the same first message in two new sessions:
```bash
curl -s $API/chat -H 'Content-Type: application/json' -d '{"session_id":"v-1","message":"What is the capital of France?"}'
# metadata.resolution_source = LIVE_INFERENCE, key_id = key_1
curl -s $API/chat -H 'Content-Type: application/json' -d '{"session_id":"v-2","message":"What is the capital of France?"}'
# metadata.resolution_source = LLM_CACHE, key_id = null, same reply and tokens, much lower latency_ms
```

**Failover**
```bash
curl -s $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
     -d '{"session_id":"v-3","message":"Name one planet"}'
# 200, key_id = key_2, fallback_attempts = 1, a real answer
curl -s -i $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
     -d '{"session_id":"v-4","message":"Name one river"}'
# HTTP 503 {"detail":"all providers unavailable"}; then GET /sessions/v-4/messages -> 404 (nothing stored)
```

**Per-message tokens and history**
```bash
curl -s $API/chat -H 'Content-Type: application/json' -d '{"session_id":"v-1","message":"What did I just ask?"}'
# input_tokens covers system + history + new message for THIS request only
curl -s $API/sessions/v-1/messages
# oldest first, assistant messages carry their metadata, no system prompt
```

**In the UI**: every reply shows Source (green `LIVE_INFERENCE` / purple `LLM_CACHE`),
model, latency, tokens in/out and the key used. Open *Session settings* and pick a failover
preset to send `X-Simulate-Failure` with the next message: `key_1` failures show as an amber
`key_2 · 1 failed before` chip; "all keys" shows a readable 503 error with Retry.

**Tests**: `make test` (or `pytest` in `backend/`) runs 67 tests with LiteLLM's mock
responses, no real API calls: every 422 case, the response contract, cache hits and misses,
failover on 11 provider error types, every `X-Simulate-Failure` case from the brief,
"failed requests store nothing", multi-turn memory, session isolation, CORS, key redaction
in logs, persistence across a restart, and concurrent requests in one session.

## 5. Setup Used

- Editor: VS Code
- AI tools: Claude (Anthropic) for planning (a PRD/TRD with a failure catalogue), code,
  tests and debugging. Design decisions were checked by running LiteLLM directly (cache
  behaviour, exception types, version differences) and by measuring model latency.

## 6. Bonus features

- **Failover demo control in the UI**: a dropdown that sends `X-Simulate-Failure` with the
  next message, so failover can be shown without curl.
- **Readable errors with Retry**: 422/502/503/network errors show as error bubbles; the
  unsent message is marked "not sent" (matching the server, which stored nothing).
- **Health badge** (keys, cache) and a "server may be waking up" hint for slow cold starts.
- **Resilience beyond the brief**: failover on timeouts, connection errors and invalid keys;
  per-key and total time limits; 502 without burning the key pool for requests no key can
  answer; empty replies never cached.
- **Key redaction in all logs**, including third-party libraries.
- **Persistent cache** on the Docker volume, and a startup warm-up of the cache-hit path.
- **Per-session system prompt** stored in SQLite.
- **67 backend tests**, runnable in Docker with `make test`.
