"""Tests for the analytics computation logic in main.py."""

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


async def _seed_full(store):
    """Seed with a realistic set of events for Oni and Misha."""
    await store.upsert_device("DEV-1", "Cat Door", {"connected": True})
    await store.upsert_pet("RFID-001", "Oni", "2026-03-20T12:00:00Z", "DEV-1")
    await store.upsert_pet("RFID-002", "Misha", "2026-03-20T14:00:00Z", "DEV-1")

    events = [
        # Oni goes out (indoor motion = trigger 2)
        _make_event(1, ts="2026-03-20T08:00:00Z", trigger=2, classification=1, rfid_codes=["RFID-001"]),
        # Oni comes back (outdoor motion = trigger 3)
        _make_event(2, ts="2026-03-20T09:30:00Z", trigger=3, classification=1, rfid_codes=["RFID-001"]),
        # Oni goes out again
        _make_event(3, ts="2026-03-20T11:00:00Z", trigger=2, classification=1, rfid_codes=["RFID-001"]),
        # Oni comes back with contraband
        _make_event(4, ts="2026-03-20T12:00:00Z", trigger=3, classification=3, rfid_codes=["RFID-001"]),
        # Misha visits (outdoor motion, different RFID)
        _make_event(5, ts="2026-03-20T14:00:00Z", trigger=3, classification=1, rfid_codes=["RFID-002"]),
        # Oni clear event
        _make_event(6, ts="2026-03-20T16:00:00Z", trigger=3, classification=1, rfid_codes=["RFID-001"]),
    ]
    await store.upsert_many(events)


class TestBuildAnalytics:
    @pytest.mark.asyncio
    async def test_empty_store(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        analytics = await main.build_analytics()

        assert analytics["oni_status"]["status"] == "unknown"
        assert analytics["summary"]["total_events"] == 0
        assert analytics["contraband"]["days_since"] is None
        assert analytics["heatmap"] is not None
        assert len(analytics["heatmap"]) == 7

    @pytest.mark.asyncio
    async def test_oni_status_inside(self, store, monkeypatch):
        """Oni's last event is outdoor motion (trigger 3) = came inside."""
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        # Last Oni event is #6 trigger=3 (outdoor motion = came inside)
        assert analytics["oni_status"]["status"] == "inside"
        assert analytics["oni_status"]["direction"] == "entered"

    @pytest.mark.asyncio
    async def test_oni_status_outside(self, store, monkeypatch):
        """When Oni's last event is indoor motion (trigger 2) = went outside."""
        import main
        monkeypatch.setattr(main, "store", store)

        await store.upsert_device("DEV-1", "Cat Door", {"connected": True})
        await store.upsert_pet("RFID-001", "Oni", "2026-03-20T10:00:00Z", "DEV-1")
        await store.upsert(_make_event(1, ts="2026-03-20T10:00:00Z", trigger=2, classification=1, rfid_codes=["RFID-001"]))

        analytics = await main.build_analytics()
        assert analytics["oni_status"]["status"] == "outside"
        assert analytics["oni_status"]["direction"] == "left"

    @pytest.mark.asyncio
    async def test_pet_identification(self, store, monkeypatch):
        """Resident (more events) should be identified as Oni."""
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        # Oni has 5 events, Misha has 1 → Oni is resident
        assert analytics["pets"]["oni"]["label"] == "Oni"
        assert analytics["pets"]["misha"]["label"] == "Misha"
        assert analytics["pets"]["oni"]["code"] == "RFID-001"
        assert analytics["pets"]["misha"]["code"] == "RFID-002"

    @pytest.mark.asyncio
    async def test_contraband_tracking(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        assert analytics["contraband"]["last_timestamp"] is not None
        assert analytics["contraband"]["days_since"] is not None
        assert analytics["contraband"]["days_since"] >= 0
        assert isinstance(analytics["contraband"]["by_hour"], list)
        assert len(analytics["contraband"]["by_hour"]) == 24

    @pytest.mark.asyncio
    async def test_heatmap_structure(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        heatmap = analytics["heatmap"]
        assert len(heatmap) == 7  # 7 days
        for row in heatmap:
            assert len(row) == 24  # 24 hours

    @pytest.mark.asyncio
    async def test_trip_tracking(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        trips = (await main.build_analytics())["trips"]
        # Two trips: 08:00→09:30 and 11:00→12:00
        assert trips["total_trips"] == 2
        assert trips["avg_duration_minutes"] > 0
        assert trips["longest_duration_minutes"] >= trips["avg_duration_minutes"]

    @pytest.mark.asyncio
    async def test_badges(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        badges = analytics["badges"]
        assert isinstance(badges, list)
        # With contraband events, should have "hunter" badge
        badge_ids = [b["id"] for b in badges]
        assert "hunter" in badge_ids

    @pytest.mark.asyncio
    async def test_misha_visits(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        misha = (await main.build_analytics())["misha_visits"]
        assert misha["last_seen"] is not None

    @pytest.mark.asyncio
    async def test_moon_data(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)

        analytics = await main.build_analytics()
        moon = analytics["moon"]
        assert "today_phase" in moon
        assert "today_name" in moon
        assert "today_emoji" in moon
        assert 0 <= moon["today_phase"] <= 1
        assert 0 <= moon["today_illumination"] <= 100
        assert len(moon["phases_30d"]) == 30

    @pytest.mark.asyncio
    async def test_timeline(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        timeline = analytics["timeline"]
        assert isinstance(timeline, list)
        for item in timeline:
            assert "time" in item
            assert "position" in item
            assert 0 <= item["position"] <= 100
            assert "classification" in item

    @pytest.mark.asyncio
    async def test_records(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        records = (await main.build_analytics())["records"]
        assert records["busiest_day"] is not None
        assert records["busiest_day_count"] > 0
        assert records["total_trips"] == 2
        assert records["current_contraband_streak"] >= 0
        assert records["longest_contraband_streak"] >= 0

    @pytest.mark.asyncio
    async def test_comparison(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        comparison = (await main.build_analytics())["comparison"]
        assert "this_week" in comparison
        assert "last_week" in comparison
        assert "change_pct" in comparison
        assert len(comparison["this_week_daily"]) == 7
        assert len(comparison["last_week_daily"]) == 7

    @pytest.mark.asyncio
    async def test_health(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        health = (await main.build_analytics())["health"]
        assert isinstance(health["labels"], list)
        assert isinstance(health["values"], list)
        assert len(health["labels"]) == len(health["values"])
        assert "trend_pct" in health

    @pytest.mark.asyncio
    async def test_calendar(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        calendar = (await main.build_analytics())["calendar"]
        assert len(calendar) == 365
        for day in calendar:
            assert "date" in day
            assert "count" in day
            assert "weekday" in day
            assert 0 <= day["weekday"] <= 6

    @pytest.mark.asyncio
    async def test_device_stats(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        analytics = await main.build_analytics()
        device_stats = analytics["device_stats"]
        assert len(device_stats) == 1
        dev = device_stats[0]
        assert dev["device_id"] == "DEV-1"
        assert dev["events_total"] == 6
        assert len(dev["hourly_pattern"]) == 24
        assert len(dev["daily_activity"]["labels"]) == 30
        assert len(dev["daily_activity"]["values"]) == 30
        assert isinstance(dev["classification_breakdown"], dict)
        assert isinstance(dev["trigger_breakdown"], dict)


class TestBuildState:
    @pytest.mark.asyncio
    async def test_build_state_structure(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        async def _no_weather():
            return None
        monkeypatch.setattr(main, "_fetch_weather", _no_weather)
        await _seed_full(store)

        state = await main.build_state()
        assert "devices" in state
        assert "events" in state
        assert "pets" in state
        assert "charts" in state
        assert "analytics" in state
        assert "timezone" in state
        assert state["timezone"] == "Europe/Paris"

    @pytest.mark.asyncio
    async def test_build_state_events_serialization(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        async def _no_weather():
            return None
        monkeypatch.setattr(main, "_fetch_weather", _no_weather)
        await _seed_full(store)

        state = await main.build_state()
        for ev in state["events"]:
            assert "eventId" in ev
            assert "device" in ev
            assert "trigger" in ev
            assert "classification" in ev
            assert "pets" in ev
            assert isinstance(ev["pets"], list)

    @pytest.mark.asyncio
    async def test_chart_data_structure(self, store, monkeypatch):
        import main
        monkeypatch.setattr(main, "store", store)
        await _seed_full(store)

        charts = await main._build_chart_data()
        for period in ("daily", "weekly", "monthly"):
            assert period in charts
            assert "labels" in charts[period]
            assert "counts" in charts[period]
            assert len(charts[period]["labels"]) == len(charts[period]["counts"])
        assert "classification_totals" in charts
