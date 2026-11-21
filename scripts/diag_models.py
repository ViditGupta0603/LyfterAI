r"""Time one tiny generateContent call per available Flash model, for one key of the pool.
Run from the repo root (N = 1 for key_1, 2 for key_2; default 1):
    backend\.venv\Scripts\python scripts\diag_models.py 2
Prints model ids and timings only; never prints the key."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402

from app.config import Settings  # noqa: E402

index = int(sys.argv[1]) if len(sys.argv) > 1 else 1
key = Settings().keys[index - 1].secret
print(f"Testing with key_{index}")
base = "https://generativelanguage.googleapis.com/v1beta"
headers = {"x-goog-api-key": key}

with httpx.Client(timeout=40, headers=headers) as client:
    models = client.get(f"{base}/models", params={"pageSize": 200}).json().get("models", [])
    candidates = sorted(
        m["name"].split("/", 1)[1]
        for m in models
        if "flash" in m["name"]
        and "generateContent" in m.get("supportedGenerationMethods", [])
        and not any(x in m["name"] for x in ("image", "tts", "audio", "live", "embedding"))
    )
    print(f"{len(candidates)} text Flash models available to this key\n")
    body = {"contents": [{"parts": [{"text": "Say hi"}]}]}
    for model_id in candidates:
        t = time.perf_counter()
        try:
            r = client.post(f"{base}/models/{model_id}:generateContent", json=body)
            status = r.status_code
        except Exception as e:  # timeout etc.
            status = type(e).__name__
        print(f"{model_id:<45} {int((time.perf_counter() - t) * 1000):>6} ms  {status}")
