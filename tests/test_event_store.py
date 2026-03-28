"""Tests for the EventStore — all CRUD operations on SQLite."""

import pytest
import pytest_asyncio

from event_store import EventStore


@pytest_asyncio.fixture
async def store(tmp_path):
    s = EventStore(tmp_path / "test.db")
    await s.open()
    yield s
    await s.close()


def _make_event(event_id, device_id="DEV-1", ts="2026-03-20T10:00:00Z",
                trigger=3, classification=1, rfid_codes=None, frame_count=5):
    return {
        "eventId": event_id,
        "deviceId": device_id,
        "timestamp": ts,
        "eventTriggerSource": trigger,
        "eventClassification": classification,
        "rfidCodes": rfid_codes or [],
        "frameCount": frame_count,
    }


# --- Events ---

class TestEvents:
    @pytest.mark.asyncio
    async def test_upsert_and_count(self, store):
        await store.upsert(_make_event(1))
        assert await store.count() == 1

    @pytest.mark.asyncio
    async def test_upsert_ignores_none_event_id(self, store):
        await store.upsert({"deviceId": "DEV-1"})
        assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, store):
        await store.upsert(_make_event(1, classification=1))
        await store.upsert(_make_event(1, classification=3))
        events = await store.get_all()
        assert len(events) == 1
        assert events[0]["eventClassification"] == 3

    @pytest.mark.asyncio
    async def test_upsert_many(self, store):
        events = [_make_event(i, ts=f"2026-03-20T{10+i}:00:00Z") for i in range(5)]
        await store.upsert_many(events)
        assert await store.count() == 5

    @pytest.mark.asyncio
    async def test_upsert_many_skips_none_ids(self, store):
        events = [_make_event(1), {"deviceId": "DEV-1"}, _make_event(2)]
        await store.upsert_many(events)
        assert await store.count() == 2

    @pytest.mark.asyncio
    async def test_get_recent_ordering(self, store):
        await store.upsert(_make_event(1, ts="2026-03-20T08:00:00Z"))
        await store.upsert(_make_event(2, ts="2026-03-20T12:00:00Z"))
        await store.upsert(_make_event(3, ts="2026-03-20T10:00:00Z"))
        recent = await store.get_recent(2)
        assert len(recent) == 2
        assert recent[0]["eventId"] == 2  # newest first
        assert recent[1]["eventId"] == 3

    @pytest.mark.asyncio
    async def test_get_since(self, store):
        await store.upsert(_make_event(1, ts="2026-03-18T10:00:00Z"))
        await store.upsert(_make_event(2, ts="2026-03-20T10:00:00Z"))
        await store.upsert(_make_event(3, ts="2026-03-22T10:00:00Z"))
        events = await store.get_since("2026-03-19T00:00:00Z")
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_get_all(self, store):
        for i in range(3):
            await store.upsert(_make_event(i, ts=f"2026-03-20T{10+i}:00:00Z"))
        events = await store.get_all()
        assert len(events) == 3
        # Newest first
        assert events[0]["eventId"] == 2

    @pytest.mark.asyncio
    async def test_count_empty(self, store):
        assert await store.count() == 0


# --- Devices ---

class TestDevices:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, store):
        await store.upsert_device("DEV-1", "Front Door", {"connected": True})
        devices = await store.get_devices()
        assert len(devices) == 1
        assert devices[0]["device_id"] == "DEV-1"
        assert devices[0]["description"] == "Front Door"
        assert devices[0]["connectivity"]["connected"] is True

    @pytest.mark.asyncio
    async def test_upsert_updates_device(self, store):
        await store.upsert_device("DEV-1", "Front Door", {"connected": True})
        await store.upsert_device("DEV-1", "Back Door", {"connected": False})
        devices = await store.get_devices()
        assert len(devices) == 1
        assert devices[0]["description"] == "Back Door"
        assert devices[0]["connectivity"]["connected"] is False

    @pytest.mark.asyncio
    async def test_get_devices_empty(self, store):
        assert await store.get_devices() == []


# --- Pets ---

class TestPets:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, store):
        await store.upsert_pet("RFID-001", "Oni", "2026-03-20T10:00:00Z", "DEV-1")
        pets = await store.get_pets()
        assert len(pets) == 1
        assert pets[0]["label"] == "Oni"
        assert pets[0]["rfid_code"] == "RFID-001"

    @pytest.mark.asyncio
    async def test_upsert_updates_pet(self, store):
        await store.upsert_pet("RFID-001", "Oni", "2026-03-20T10:00:00Z", "DEV-1")
        await store.upsert_pet("RFID-001", "Oni", "2026-03-21T10:00:00Z", "DEV-2")
        pets = await store.get_pets()
        assert len(pets) == 1
        assert pets[0]["last_seen"] == "2026-03-21T10:00:00Z"
        assert pets[0]["device_id"] == "DEV-2"

    @pytest.mark.asyncio
    async def test_get_pets_empty(self, store):
        assert await store.get_pets() == []


# --- Sync Metadata ---

class TestMeta:
    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        await store.set_meta("last_sync", "2026-03-20T10:00:00Z")
        assert await store.get_meta("last_sync") == "2026-03-20T10:00:00Z"

    @pytest.mark.asyncio
    async def test_get_missing_key(self, store):
        assert await store.get_meta("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_overwrites(self, store):
        await store.set_meta("key", "v1")
        await store.set_meta("key", "v2")
        assert await store.get_meta("key") == "v2"


# --- Annotations ---

class TestAnnotations:
    @pytest.mark.asyncio
    async def test_add_and_get(self, store):
        await store.add_annotation(100, "Oni brought a mouse")
        annotations = await store.get_annotations(100)
        assert len(annotations) == 1
        assert annotations[0]["note"] == "Oni brought a mouse"
        assert annotations[0]["event_id"] == 100

    @pytest.mark.asyncio
    async def test_get_annotations_wrong_event(self, store):
        await store.add_annotation(100, "note")
        assert await store.get_annotations(999) == []

    @pytest.mark.asyncio
    async def test_get_all_annotations(self, store):
        await store.add_annotation(1, "note 1")
        await store.add_annotation(2, "note 2")
        all_annotations = await store.get_all_annotations()
        assert len(all_annotations) == 2

    @pytest.mark.asyncio
    async def test_delete_annotation(self, store):
        await store.add_annotation(100, "to delete")
        annotations = await store.get_annotations(100)
        await store.delete_annotation(annotations[0]["id"])
        assert await store.get_annotations(100) == []

    @pytest.mark.asyncio
    async def test_multiple_annotations_per_event(self, store):
        await store.add_annotation(100, "note 1")
        await store.add_annotation(100, "note 2")
        annotations = await store.get_annotations(100)
        assert len(annotations) == 2


# --- Alerts ---

class TestAlerts:
    @pytest.mark.asyncio
    async def test_add_and_get(self, store):
        await store.add_alert("Outside too long", "outside_too_long", 120)
        alerts = await store.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["name"] == "Outside too long"
        assert alerts[0]["alert_type"] == "outside_too_long"
        assert alerts[0]["threshold"] == 120
        assert alerts[0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_add_alert_no_threshold(self, store):
        await store.add_alert("Contraband", "contraband", None)
        alerts = await store.get_alerts()
        assert alerts[0]["threshold"] is None

    @pytest.mark.asyncio
    async def test_update_alert_enabled(self, store):
        await store.add_alert("Test", "contraband", None)
        alerts = await store.get_alerts()
        await store.update_alert(alerts[0]["id"], False)
        alerts = await store.get_alerts()
        assert alerts[0]["enabled"] is False

    @pytest.mark.asyncio
    async def test_delete_alert(self, store):
        await store.add_alert("Test", "contraband", None)
        alerts = await store.get_alerts()
        await store.delete_alert(alerts[0]["id"])
        assert await store.get_alerts() == []


# --- Door Schedule ---

class TestDoorSchedule:
    @pytest.mark.asyncio
    async def test_add_and_get(self, store):
        await store.add_schedule("DEV-1", "lock", 22, 0)
        schedules = await store.get_schedules()
        assert len(schedules) == 1
        assert schedules[0]["device_id"] == "DEV-1"
        assert schedules[0]["action"] == "lock"
        assert schedules[0]["hour"] == 22
        assert schedules[0]["minute"] == 0
        assert schedules[0]["days"] == "0,1,2,3,4,5,6"
        assert schedules[0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_add_with_custom_days(self, store):
        await store.add_schedule("DEV-1", "lock", 22, 0, "0,1,2,3,4")
        schedules = await store.get_schedules()
        assert schedules[0]["days"] == "0,1,2,3,4"

    @pytest.mark.asyncio
    async def test_delete_schedule(self, store):
        await store.add_schedule("DEV-1", "lock", 22, 0)
        schedules = await store.get_schedules()
        await store.delete_schedule(schedules[0]["id"])
        assert await store.get_schedules() == []

    @pytest.mark.asyncio
    async def test_update_schedule_enabled(self, store):
        await store.add_schedule("DEV-1", "lock", 22, 0)
        schedules = await store.get_schedules()
        await store.update_schedule(schedules[0]["id"], False)
        schedules = await store.get_schedules()
        assert schedules[0]["enabled"] is False

    @pytest.mark.asyncio
    async def test_schedules_ordered_by_time(self, store):
        await store.add_schedule("DEV-1", "unlock", 7, 0)
        await store.add_schedule("DEV-1", "lock", 22, 30)
        await store.add_schedule("DEV-1", "in_only", 20, 0)
        schedules = await store.get_schedules()
        assert schedules[0]["hour"] == 7
        assert schedules[1]["hour"] == 20
        assert schedules[2]["hour"] == 22
