# syntax=docker/dockerfile:1

# ---------- builder: install pinned dependencies into a venv ----------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt

# ---------- test: `make test` builds this target and runs pytest ----------
FROM builder AS test
COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements-dev.txt
WORKDIR /app
COPY . .
CMD ["/opt/venv/bin/python", "-m", "pytest"]

# ---------- runtime: venv + app code only, non-root ----------
FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATABASE_URL=sqlite:////data/app.db \
    CACHE_DIR=/data/llm_cache
# /data is provided by a mounted volume: docker-compose named volume locally, a platform
# volume (e.g. Railway) in production. No VOLUME instruction: some hosts reject it.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)"
# One worker on purpose: per-session locks and the cache object live in-process.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
