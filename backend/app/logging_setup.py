"""Logging with API-key redaction.

Provider errors can echo the request URL, and Gemini can put the key in it (?key=...).
Redaction is done in a global LogRecord factory, so it applies to every record from
every logger (ours, uvicorn, LiteLLM, httpx), whatever handlers are attached later."""

from __future__ import annotations

import logging
import traceback

from .config import ApiKey

_BASE_FACTORY = logging.getLogRecordFactory()


def _redact(text: str, keys: list[ApiKey]) -> str:
    for key in keys:
        text = text.replace(key.secret, f"<{key.id}>")
    return text


def install_redaction(keys: list[ApiKey]) -> None:
    keys = [k for k in keys if k.secret]

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = _BASE_FACTORY(*args, **kwargs)
        if not keys:
            return record
        try:
            message = record.getMessage()
        except Exception:
            return record
        redacted = _redact(message, keys)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and record.exc_info[1] is not None:
            exc_text = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            record.exc_text, record.exc_info = _redact(exc_text, keys), None
        return record

    logging.setLogRecordFactory(factory)


def setup_logging(level: str, keys: list[ApiKey]) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    install_redaction(keys)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
