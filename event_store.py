"""SQLite-backed persistent storage for events, devices, and pets."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "onlycat_events.db"))


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
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                description TEXT,
                connectivity JSON
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                rfid_code TEXT PRIMARY KEY,
                label TEXT,
                last_seen TEXT,
                device_id TEXT
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                threshold INTEGER,
                enabled INTEGER DEFAULT 1
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS door_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                enabled INTEGER DEFAULT 1
            )
        """)
        await self._db.commit()
        logger.info("Event store opened: %s", self._db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    # --- Events ---

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

    # --- Devices ---

    async def upsert_device(self, device_id: str, description: str, connectivity: dict):
        await self._db.execute(
            """INSERT INTO devices (device_id, description, connectivity)
               VALUES (?, ?, ?)
               ON CONFLICT(device_id) DO UPDATE SET
                   description=excluded.description,
                   connectivity=excluded.connectivity
            """,
            (device_id, description, json.dumps(connectivity)),
        )
        await self._db.commit()

    async def get_devices(self) -> list[dict]:
        async with self._db.execute("SELECT device_id, description, connectivity FROM devices") as cursor:
            rows = await cursor.fetchall()
        return [
            {"device_id": r[0], "description": r[1], "connectivity": json.loads(r[2] or "{}")}
            for r in rows
        ]

    # --- Pets ---

    async def upsert_pet(self, rfid_code: str, label: str, last_seen: str, device_id: str):
        await self._db.execute(
            """INSERT INTO pets (rfid_code, label, last_seen, device_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(rfid_code) DO UPDATE SET
                   label=excluded.label,
                   last_seen=excluded.last_seen,
                   device_id=excluded.device_id
            """,
            (rfid_code, label, last_seen, device_id),
        )
        await self._db.commit()

    async def get_pets(self) -> list[dict]:
        async with self._db.execute("SELECT rfid_code, label, last_seen, device_id FROM pets") as cursor:
            rows = await cursor.fetchall()
        return [
            {"rfid_code": r[0], "label": r[1], "last_seen": r[2], "device_id": r[3]}
            for r in rows
        ]

    # --- Sync metadata ---

    async def set_meta(self, key: str, value: str):
        await self._db.execute(
            "INSERT INTO sync_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self._db.commit()

    async def get_meta(self, key: str) -> str | None:
        async with self._db.execute("SELECT value FROM sync_meta WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    # --- Annotations ---

    async def add_annotation(self, event_id: int, note: str):
        created_at = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO annotations (event_id, note, created_at) VALUES (?, ?, ?)",
            (event_id, note, created_at),
        )
        await self._db.commit()

    async def get_annotations(self, event_id: int) -> list[dict]:
        async with self._db.execute(
            "SELECT id, event_id, note, created_at FROM annotations WHERE event_id = ? ORDER BY created_at",
            (event_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"id": r[0], "event_id": r[1], "note": r[2], "created_at": r[3]} for r in rows]

    async def get_all_annotations(self) -> list[dict]:
        async with self._db.execute(
            "SELECT id, event_id, note, created_at FROM annotations ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"id": r[0], "event_id": r[1], "note": r[2], "created_at": r[3]} for r in rows]

    async def delete_annotation(self, annotation_id: int):
        await self._db.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        await self._db.commit()

    # --- Alerts ---

    async def add_alert(self, name: str, alert_type: str, threshold: int | None):
        await self._db.execute(
            "INSERT INTO alerts (name, alert_type, threshold) VALUES (?, ?, ?)",
            (name, alert_type, threshold),
        )
        await self._db.commit()

    async def get_alerts(self) -> list[dict]:
        async with self._db.execute(
            "SELECT id, name, alert_type, threshold, enabled FROM alerts ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"id": r[0], "name": r[1], "alert_type": r[2], "threshold": r[3], "enabled": bool(r[4])} for r in rows]

    async def update_alert(self, alert_id: int, enabled: bool):
        await self._db.execute(
            "UPDATE alerts SET enabled = ? WHERE id = ?", (int(enabled), alert_id)
        )
        await self._db.commit()

    async def delete_alert(self, alert_id: int):
        await self._db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        await self._db.commit()

    # --- Door Schedule ---

    async def add_schedule(self, device_id: str, action: str, hour: int, minute: int, days: str = "0,1,2,3,4,5,6"):
        await self._db.execute(
            "INSERT INTO door_schedule (device_id, action, hour, minute, days) VALUES (?, ?, ?, ?, ?)",
            (device_id, action, hour, minute, days),
        )
        await self._db.commit()

    async def get_schedules(self) -> list[dict]:
        async with self._db.execute(
            "SELECT id, device_id, action, hour, minute, days, enabled FROM door_schedule ORDER BY hour, minute"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {"id": r[0], "device_id": r[1], "action": r[2], "hour": r[3], "minute": r[4], "days": r[5], "enabled": bool(r[6])}
            for r in rows
        ]

    async def delete_schedule(self, schedule_id: int):
        await self._db.execute("DELETE FROM door_schedule WHERE id = ?", (schedule_id,))
        await self._db.commit()

    async def update_schedule(self, schedule_id: int, enabled: bool):
        await self._db.execute(
            "UPDATE door_schedule SET enabled = ? WHERE id = ?", (int(enabled), schedule_id)
        )
        await self._db.commit()
