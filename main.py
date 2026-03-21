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


async def build_analytics() -> dict:
    """Compute comprehensive analytics from all stored events."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday
    month_start = today_start.replace(day=1)
    thirty_days_ago = now - timedelta(days=30)

    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    devices_raw = await store.get_devices()

    pet_map = {p["rfid_code"]: p for p in pets_raw}

    # Parse all events with datetime objects
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

    # Sort chronologically (oldest first) for status tracking
    parsed_chrono = sorted(parsed, key=lambda x: x[0])

    # Identify pets: resident (Oni) has more events, visitor (Misha) has fewer
    pet_event_counts: dict[str, int] = defaultdict(int)
    for _, ev in parsed:
        for code in (ev.get("rfidCodes") or []):
            pet_event_counts[code] += 1

    # Sort by count descending - most events = resident
    sorted_pets = sorted(pet_event_counts.items(), key=lambda x: x[1], reverse=True)
    resident_code = sorted_pets[0][0] if sorted_pets else None
    visitor_code = sorted_pets[1][0] if len(sorted_pets) > 1 else None

    resident_label = pet_map.get(resident_code, {}).get("label", "Oni") if resident_code else "Oni"
    visitor_label = pet_map.get(visitor_code, {}).get("label", "Misha") if visitor_code else "Misha"

    # --- Oni Status ---
    oni_status = "unknown"
    oni_last_event_ts = None
    oni_last_direction = None
    for dt, ev in reversed(parsed_chrono):
        codes = ev.get("rfidCodes") or []
        trigger = ev.get("eventTriggerSource")
        if resident_code and resident_code in codes and trigger in (2, 3):
            oni_last_event_ts = dt.isoformat()
            if trigger == 2:  # Indoor motion = leaving
                oni_status = "outside"
                oni_last_direction = "left"
            elif trigger == 3:  # Outdoor motion = coming in
                oni_status = "inside"
                oni_last_direction = "entered"
            break

    # --- Summary stats ---
    events_today = sum(1 for dt, _ in parsed if dt >= today_start)
    total_events = len(parsed)
    # Average per day over 30 days
    events_30d = sum(1 for dt, _ in parsed if dt >= thirty_days_ago)
    avg_per_day = round(events_30d / 30, 1) if events_30d else 0

    # --- Contraband tracking ---
    contraband_events = [(dt, ev) for dt, ev in parsed if ev.get("eventClassification") == 3]
    last_contraband_ts = contraband_events[0][0].isoformat() if contraband_events else None
    days_since_contraband = (now - contraband_events[0][0]).days if contraband_events else None
    contraband_this_week = sum(1 for dt, _ in contraband_events if dt >= week_start)
    contraband_this_month = sum(1 for dt, _ in contraband_events if dt >= month_start)
    contraband_by_hour = [0] * 24
    for dt, _ in contraband_events:
        if dt >= thirty_days_ago:
            contraband_by_hour[dt.hour] += 1

    # --- Per-pet stats ---
    def compute_pet_stats(rfid_code):
        if not rfid_code:
            return {
                "events_today": 0, "events_week": 0, "events_month": 0,
                "hourly_pattern": [0] * 24, "most_active_hour": None,
                "classification_breakdown": {},
            }
        pet_events = [(dt, ev) for dt, ev in parsed if rfid_code in (ev.get("rfidCodes") or [])]
        today_count = sum(1 for dt, _ in pet_events if dt >= today_start)
        week_count = sum(1 for dt, _ in pet_events if dt >= week_start)
        month_count = sum(1 for dt, _ in pet_events if dt >= month_start)

        hourly = [0] * 24
        for dt, _ in pet_events:
            if dt >= thirty_days_ago:
                hourly[dt.hour] += 1
        most_active = hourly.index(max(hourly)) if max(hourly) > 0 else None

        class_breakdown: dict[str, int] = defaultdict(int)
        for _, ev in pet_events:
            cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
            class_breakdown[cls] += 1

        return {
            "events_today": today_count,
            "events_week": week_count,
            "events_month": month_count,
            "hourly_pattern": hourly,
            "most_active_hour": most_active,
            "classification_breakdown": dict(class_breakdown),
        }

    oni_stats = compute_pet_stats(resident_code)
    misha_stats = compute_pet_stats(visitor_code)

    # --- Heatmap data (7x24, day-of-week x hour) from last 30 days ---
    heatmap = [[0] * 24 for _ in range(7)]
    for dt, _ in parsed:
        if dt >= thirty_days_ago:
            heatmap[dt.weekday()][dt.hour] += 1

    # --- Misha visits ---
    misha_last_seen = None
    if visitor_code:
        for dt, ev in parsed:  # parsed is newest first
            if visitor_code in (ev.get("rfidCodes") or []):
                misha_last_seen = dt.isoformat()
                break

    misha_visits_week = misha_stats["events_week"]
    misha_visits_month = misha_stats["events_month"]
    misha_usual_time = None
    if misha_stats["most_active_hour"] is not None:
        h = misha_stats["most_active_hour"]
        misha_usual_time = f"{h:02d}:00"

    # --- Device uptime ---
    device_connected = any(
        d.get("connectivity", {}).get("connected", False) for d in devices_raw
    )

    return {
        "oni_status": {
            "status": oni_status,
            "last_event": oni_last_event_ts,
            "direction": oni_last_direction,
        },
        "summary": {
            "events_today": events_today,
            "avg_per_day": avg_per_day,
            "total_events": total_events,
        },
        "contraband": {
            "days_since": days_since_contraband,
            "last_timestamp": last_contraband_ts,
            "this_week": contraband_this_week,
            "this_month": contraband_this_month,
            "by_hour": contraband_by_hour,
        },
        "pets": {
            "oni": {
                "label": resident_label,
                "code": resident_code,
                **oni_stats,
            },
            "misha": {
                "label": visitor_label,
                "code": visitor_code,
                **misha_stats,
            },
        },
        "heatmap": heatmap,
        "misha_visits": {
            "last_seen": misha_last_seen,
            "visits_week": misha_visits_week,
            "visits_month": misha_visits_month,
            "usual_time": misha_usual_time,
        },
        "device_connected": device_connected,
    }


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
    analytics = await build_analytics()

    return {
        "devices": devices,
        "events": events,
        "pets": pets,
        "connected": True,
        "charts": charts,
        "last_sync": last_sync,
        "analytics": analytics,
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
