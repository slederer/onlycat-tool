"""Tests for FastAPI endpoints using the test client."""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from event_store import EventStore


@pytest_asyncio.fixture
async def store(tmp_path):
    s = EventStore(tmp_path / "test.db")
    await s.open()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def client(store, monkeypatch):
    # Patch the global store before importing the app
    import main
    monkeypatch.setattr(main, "store", store)
    # Disable the sync loop by patching do_sync to no-op
    monkeypatch.setattr(main, "do_sync", lambda: None)
    # Use test client
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_event(event_id, device_id="DEV-1", ts="2026-03-20T10:00:00Z",
                trigger=3, classification=1, rfid_codes=None):
    return {
        "eventId": event_id,
        "deviceId": device_id,
        "timestamp": ts,
        "eventTriggerSource": trigger,
        "eventClassification": classification,
        "rfidCodes": rfid_codes or [],
        "frameCount": 5,
    }


async def _seed_data(store):
    """Seed the store with basic test data."""
    await store.upsert_device("DEV-1", "Cat Door", {"connected": True})
    await store.upsert_pet("RFID-001", "Oni", "2026-03-20T10:00:00Z", "DEV-1")
    await store.upsert_pet("RFID-002", "Misha", "2026-03-19T15:00:00Z", "DEV-1")
    events = [
        _make_event(1, ts="2026-03-20T08:00:00Z", trigger=2, classification=1, rfid_codes=["RFID-001"]),
        _make_event(2, ts="2026-03-20T09:00:00Z", trigger=3, classification=1, rfid_codes=["RFID-001"]),
        _make_event(3, ts="2026-03-20T10:00:00Z", trigger=3, classification=3, rfid_codes=["RFID-001"]),
        _make_event(4, ts="2026-03-19T15:00:00Z", trigger=3, classification=1, rfid_codes=["RFID-002"]),
    ]
    await store.upsert_many(events)


# --- API Status ---

class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status(self, client, store):
        await store.set_meta("last_sync", "2026-03-20T10:00:00Z")
        await store.upsert(_make_event(1))
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_sync"] == "2026-03-20T10:00:00Z"
        assert data["event_count"] == 1

    @pytest.mark.asyncio
    async def test_status_empty(self, client):
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_sync"] is None
        assert data["event_count"] == 0


# --- CSV Export ---

class TestExportEndpoint:
    @pytest.mark.asyncio
    async def test_export_csv(self, client, store):
        await _seed_data(store)
        resp = await client.get("/api/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        lines = resp.text.strip().split("\n")
        assert len(lines) == 5  # header + 4 events
        assert "Event ID" in lines[0]

    @pytest.mark.asyncio
    async def test_export_csv_empty(self, client):
        resp = await client.get("/api/export")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 1  # header only


# --- Annotations API ---

class TestAnnotationsAPI:
    @pytest.mark.asyncio
    async def test_add_annotation(self, client, store):
        resp = await client.post("/api/annotations", json={"event_id": 100, "note": "test note"})
        assert resp.status_code == 200
        annotations = await store.get_annotations(100)
        assert len(annotations) == 1
        assert annotations[0]["note"] == "test note"

    @pytest.mark.asyncio
    async def test_list_annotations(self, client, store):
        await store.add_annotation(1, "note 1")
        await store.add_annotation(2, "note 2")
        resp = await client.get("/api/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_delete_annotation(self, client, store):
        await store.add_annotation(100, "to delete")
        annotations = await store.get_all_annotations()
        resp = await client.delete(f"/api/annotations/{annotations[0]['id']}")
        assert resp.status_code == 200
        assert await store.get_all_annotations() == []


# --- Alerts API ---

class TestAlertsAPI:
    @pytest.mark.asyncio
    async def test_add_alert(self, client, store):
        resp = await client.post("/api/alerts", json={
            "name": "Test Alert", "alert_type": "contraband", "threshold": None
        })
        assert resp.status_code == 200
        alerts = await store.get_alerts()
        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_list_alerts(self, client, store):
        await store.add_alert("A1", "contraband", None)
        await store.add_alert("A2", "outside_too_long", 120)
        resp = await client.get("/api/alerts")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_update_alert(self, client, store):
        await store.add_alert("Test", "contraband", None)
        alerts = await store.get_alerts()
        resp = await client.put(f"/api/alerts/{alerts[0]['id']}", json={"enabled": False})
        assert resp.status_code == 200
        alerts = await store.get_alerts()
        assert alerts[0]["enabled"] is False

    @pytest.mark.asyncio
    async def test_delete_alert(self, client, store):
        await store.add_alert("Test", "contraband", None)
        alerts = await store.get_alerts()
        resp = await client.delete(f"/api/alerts/{alerts[0]['id']}")
        assert resp.status_code == 200
        assert await store.get_alerts() == []


# --- Schedules API ---

class TestSchedulesAPI:
    @pytest.mark.asyncio
    async def test_add_schedule(self, client, store):
        resp = await client.post("/api/schedules", json={
            "device_id": "DEV-1", "action": "lock", "hour": 22, "minute": 0
        })
        assert resp.status_code == 200
        schedules = await store.get_schedules()
        assert len(schedules) == 1

    @pytest.mark.asyncio
    async def test_list_schedules(self, client, store):
        await store.add_schedule("DEV-1", "lock", 22, 0)
        await store.add_schedule("DEV-1", "unlock", 7, 0)
        resp = await client.get("/api/schedules")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_delete_schedule(self, client, store):
        await store.add_schedule("DEV-1", "lock", 22, 0)
        schedules = await store.get_schedules()
        resp = await client.delete(f"/api/schedules/{schedules[0]['id']}")
        assert resp.status_code == 200
        assert await store.get_schedules() == []


# --- Diary ---

class TestDiaryEndpoint:
    @pytest.mark.asyncio
    async def test_diary_no_api_key(self, client, monkeypatch):
        import main
        monkeypatch.setattr(main, "ANTHROPIC_API_KEY", None)
        resp = await client.get("/api/diary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diary"] is None
        assert "ANTHROPIC_API_KEY" in data.get("error", "")
