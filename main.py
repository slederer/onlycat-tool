"""OnlyCat Dashboard — cat activity monitor with daily sync."""

import asyncio
import csv
import io
import json
import logging
import math
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from commands import set_transit_policy
from event_store import EventStore
from sync import run_sync

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "24"))
LATITUDE = os.environ.get("LATITUDE", "48.8631")
LONGITUDE = os.environ.get("LONGITUDE", "2.3839")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Paris"))

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
    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday
    month_start = today_start.replace(day=1)
    thirty_days_ago = now - timedelta(days=30)

    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    devices_raw = await store.get_devices()

    pet_map = {p["rfid_code"]: p for p in pets_raw}

    # Parse all events with datetime objects (converted to local timezone)
    parsed = []
    for ev in all_events:
        ts = ev.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
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

    # --- Trip tracking ---
    oni_events_chrono = [
        (dt, ev) for dt, ev in parsed_chrono
        if resident_code and resident_code in (ev.get("rfidCodes") or [])
    ]
    trips: list[dict] = []
    trip_start = None
    for dt, ev in oni_events_chrono:
        trigger = ev.get("eventTriggerSource")
        if trigger == 2:  # Indoor motion = leaving
            trip_start = dt
        elif trigger == 3 and trip_start:  # Outdoor motion = returning
            duration = (dt - trip_start).total_seconds() / 60
            if 0 < duration < 24 * 60:  # Sanity: between 0 and 24h
                trips.append({
                    "left_at": trip_start.isoformat(),
                    "returned_at": dt.isoformat(),
                    "duration_minutes": round(duration),
                })
            trip_start = None

    # Current trip (if Oni is outside)
    current_trip_start = None
    if oni_status == "outside" and trip_start:
        current_trip_start = trip_start.isoformat()

    avg_trip_minutes = round(sum(t["duration_minutes"] for t in trips) / len(trips)) if trips else 0
    longest_trip_minutes = max((t["duration_minutes"] for t in trips), default=0)
    trips_today = [t for t in trips if datetime.fromisoformat(t["returned_at"]).replace(tzinfo=timezone.utc) >= today_start]
    time_outside_today = sum(t["duration_minutes"] for t in trips_today)
    total_trips = len(trips)

    # --- Records & milestones ---
    events_by_day: dict[str, int] = defaultdict(int)
    for dt, _ in parsed:
        events_by_day[dt.strftime("%Y-%m-%d")] += 1
    busiest_day = max(events_by_day, key=events_by_day.get) if events_by_day else None
    busiest_day_count = events_by_day.get(busiest_day, 0) if busiest_day else 0

    events_by_hour_slot: dict[str, int] = defaultdict(int)
    for dt, _ in parsed:
        events_by_hour_slot[dt.strftime("%Y-%m-%d %H:00")] += 1
    busiest_hour_count = max(events_by_hour_slot.values(), default=0)

    # Contraband-free streak (current)
    contraband_dates = {dt.date() for dt, ev in parsed if ev.get("eventClassification") == 3}
    current_streak = 0
    check_date = now.date()
    while check_date not in contraband_dates and current_streak < 999:
        current_streak += 1
        check_date -= timedelta(days=1)

    # Longest contraband-free streak
    all_dates = sorted({dt.date() for dt, _ in parsed})
    longest_streak = 0
    streak = 0
    for d in all_dates:
        if d not in contraband_dates:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0

    # --- Moon phases (last 30 days) ---
    def moon_phase(dt_val):
        ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
        days_since = (dt_val - ref).total_seconds() / 86400
        return (days_since % 29.53059) / 29.53059

    def phase_name(p):
        if p < 0.0625 or p >= 0.9375:
            return "New Moon"
        if p < 0.1875:
            return "Waxing Crescent"
        if p < 0.3125:
            return "First Quarter"
        if p < 0.4375:
            return "Waxing Gibbous"
        if p < 0.5625:
            return "Full Moon"
        if p < 0.6875:
            return "Waning Gibbous"
        if p < 0.8125:
            return "Last Quarter"
        return "Waning Crescent"

    def phase_emoji(p):
        if p < 0.0625 or p >= 0.9375:
            return "\U0001F311"
        if p < 0.1875:
            return "\U0001F312"
        if p < 0.3125:
            return "\U0001F313"
        if p < 0.4375:
            return "\U0001F314"
        if p < 0.5625:
            return "\U0001F315"
        if p < 0.6875:
            return "\U0001F316"
        if p < 0.8125:
            return "\U0001F317"
        return "\U0001F318"

    moon_data = []
    for i in range(30):
        d = now - timedelta(days=29 - i)
        p = moon_phase(d)
        moon_data.append({
            "date": d.strftime("%m/%d"),
            "phase": round(p, 3),
            "name": phase_name(p),
            "emoji": phase_emoji(p),
            "illumination": round(abs(1 - 2 * abs(p - 0.5)) * 100),
        })

    # Moon vs activity correlation
    full_moon_events = sum(1 for dt, _ in parsed if dt >= thirty_days_ago and 0.4 <= moon_phase(dt) <= 0.6)
    new_moon_events = sum(1 for dt, _ in parsed if dt >= thirty_days_ago and (moon_phase(dt) < 0.1 or moon_phase(dt) > 0.9))
    today_phase = moon_phase(now)

    # --- Prediction ---
    predicted_return = None
    if oni_status == "outside" and trip_start:
        dep_hour = trip_start.hour
        similar = [t for t in trips
                   if datetime.fromisoformat(t["left_at"]).replace(tzinfo=timezone.utc).hour == dep_hour]
        if similar:
            avg_dur = sum(t["duration_minutes"] for t in similar) / len(similar)
            predicted_return = (trip_start + timedelta(minutes=avg_dur)).isoformat()

    # --- Badges ---
    badges = []
    if total_events >= 50:
        badges.append({"id": "half_century", "name": "Half Century", "icon": "\u2B50", "desc": "50+ events recorded"})
    if total_events >= 100:
        badges.append({"id": "century", "name": "Century", "icon": "\U0001F4AF", "desc": "100+ events recorded"})
    if total_events >= 500:
        badges.append({"id": "veteran", "name": "Veteran", "icon": "\U0001F396\uFE0F", "desc": "500+ events recorded"})
    if total_events >= 1000:
        badges.append({"id": "marathon", "name": "Marathon", "icon": "\U0001F3C3", "desc": "1000+ events recorded"})
    if current_streak >= 7:
        badges.append({"id": "clean_week", "name": "Clean Week", "icon": "\u2728", "desc": "7+ day contraband-free streak"})
    if current_streak >= 30:
        badges.append({"id": "spotless", "name": "Spotless", "icon": "\U0001F3C6", "desc": "30+ day contraband-free streak"})
    if longest_trip_minutes >= 120:
        badges.append({"id": "explorer", "name": "Explorer", "icon": "\U0001F30D", "desc": "Trip over 2 hours"})
    if longest_trip_minutes >= 360:
        badges.append({"id": "wanderer", "name": "Wanderer", "icon": "\U0001F6E4\uFE0F", "desc": "Trip over 6 hours"})
    early_events = sum(1 for dt, _ in parsed if dt.hour < 6)
    late_events = sum(1 for dt, _ in parsed if dt.hour >= 23)
    if early_events > 0:
        badges.append({"id": "early_bird", "name": "Early Bird", "icon": "\U0001F305", "desc": "Activity before 6am"})
    if late_events > 0:
        badges.append({"id": "night_owl", "name": "Night Owl", "icon": "\U0001F989", "desc": "Activity after 11pm"})
    if misha_visits_month >= 10:
        badges.append({"id": "popular", "name": "Popular Spot", "icon": "\U0001F3E0", "desc": "10+ Misha visits in a month"})
    if total_trips >= 50:
        badges.append({"id": "frequent", "name": "Frequent Flyer", "icon": "\u2708\uFE0F", "desc": "50+ trips"})
    if total_trips >= 200:
        badges.append({"id": "globetrotter", "name": "Globetrotter", "icon": "\U0001F30E", "desc": "200+ trips"})
    if busiest_day_count >= 20:
        badges.append({"id": "hyperactive", "name": "Hyperactive", "icon": "\u26A1", "desc": "20+ events in one day"})
    if contraband_events:
        badges.append({"id": "hunter", "name": "Hunter", "icon": "\U0001F43E", "desc": "At least one contraband event"})

    # --- Historical comparison: this week vs last week ---
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start
    events_last_week = sum(1 for dt, _ in parsed if last_week_start <= dt < last_week_end)
    events_this_week = sum(1 for dt, _ in parsed if dt >= week_start)
    contraband_last_week = sum(1 for dt, ev in parsed if last_week_start <= dt < last_week_end and ev.get("eventClassification") == 3)
    this_week_daily = [0] * 7
    last_week_daily = [0] * 7
    for dt, _ in parsed:
        if dt >= week_start:
            this_week_daily[dt.weekday()] += 1
        elif dt >= last_week_start:
            last_week_daily[dt.weekday()] += 1

    # --- Activity calendar (365 days) ---
    year_ago = now - timedelta(days=365)
    calendar_data = {}
    for dt, _ in parsed:
        if dt >= year_ago:
            day_key = dt.strftime("%Y-%m-%d")
            calendar_data[day_key] = calendar_data.get(day_key, 0) + 1
    calendar_days = []
    for i in range(365):
        d = (now - timedelta(days=364 - i))
        key = d.strftime("%Y-%m-%d")
        calendar_days.append({"date": key, "count": calendar_data.get(key, 0), "weekday": d.weekday()})

    # --- Health trends: weekly aggregates ---
    from collections import OrderedDict
    health_weeks = OrderedDict()
    for dt, _ in parsed:
        week_key = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        health_weeks[week_key] = health_weeks.get(week_key, 0) + 1
    health_labels = list(health_weeks.keys())[-12:]
    health_values = [health_weeks[k] for k in health_labels]
    recent_avg = sum(health_values[-4:]) / max(len(health_values[-4:]), 1)
    older_avg = sum(health_values[-8:-4]) / max(len(health_values[-8:-4]), 1) if len(health_values) >= 8 else recent_avg
    trend_pct = round((recent_avg - older_avg) / max(older_avg, 1) * 100) if older_avg else 0

    # --- Today's timeline ---
    timeline = []
    for dt, ev in parsed:
        if dt >= today_start:
            rfid_codes = ev.get("rfidCodes") or []
            pet_names = [pet_map.get(c, {}).get("label", c) for c in rfid_codes]
            minutes_since_midnight = dt.hour * 60 + dt.minute
            timeline.append({
                "time": dt.strftime("%H:%M"),
                "timestamp": dt.isoformat(),
                "position": round(minutes_since_midnight / 1440 * 100, 1),
                "classification": CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown"),
                "trigger": TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
                "pets": pet_names,
            })
    timeline.sort(key=lambda x: x["timestamp"])

    # --- Weather (cached) ---
    weather = await _fetch_weather()

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
        "trips": {
            "recent": trips[-10:][::-1],  # Last 10 trips, newest first
            "current_trip_start": current_trip_start,
            "avg_duration_minutes": avg_trip_minutes,
            "longest_duration_minutes": longest_trip_minutes,
            "trips_today": len(trips_today),
            "time_outside_today_minutes": time_outside_today,
            "total_trips": total_trips,
        },
        "records": {
            "busiest_day": busiest_day,
            "busiest_day_count": busiest_day_count,
            "busiest_hour_count": busiest_hour_count,
            "longest_trip_minutes": longest_trip_minutes,
            "current_contraband_streak": current_streak,
            "longest_contraband_streak": longest_streak,
            "total_trips": total_trips,
        },
        "moon": {
            "today_phase": round(today_phase, 3),
            "today_name": phase_name(today_phase),
            "today_emoji": phase_emoji(today_phase),
            "today_illumination": round(abs(1 - 2 * abs(today_phase - 0.5)) * 100),
            "full_moon_events_30d": full_moon_events,
            "new_moon_events_30d": new_moon_events,
            "phases_30d": moon_data,
        },
        "device_stats": _build_device_stats(devices_raw, parsed, parsed_chrono, today_start, week_start, thirty_days_ago),
        "weather": weather,
        "prediction": {
            "estimated_return": predicted_return,
        },
        "badges": badges,
        "timeline": timeline,
        "comparison": {
            "this_week": events_this_week,
            "last_week": events_last_week,
            "change_pct": round((events_this_week - events_last_week) / max(events_last_week, 1) * 100),
            "contraband_this_week": contraband_this_week,
            "contraband_last_week": contraband_last_week,
            "this_week_daily": this_week_daily,
            "last_week_daily": last_week_daily,
        },
        "calendar": calendar_days,
        "health": {
            "labels": health_labels,
            "values": health_values,
            "trend_pct": trend_pct,
            "recent_avg": round(recent_avg, 1),
        },
    }


def _build_device_stats(devices_raw, parsed, parsed_chrono, today_start, week_start, thirty_days_ago):
    """Build per-device statistics."""
    device_stats = []
    for d in devices_raw:
        did = d["device_id"]
        conn = d.get("connectivity", {})
        desc = d.get("description", did)

        # Events for this device
        dev_events = [(dt, ev) for dt, ev in parsed if ev.get("deviceId") == did]
        dev_today = sum(1 for dt, _ in dev_events if dt >= today_start)
        dev_week = sum(1 for dt, _ in dev_events if dt >= week_start)
        dev_total = len(dev_events)

        # Hourly pattern (30 days)
        hourly = [0] * 24
        for dt, _ in dev_events:
            if dt >= thirty_days_ago:
                hourly[dt.hour] += 1

        # Classification breakdown
        class_counts: dict[str, int] = defaultdict(int)
        for _, ev in dev_events:
            cls = CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown")
            class_counts[cls] += 1

        # Trigger breakdown
        trigger_counts: dict[str, int] = defaultdict(int)
        for _, ev in dev_events:
            tr = TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown")
            trigger_counts[tr] += 1

        # Daily event counts for the last 30 days (for sparkline)
        daily_counts: dict[str, int] = defaultdict(int)
        for dt, _ in dev_events:
            if dt >= thirty_days_ago:
                daily_counts[dt.strftime("%m/%d")] += 1
        now = parsed_chrono[-1][0] if parsed_chrono else datetime.now(TZ)
        daily_labels = [(now - timedelta(days=29 - i)).strftime("%m/%d") for i in range(30)]
        daily_values = [daily_counts.get(label, 0) for label in daily_labels]

        # First and last event
        first_event = dev_events[-1][0].isoformat() if dev_events else None
        last_event = dev_events[0][0].isoformat() if dev_events else None

        # Avg events per day (30 days)
        dev_30d = sum(1 for dt, _ in dev_events if dt >= thirty_days_ago)
        avg_per_day = round(dev_30d / 30, 1) if dev_30d else 0

        # Peak hour
        peak_hour = hourly.index(max(hourly)) if max(hourly) > 0 else None

        device_stats.append({
            "device_id": did,
            "description": desc,
            "connected": conn.get("connected", False),
            "disconnect_reason": conn.get("disconnectReason", ""),
            "firmware_version": conn.get("firmwareVersion", ""),
            "signal_strength": conn.get("signalStrength"),
            "events_today": dev_today,
            "events_week": dev_week,
            "events_total": dev_total,
            "avg_per_day": avg_per_day,
            "peak_hour": f"{peak_hour:02d}:00" if peak_hour is not None else "--",
            "hourly_pattern": hourly,
            "classification_breakdown": dict(class_counts),
            "trigger_breakdown": dict(trigger_counts),
            "daily_activity": {"labels": daily_labels, "values": daily_values},
            "first_event": first_event,
            "last_event": last_event,
        })

    return device_stats


async def _fetch_weather() -> dict | None:
    """Fetch 30-day weather from Open-Meteo, with daily cache."""
    now = datetime.now(TZ)
    cache_date = await store.get_meta("weather_cache_date")
    if cache_date == now.strftime("%Y-%m-%d"):
        cached = await store.get_meta("weather_cache")
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass
    try:
        end_date = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LATITUDE}&longitude={LONGITUDE}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
            f"&start_date={start_date}&end_date={end_date}&timezone=auto"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            data = resp.json()
        daily = data.get("daily", {})
        result = {
            "dates": daily.get("time", []),
            "temp_max": daily.get("temperature_2m_max", []),
            "temp_min": daily.get("temperature_2m_min", []),
            "precipitation": daily.get("precipitation_sum", []),
            "weather_code": daily.get("weather_code", []),
        }
        await store.set_meta("weather_cache", json.dumps(result))
        await store.set_meta("weather_cache_date", now.strftime("%Y-%m-%d"))
        return result
    except Exception:
        logger.exception("Failed to fetch weather data")
        return None


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
        "timezone": str(TZ),
    }


async def _build_chart_data():
    """Aggregate events from DB into daily, weekly, and monthly buckets."""
    now = datetime.now(TZ)
    cutoff = (now - timedelta(days=30)).isoformat()
    all_events = await store.get_since(cutoff)

    parsed = []
    for ev in all_events:
        ts = ev.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
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
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


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


@app.get("/api/export")
async def export_csv():
    """Export all events as CSV."""
    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    devices_raw = await store.get_devices()
    pet_map = {p["rfid_code"]: p for p in pets_raw}
    device_map = {d["device_id"]: d for d in devices_raw}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Event ID", "Timestamp", "Device", "Trigger", "Classification", "Pets", "Frame Count"])
    for ev in all_events:
        rfid_codes = ev.get("rfidCodes") or []
        pet_names = [pet_map.get(c, {}).get("label", c) for c in rfid_codes]
        writer.writerow([
            ev.get("eventId", ""),
            ev.get("timestamp", ""),
            device_map.get(ev.get("deviceId", ""), {}).get("description", ev.get("deviceId", "")),
            TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
            CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown"),
            ", ".join(pet_names),
            ev.get("frameCount", 0),
        ])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=onlycat_events.csv"},
    )


# --- Cat door control ---
@app.post("/api/device/{device_id}/policy")
async def set_door_policy(device_id: str, request: Request):
    body = await request.json()
    policy = body.get("policy")
    token = os.environ.get("ONLYCAT_TOKEN")
    if not token:
        return JSONResponse({"error": "No token"}, status_code=500)
    result = await set_transit_policy(token, device_id, policy)
    return result


# --- Annotations ---
@app.post("/api/annotations")
async def add_annotation(request: Request):
    body = await request.json()
    await store.add_annotation(body["event_id"], body["note"])
    return {"status": "ok"}


@app.get("/api/annotations")
async def list_annotations():
    return await store.get_all_annotations()


@app.delete("/api/annotations/{annotation_id}")
async def delete_annotation(annotation_id: int):
    await store.delete_annotation(annotation_id)
    return {"status": "ok"}


# --- Alerts ---
@app.get("/api/alerts")
async def list_alerts():
    return await store.get_alerts()


@app.post("/api/alerts")
async def add_alert(request: Request):
    body = await request.json()
    await store.add_alert(body["name"], body["alert_type"], body.get("threshold"))
    return {"status": "ok"}


@app.delete("/api/alerts/{alert_id}")
async def delete_alert_endpoint(alert_id: int):
    await store.delete_alert(alert_id)
    return {"status": "ok"}


@app.put("/api/alerts/{alert_id}")
async def update_alert_endpoint(alert_id: int, request: Request):
    body = await request.json()
    await store.update_alert(alert_id, body.get("enabled", True))
    return {"status": "ok"}


# --- Door schedule ---
@app.get("/api/schedules")
async def list_schedules():
    return await store.get_schedules()


@app.post("/api/schedules")
async def add_schedule(request: Request):
    body = await request.json()
    await store.add_schedule(body["device_id"], body["action"], body["hour"], body["minute"], body.get("days", "0,1,2,3,4,5,6"))
    return {"status": "ok"}


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    await store.delete_schedule(schedule_id)
    return {"status": "ok"}


@app.get("/share", response_class=HTMLResponse)
async def share_page(request: Request):
    """Public read-only dashboard."""
    state = await build_state()
    return templates.TemplateResponse(
        "share.html",
        {"request": request, "initial_state": state},
    )


@app.get("/api/diary")
async def get_diary():
    """Generate AI diary entry for today using Claude."""
    if not ANTHROPIC_API_KEY:
        return {"diary": None, "error": "Set ANTHROPIC_API_KEY to enable AI diary"}
    today_key = f"diary_{datetime.now(TZ).strftime('%Y-%m-%d')}"
    cached = await store.get_meta(today_key)
    if cached:
        return {"diary": cached}

    analytics = await build_analytics()
    oni = analytics["oni_status"]
    summary = analytics["summary"]
    cb = analytics["contraband"]
    trips_data = analytics["trips"]
    misha = analytics["misha_visits"]
    moon = analytics["moon"]

    prompt = (
        f"Write a short, fun, first-person diary entry (3-4 sentences) as Oni the cat. "
        f"Today's stats: {summary['events_today']} events, "
        f"{trips_data['trips_today']} trips outside, "
        f"{trips_data['time_outside_today_minutes']} minutes outside total. "
        f"Oni is currently {oni['status']}. "
        f"Contraband status: {cb['days_since']} days since last incident. "
        f"Misha (neighbor cat) visited {misha['visits_week']} times this week. "
        f"Moon: {moon['today_name']} ({moon['today_illumination']}% illumination). "
        f"Be playful, use cat personality. Keep it under 100 words."
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            data = resp.json()
            diary = data["content"][0]["text"]
        await store.set_meta(today_key, diary)
        return {"diary": diary}
    except Exception as exc:
        logger.exception("Failed to generate diary")
        return {"diary": None, "error": str(exc)}


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
