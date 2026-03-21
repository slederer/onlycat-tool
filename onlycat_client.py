"""OnlyCat Cloud API client using Socket.IO."""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import socketio

from event_store import EventStore

logger = logging.getLogger(__name__)

CLASSIFICATION = {
    0: "Unknown",
    1: "Clear",
    2: "Suspicious",
    3: "Contraband",
    4: "Human Activity",
    10: "Remote Unlock",
}

TRIGGER_SOURCE = {
    0: "Manual",
    1: "Remote",
    2: "Indoor Motion",
    3: "Outdoor Motion",
}

GATEWAY_URL = "https://gateway.onlycat.com"
RECENT_EVENTS_LIMIT = 50


class OnlyCatClient:
    def __init__(self, token: str, on_update=None):
        self._token = token
        self._on_update = on_update
        self._sio = socketio.AsyncClient(reconnection=True, reconnection_delay=10)
        self._store = EventStore()
        self.state = {
            "devices": {},
            "events": [],  # recent events for the activity table
            "pets": {},
            "connected": False,
        }
        self._register_handlers()

    def _register_handlers(self):
        sio = self._sio

        @sio.event
        async def connect():
            logger.info("Connected to OnlyCat Cloud")
            self.state["connected"] = True
            await self._fetch_initial_data()

        @sio.event
        async def disconnect():
            logger.warning("Disconnected from OnlyCat Cloud")
            self.state["connected"] = False
            await self._notify()

        @sio.on("userUpdate")
        async def on_user_update(data):
            logger.info("User update: %s", data.get("id", "unknown"))

        @sio.on("deviceUpdate")
        async def on_device_update(data):
            device_id = data.get("deviceId")
            body = data.get("body", {})
            if device_id and device_id in self.state["devices"]:
                device = self.state["devices"][device_id]
                if "connectivity" in body:
                    device["connectivity"] = body["connectivity"]
                if "description" in body:
                    device["description"] = body["description"]
            await self._notify()

        @sio.on("deviceEventUpdate")
        async def on_device_event_update(data):
            device_id = data.get("deviceId")
            event_id = data.get("eventId")
            if device_id and event_id:
                try:
                    event = await sio.call("getEvent", {
                        "deviceId": device_id,
                        "eventId": event_id,
                    })
                    await self._process_event(event)
                except Exception:
                    logger.exception("Failed to fetch event %s/%s", device_id, event_id)

        @sio.on("eventUpdate")
        async def on_event_update(data):
            body = data.get("body", data)
            await self._process_event(body)

    async def _fetch_initial_data(self):
        """Fetch devices, events, and pets on initial connection."""
        try:
            devices_resp = await self._sio.call("getDevices", {"subscribe": True})
            devices = devices_resp if isinstance(devices_resp, list) else devices_resp.get("devices", [])

            for d in devices:
                device_id = d.get("deviceId")
                if not device_id:
                    continue

                device_detail = await self._sio.call("getDevice", {
                    "deviceId": device_id,
                    "subscribe": True,
                })
                self.state["devices"][device_id] = {
                    "deviceId": device_id,
                    "description": device_detail.get("description", device_id),
                    "connectivity": device_detail.get("connectivity", {}),
                }

                # Fetch RFID pets
                try:
                    rfid_codes = await self._sio.call(
                        "getLastSeenRfidCodesByDevice", {"deviceId": device_id}
                    )
                    if isinstance(rfid_codes, list):
                        for entry in rfid_codes:
                            code = entry.get("rfidCode")
                            if code:
                                label = code
                                try:
                                    profile = await self._sio.call(
                                        "getRfidProfile", {"rfidCode": code}
                                    )
                                    label = profile.get("label", code)
                                except Exception:
                                    pass
                                self.state["pets"][code] = {
                                    "rfid_code": code,
                                    "label": label,
                                    "last_seen": entry.get("timestamp"),
                                    "device_id": device_id,
                                }
                except Exception:
                    logger.exception("Failed to fetch RFID codes for %s", device_id)

                # Fetch recent events from API and persist
                try:
                    events_resp = await self._sio.call(
                        "getDeviceEvents", {"deviceId": device_id, "subscribe": True}
                    )
                    events = events_resp if isinstance(events_resp, list) else events_resp.get("events", [])
                    await self._store.upsert_many(events)
                except Exception:
                    logger.exception("Failed to fetch events for %s", device_id)

            # Load recent events from DB for the activity table
            self.state["events"] = await self._store.get_recent(RECENT_EVENTS_LIMIT)

            await self._notify()
            count = await self._store.count()
            logger.info(
                "Initial load: %d devices, %d total stored events, %d pets",
                len(self.state["devices"]),
                count,
                len(self.state["pets"]),
            )

        except Exception:
            logger.exception("Failed to fetch initial data")

    async def _process_event(self, event_data):
        """Process a single incoming event."""
        if not event_data:
            return

        # Persist to SQLite
        await self._store.upsert(event_data)

        # Update recent events list
        self.state["events"] = await self._store.get_recent(RECENT_EVENTS_LIMIT)

        # Resolve RFID if present
        rfid_codes = event_data.get("rfidCodes", [])
        for code in rfid_codes or []:
            if code not in self.state["pets"]:
                try:
                    profile = await self._sio.call("getRfidProfile", {"rfidCode": code})
                    self.state["pets"][code] = {
                        "rfid_code": code,
                        "label": profile.get("label", code),
                        "last_seen": event_data.get("timestamp"),
                        "device_id": event_data.get("deviceId"),
                    }
                except Exception:
                    pass
            else:
                self.state["pets"][code]["last_seen"] = event_data.get("timestamp")

        await self._notify()

    async def _notify(self):
        """Call the update callback if set."""
        if self._on_update:
            try:
                await self._on_update()
            except Exception:
                logger.exception("Update callback failed")

    async def start(self):
        """Connect to the OnlyCat Cloud gateway."""
        await self._store.open()
        await self._sio.connect(
            GATEWAY_URL,
            transports=["websocket"],
            headers={"platform": "home-assistant", "device": "onlycat-hass"},
            auth={"token": self._token},
        )
        await self._sio.wait()

    async def stop(self):
        """Disconnect from the gateway."""
        await self._sio.disconnect()
        await self._store.close()

    async def serialize_state(self):
        """Return JSON-serializable state for the dashboard."""
        events = []
        for ev in self.state["events"]:
            rfid_codes = ev.get("rfidCodes") or []
            pet_names = [
                self.state["pets"].get(c, {}).get("label", c) for c in rfid_codes
            ]
            events.append({
                "eventId": ev.get("eventId"),
                "deviceId": ev.get("deviceId"),
                "device": self.state["devices"]
                .get(ev.get("deviceId", ""), {})
                .get("description", ev.get("deviceId", "?")),
                "timestamp": ev.get("timestamp", ""),
                "trigger": TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
                "classification": CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown"),
                "pets": pet_names,
                "frameCount": ev.get("frameCount", 0),
            })

        devices = []
        for d in self.state["devices"].values():
            conn = d.get("connectivity", {})
            devices.append({
                "deviceId": d["deviceId"],
                "description": d.get("description", d["deviceId"]),
                "connected": conn.get("connected", False),
                "disconnectReason": conn.get("disconnectReason", ""),
            })

        pets = []
        for p in self.state["pets"].values():
            pets.append({
                "rfid_code": p["rfid_code"],
                "label": p.get("label", p["rfid_code"]),
                "last_seen": p.get("last_seen", ""),
                "device": self.state["devices"]
                .get(p.get("device_id", ""), {})
                .get("description", p.get("device_id", "?")),
            })

        charts = await self._build_chart_data()

        return {
            "devices": devices,
            "events": events,
            "pets": pets,
            "connected": self.state["connected"],
            "charts": charts,
        }

    async def _build_chart_data(self):
        """Aggregate events from DB into daily, weekly, and monthly buckets."""
        now = datetime.now(timezone.utc)

        # Pull last 30 days of events from SQLite
        cutoff = (now - timedelta(days=30)).isoformat()
        all_events = await self._store.get_since(cutoff)

        # Parse timestamps
        parsed = []
        for ev in all_events:
            ts = ev.get("timestamp")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            parsed.append((dt, ev))

        # --- Daily: hourly buckets for the last 24 hours ---
        daily_cutoff = now - timedelta(hours=24)
        daily_counts = defaultdict(int)
        daily_by_class = defaultdict(lambda: defaultdict(int))
        for dt, ev in parsed:
            if dt >= daily_cutoff:
                hour_label = dt.strftime("%H:00")
                daily_counts[hour_label] += 1
                cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
                daily_by_class[hour_label][cls] += 1

        daily_labels = []
        for i in range(24):
            h = (now - timedelta(hours=23 - i)).strftime("%H:00")
            daily_labels.append(h)

        # --- Weekly: daily buckets for the last 7 days ---
        weekly_cutoff = now - timedelta(days=7)
        weekly_counts = defaultdict(int)
        weekly_by_class = defaultdict(lambda: defaultdict(int))
        for dt, ev in parsed:
            if dt >= weekly_cutoff:
                day_label = dt.strftime("%a %m/%d")
                weekly_counts[day_label] += 1
                cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
                weekly_by_class[day_label][cls] += 1

        weekly_labels = []
        for i in range(7):
            d = (now - timedelta(days=6 - i)).strftime("%a %m/%d")
            weekly_labels.append(d)

        # --- Monthly: daily buckets for the last 30 days ---
        monthly_counts = defaultdict(int)
        monthly_by_class = defaultdict(lambda: defaultdict(int))
        for dt, ev in parsed:
            day_label = dt.strftime("%m/%d")
            monthly_counts[day_label] += 1
            cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
            monthly_by_class[day_label][cls] += 1

        monthly_labels = []
        for i in range(30):
            d = (now - timedelta(days=29 - i)).strftime("%m/%d")
            monthly_labels.append(d)

        # Classification breakdown (all stored events)
        class_totals = defaultdict(int)
        for _, ev in parsed:
            cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
            class_totals[cls] += 1

        return {
            "daily": {
                "labels": daily_labels,
                "counts": [daily_counts.get(l, 0) for l in daily_labels],
                "by_class": {l: dict(daily_by_class.get(l, {})) for l in daily_labels},
            },
            "weekly": {
                "labels": weekly_labels,
                "counts": [weekly_counts.get(l, 0) for l in weekly_labels],
                "by_class": {l: dict(weekly_by_class.get(l, {})) for l in weekly_labels},
            },
            "monthly": {
                "labels": monthly_labels,
                "counts": [monthly_counts.get(l, 0) for l in monthly_labels],
                "by_class": {l: dict(monthly_by_class.get(l, {})) for l in monthly_labels},
            },
            "classification_totals": dict(class_totals),
        }
