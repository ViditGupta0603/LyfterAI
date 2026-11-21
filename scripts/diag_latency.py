r"""Find where live-call latency comes from. Run from the repo root:
    backend\.venv\Scripts\python scripts\diag_latency.py
Prints timings only; never prints the key."""

import asyncio
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402

from app.config import Settings  # noqa: E402

s = Settings()
key = s.keys[0].secret
model_id = s.llm_model.split("/", 1)[1]
host = "generativelanguage.googleapis.com"
url = f"https://{host}/v1beta/models/{model_id}:generateContent"
body = {"contents": [{"parts": [{"text": "Say hi"}]}]}


def timed(label, fn):
    t = time.perf_counter()
    try:
        out = fn()
        print(f"{label:<45} {int((time.perf_counter() - t) * 1000):>6} ms  {out}")
    except Exception as e:
        print(f"{label:<45} {int((time.perf_counter() - t) * 1000):>6} ms  ERROR {type(e).__name__}: {str(e).replace(key, '<KEY>')[:120]}")


timed("1. DNS lookup (all addresses)", lambda: sorted({a[4][0] for a in socket.getaddrinfo(host, 443)}))
timed("2. raw HTTPS call, sync httpx", lambda: httpx.post(url, json=body, headers={"x-goog-api-key": key}, timeout=30).status_code)


async def raw_async():
    async with httpx.AsyncClient(timeout=30) as c:
        return (await c.post(url, json=body, headers={"x-goog-api-key": key})).status_code


timed("3. raw HTTPS call, async httpx", lambda: asyncio.run(raw_async()))

import litellm  # noqa: E402

litellm.suppress_debug_info = True


async def via_litellm():
    r = await litellm.acompletion(model=s.llm_model, api_key=key, messages=[{"role": "user", "content": "Say hi"}],
                                  num_retries=0, max_retries=0, timeout=30)
    return repr(r.choices[0].message.content[:30])


timed("4. litellm.acompletion (default transport)", lambda: asyncio.run(via_litellm()))
timed("5. litellm.acompletion again (warm)", lambda: asyncio.run(via_litellm()))
litellm.disable_aiohttp_transport = True
timed("6. litellm.acompletion, aiohttp disabled", lambda: asyncio.run(via_litellm()))
