"""SQLite-backed persistent event storage."""

import json
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "onlycat_events.db"


class EventStore:
    def __init__(self, db_path: str | Path = DB_PATH):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self):
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                timestamp TEXT,
                trigger_source INTEGER,
                classification INTEGER,
                rfid_codes TEXT,
                frame_count INTEGER,
                raw JSON
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
        """)
        await self._db.commit()
        logger.info("Event store opened: %s", self._db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    async def upsert(self, event: dict):
        """Insert or update an event."""
        event_id = event.get("eventId")
        if event_id is None:
            return
        await self._db.execute(
            """INSERT INTO events (event_id, device_id, timestamp, trigger_source,
                                   classification, rfid_codes, frame_count, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_id) DO UPDATE SET
                   timestamp=excluded.timestamp,
                   trigger_source=excluded.trigger_source,
                   classification=excluded.classification,
                   rfid_codes=excluded.rfid_codes,
                   frame_count=excluded.frame_count,
                   raw=excluded.raw
            """,
            (
                event_id,
                event.get("deviceId", ""),
                event.get("timestamp", ""),
                event.get("eventTriggerSource"),
                event.get("eventClassification"),
                json.dumps(event.get("rfidCodes") or []),
                event.get("frameCount", 0),
                json.dumps(event),
            ),
        )
        await self._db.commit()

    async def upsert_many(self, events: list[dict]):
        """Insert or update multiple events."""
        for ev in events:
            event_id = ev.get("eventId")
            if event_id is None:
                continue
            await self._db.execute(
                """INSERT INTO events (event_id, device_id, timestamp, trigger_source,
                                       classification, rfid_codes, frame_count, raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(event_id) DO UPDATE SET
                       timestamp=excluded.timestamp,
                       trigger_source=excluded.trigger_source,
                       classification=excluded.classification,
                       rfid_codes=excluded.rfid_codes,
                       frame_count=excluded.frame_count,
                       raw=excluded.raw
                """,
                (
                    event_id,
                    ev.get("deviceId", ""),
                    ev.get("timestamp", ""),
                    ev.get("eventTriggerSource"),
                    ev.get("eventClassification"),
                    json.dumps(ev.get("rfidCodes") or []),
                    ev.get("frameCount", 0),
                    json.dumps(ev),
                ),
            )
        await self._db.commit()

    async def get_recent(self, limit: int = 50) -> list[dict]:
        """Get the most recent events."""
        async with self._db.execute(
            "SELECT raw FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def get_since(self, since_iso: str) -> list[dict]:
        """Get all events since a given ISO timestamp."""
        async with self._db.execute(
            "SELECT raw FROM events WHERE timestamp >= ? ORDER BY timestamp DESC",
            (since_iso,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def get_all(self) -> list[dict]:
        """Get all stored events."""
        async with self._db.execute(
            "SELECT raw FROM events ORDER BY timestamp DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM events") as cursor:
            row = await cursor.fetchone()
        return row[0]
