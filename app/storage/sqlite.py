from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS processed_updates (
                    update_id INTEGER PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    user_id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entity_usage (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id)
                );
                """
            )
            await db.commit()

    async def claim_update(self, update_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO processed_updates VALUES (?, ?)",
                (update_id, datetime.now(UTC).isoformat()),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def save_draft(
        self, user_id: int, payload: dict[str, Any], state: str = "review"
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO drafts VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    payload=excluded.payload, state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    state,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def get_draft(self, user_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT payload FROM drafts WHERE user_id=?", (user_id,)
                )
            ).fetchone()
        return json.loads(row[0]) if row else None

    async def update_draft(self, user_id: int, changes: dict[str, Any]) -> None:
        draft = await self.get_draft(user_id)
        if draft is None:
            raise KeyError("Черновик не найден")
        draft.update(changes)
        await self.save_draft(user_id, draft)

    async def delete_draft(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM drafts WHERE user_id=?", (user_id,))
            await db.commit()

    async def mark_entity_used(self, entity_type: str, entity_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO entity_usage VALUES (?, ?, ?)",
                (entity_type, entity_id, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def can_physically_delete(self, entity_type: str, entity_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT 1 FROM entity_usage WHERE entity_type=? AND entity_id=?",
                    (entity_type, entity_id),
                )
            ).fetchone()
        return row is None
