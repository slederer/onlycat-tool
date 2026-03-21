"""OnlyCat Dashboard — cat activity monitor with daily sync."""

import asyncio
import json
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from event_store import EventStore
from sync import run_sync

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "24"))

CLASSIFICATION = {
    0: "Unknown", 1: "Clear", 2: "Suspicious", 3: "Contraband",
    4: "Human Activity", 10: "Remote Unlock",
}
TRIGGER_SOURCE = {
    0: "Manual", 1: "Remote", 2: "Indoor Motion", 3: "Outdoor Motion",
}
RECENT_EVENTS_LIMIT = 50

# Global state
store = EventStore()
browser_clients: set[WebSocket] = set()
sync_lock = asyncio.Lock()


async def build_state() -> dict:
    """Build dashboard state from the database."""
    devices_raw = await store.get_devices()
    pets_raw = await store.get_pets()
    events_raw = await store.get_recent(RECENT_EVENTS_LIMIT)

    # Index for lookups
    device_map = {d["device_id"]: d for d in devices_raw}
    pet_map = {p["rfid_code"]: p for p in pets_raw}

    events = []
    for ev in events_raw:
        rfid_codes = ev.get("rfidCodes") or []
        pet_names = [pet_map.get(c, {}).get("label", c) for c in rfid_codes]
        events.append({
            "eventId": ev.get("eventId"),
            "deviceId": ev.get("deviceId"),
            "device": device_map.get(ev.get("deviceId", ""), {}).get("description", ev.get("deviceId", "?")),
            "timestamp": ev.get("timestamp", ""),
            "trigger": TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
            "classification": CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown"),
            "pets": pet_names,
            "frameCount": ev.get("frameCount", 0),
        })

    devices = []
    for d in devices_raw:
        conn = d.get("connectivity", {})
        devices.append({
            "deviceId": d["device_id"],
            "description": d.get("description", d["device_id"]),
            "connected": conn.get("connected", False),
            "disconnectReason": conn.get("disconnectReason", ""),
        })

    pets = []
    for p in pets_raw:
        pets.append({
            "rfid_code": p["rfid_code"],
            "label": p.get("label", p["rfid_code"]),
            "last_seen": p.get("last_seen", ""),
            "device": device_map.get(p.get("device_id", ""), {}).get("description", p.get("device_id", "?")),
        })

    charts = await _build_chart_data()
    last_sync = await store.get_meta("last_sync")

    return {
        "devices": devices,
        "events": events,
        "pets": pets,
        "connected": True,
        "charts": charts,
        "last_sync": last_sync,
    }


async def _build_chart_data():
    """Aggregate events from DB into daily, weekly, and monthly buckets."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=30)).isoformat()
    all_events = await store.get_since(cutoff)

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

    # Daily: hourly buckets for the last 24 hours
    daily_cutoff = now - timedelta(hours=24)
    daily_counts: dict[str, int] = defaultdict(int)
    daily_by_class: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for dt, ev in parsed:
        if dt >= daily_cutoff:
            hour_label = dt.strftime("%H:00")
            daily_counts[hour_label] += 1
            cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
            daily_by_class[hour_label][cls] += 1

    daily_labels = [(now - timedelta(hours=23 - i)).strftime("%H:00") for i in range(24)]

    # Weekly: daily buckets for the last 7 days
    weekly_cutoff = now - timedelta(days=7)
    weekly_counts: dict[str, int] = defaultdict(int)
    weekly_by_class: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for dt, ev in parsed:
        if dt >= weekly_cutoff:
            day_label = dt.strftime("%a %m/%d")
            weekly_counts[day_label] += 1
            cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
            weekly_by_class[day_label][cls] += 1

    weekly_labels = [(now - timedelta(days=6 - i)).strftime("%a %m/%d") for i in range(7)]

    # Monthly: daily buckets for the last 30 days
    monthly_counts: dict[str, int] = defaultdict(int)
    monthly_by_class: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for dt, ev in parsed:
        day_label = dt.strftime("%m/%d")
        monthly_counts[day_label] += 1
        cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
        monthly_by_class[day_label][cls] += 1

    monthly_labels = [(now - timedelta(days=29 - i)).strftime("%m/%d") for i in range(30)]

    class_totals: dict[str, int] = defaultdict(int)
    for _, ev in parsed:
        cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
        class_totals[cls] += 1

    return {
        "daily": {
            "labels": daily_labels,
            "counts": [daily_counts.get(label, 0) for label in daily_labels],
            "by_class": {label: dict(daily_by_class.get(label, {})) for label in daily_labels},
        },
        "weekly": {
            "labels": weekly_labels,
            "counts": [weekly_counts.get(label, 0) for label in weekly_labels],
            "by_class": {label: dict(weekly_by_class.get(label, {})) for label in weekly_labels},
        },
        "monthly": {
            "labels": monthly_labels,
            "counts": [monthly_counts.get(label, 0) for label in monthly_labels],
            "by_class": {label: dict(monthly_by_class.get(label, {})) for label in monthly_labels},
        },
        "classification_totals": dict(class_totals),
    }


async def broadcast_update():
    """Push state to all connected browsers."""
    payload = json.dumps(await build_state())
    for ws in list(browser_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            browser_clients.discard(ws)


async def do_sync():
    """Run a sync if token is available."""
    token = os.environ.get("ONLYCAT_TOKEN")
    if not token:
        logger.error("ONLYCAT_TOKEN not set — skipping sync")
        return {"error": "ONLYCAT_TOKEN not set"}
    async with sync_lock:
        result = await run_sync(token, store)
    await broadcast_update()
    return result


async def sync_loop():
    """Background task: sync on startup, then every SYNC_INTERVAL_HOURS."""
    await do_sync()
    while True:
        await asyncio.sleep(SYNC_INTERVAL_HOURS * 3600)
        await do_sync()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.open()
    task = asyncio.create_task(sync_loop())
    yield
    task.cancel()
    await store.close()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    state = await build_state()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "initial_state": state},
    )


@app.post("/api/sync")
async def trigger_sync():
    """Manually trigger a data sync."""
    if sync_lock.locked():
        return JSONResponse({"status": "already running"}, status_code=409)
    result = await do_sync()
    return result


@app.get("/api/status")
async def status():
    last_sync = await store.get_meta("last_sync")
    event_count = await store.count()
    return {"last_sync": last_sync, "event_count": event_count}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    browser_clients.add(ws)
    await ws.send_text(json.dumps(await build_state()))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        browser_clients.discard(ws)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
