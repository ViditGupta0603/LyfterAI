"""SQLite storage: schema, history reads, and the one transaction that saves a turn.

Rules (TRD "SQLite storage"):
- The required `messages` table is kept verbatim; `sessions` holds the per-session system prompt.
- A turn is saved only after the LLM succeeded, in ONE transaction (user + assistant rows),
  so a failed request (422/502/503) never leaves anything behind.
- WAL + busy_timeout so concurrent readers never hit "database is locked".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id    TEXT PRIMARY KEY,
  system_prompt TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content    TEXT NOT NULL,
  metadata   TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def utc_now() -> str:
    """Server time, ISO-8601 UTC, e.g. 2026-11-20T15:04:05.123456+00:00."""
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    # ---------- lifecycle ----------

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database not connected")
        return self._conn

    async def ping(self) -> bool:
        """Used by /health: True only if a real query succeeds."""
        try:
            async with self.conn.execute("SELECT 1") as cur:
                return (await cur.fetchone())[0] == 1
        except Exception:
            return False

    # ---------- reads ----------

    async def get_system_prompt(self, session_id: str) -> str | None:
        async with self.conn.execute(
            "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return row["system_prompt"] if row else None

    async def get_recent_messages(self, session_id: str, limit: int) -> list[dict[str, str]]:
        """Last `limit` turns, oldest first, as LLM-ready {role, content} dicts."""
        if limit <= 0:
            return []
        async with self.conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def get_history(self, session_id: str) -> list[dict[str, Any]] | None:
        """Full history for GET /sessions/{id}/messages. None = unknown session (-> 404)."""
        async with self.conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return None
        out: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {"role": r["role"], "content": r["content"]}
            if r["role"] == "assistant" and r["metadata"]:
                item["metadata"] = json.loads(r["metadata"])
            out.append(item)
        return out

    # ---------- the one write ----------

    async def save_turn(
        self,
        session_id: str,
        system_prompt: str | None,
        user_message: str,
        assistant_reply: str,
        metadata: dict[str, Any],
    ) -> None:
        """Session upsert + user row + assistant row, all or nothing."""
        now = utc_now()
        try:
            await self.conn.execute("BEGIN IMMEDIATE")
            await self.conn.execute(
                """
                INSERT INTO sessions (session_id, system_prompt, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  system_prompt = excluded.system_prompt,
                  updated_at    = excluded.updated_at
                """,
                (session_id, system_prompt, now, now),
            )
            await self.conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, 'user', ?, NULL, ?)",
                (session_id, user_message, now),
            )
            await self.conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, 'assistant', ?, ?, ?)",
                (session_id, assistant_reply, json.dumps(metadata), utc_now()),
            )
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise
