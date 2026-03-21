"""Sync data from OnlyCat Cloud API into the local database."""

import asyncio
import logging
from datetime import datetime, timezone

import socketio

from event_store import EventStore

logger = logging.getLogger(__name__)

GATEWAY_URL = "https://gateway.onlycat.com"


async def run_sync(token: str, store: EventStore) -> dict:
    """Connect to OnlyCat, fetch all devices/pets/events, store in DB, disconnect.

    Returns a summary dict with counts.
    """
    sio = socketio.AsyncClient(reconnection=False)
    connected = asyncio.Event()
    summary = {"devices": 0, "pets": 0, "events": 0, "error": None}

    @sio.event
    async def connect():
        connected.set()

    try:
        await sio.connect(
            GATEWAY_URL,
            transports=["websocket"],
            headers={"platform": "home-assistant", "device": "onlycat-hass"},
            auth={"token": token},
        )
        await asyncio.wait_for(connected.wait(), timeout=30)
    except Exception as exc:
        summary["error"] = f"Connection failed: {exc}"
        logger.error("Sync connection failed: %s", exc)
        return summary

    try:
        # Fetch devices
        devices_resp = await sio.call("getDevices", {"subscribe": False})
        devices = devices_resp if isinstance(devices_resp, list) else devices_resp.get("devices", [])

        for d in devices:
            device_id = d.get("deviceId")
            if not device_id:
                continue

            device_detail = await sio.call("getDevice", {
                "deviceId": device_id,
                "subscribe": False,
            })
            description = device_detail.get("description", device_id)
            connectivity = device_detail.get("connectivity", {})
            await store.upsert_device(device_id, description, connectivity)
            summary["devices"] += 1

            # Fetch RFID pets
            try:
                rfid_codes = await sio.call(
                    "getLastSeenRfidCodesByDevice", {"deviceId": device_id}
                )
                if isinstance(rfid_codes, list):
                    for entry in rfid_codes:
                        code = entry.get("rfidCode")
                        if not code:
                            continue
                        label = code
                        try:
                            profile = await sio.call("getRfidProfile", {"rfidCode": code})
                            label = profile.get("label", code)
                        except Exception:
                            pass
                        await store.upsert_pet(
                            code, label, entry.get("timestamp", ""), device_id
                        )
                        summary["pets"] += 1
            except Exception:
                logger.exception("Failed to fetch RFID codes for %s", device_id)

            # Fetch events
            try:
                events_resp = await sio.call(
                    "getDeviceEvents", {"deviceId": device_id, "subscribe": False}
                )
                events = events_resp if isinstance(events_resp, list) else events_resp.get("events", [])
                await store.upsert_many(events)
                summary["events"] += len(events)
            except Exception:
                logger.exception("Failed to fetch events for %s", device_id)

        # Record sync time
        await store.set_meta("last_sync", datetime.now(timezone.utc).isoformat())

        logger.info(
            "Sync complete: %d devices, %d pets, %d events",
            summary["devices"], summary["pets"], summary["events"],
        )

    except Exception as exc:
        summary["error"] = str(exc)
        logger.exception("Sync failed")
    finally:
        await sio.disconnect()

    return summary
