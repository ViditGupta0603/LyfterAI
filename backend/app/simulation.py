"""Parser for the X-Simulate-Failure test header.

Format: comma-separated <key_id>=<status> pairs, '*' = every key. Statuses: 429, 500, 502, 503.
    key_1=429            key_1=429,key_2=500            *=429

Malformed input never breaks a request: bad pairs, unknown key ids and unsupported
statuses are ignored (decision A7). Later pairs override earlier ones.
"""

from __future__ import annotations

SUPPORTED_STATUSES = frozenset({429, 500, 502, 503})


def parse_simulation_header(header: str | None, key_ids: list[str]) -> dict[str, int]:
    """Return {key_id: status} for the keys that must fail in this request."""
    if not header:
        return {}
    known = set(key_ids)
    plan: dict[str, int] = {}
    for part in header.split(","):
        if "=" not in part:
            continue
        raw_key, raw_status = part.split("=", 1)
        key = raw_key.strip().lower()
        status_text = raw_status.strip()
        if not status_text.isdigit() or int(status_text) not in SUPPORTED_STATUSES:
            continue
        status = int(status_text)
        if key == "*":
            for kid in key_ids:
                plan[kid] = status
        elif key in known:
            plan[key] = status
    return plan
