"""MCP server for OnlyCat — exposes cat activity data to ChatGPT and other MCP clients."""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from event_store import EventStore

TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Paris"))
CLASSIFICATION = {
    0: "Unknown", 1: "Clear", 2: "Suspicious", 3: "Contraband",
    4: "Human Activity", 10: "Remote Unlock",
}
TRIGGER_SOURCE = {
    0: "Manual", 1: "Remote", 2: "Indoor Motion", 3: "Outdoor Motion",
}

mcp = FastMCP(
    "OnlyCat",
    instructions=(
        "OnlyCat is a cat activity monitor for Oni, an orange female cat in Paris. "
        "Use these tools to check on Oni's status, activity patterns, trips, contraband incidents, "
        "visitor cats, and device health. Data comes from an OnlyCat smart cat door with RFID detection. "
        "Trigger sources: 2=Indoor Motion (cat leaving), 3=Outdoor Motion (cat entering). "
        "Classifications: 1=Clear, 2=Suspicious, 3=Contraband (prey brought in). "
        "All timestamps are in Europe/Paris timezone."
    ),
)

# The store will be set from main.py after initialization
store: EventStore | None = None


def set_store(s: EventStore):
    global store
    store = s


def _parse_events(all_events: list[dict]) -> list[tuple[datetime, dict]]:
    """Parse events and convert timestamps to local timezone."""
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
    return parsed


def _identify_pets(parsed: list[tuple[datetime, dict]], pets_raw: list[dict]):
    """Identify resident and visitor cats from event frequency."""
    pet_map = {p["rfid_code"]: p for p in pets_raw}
    pet_event_counts: dict[str, int] = defaultdict(int)
    for _, ev in parsed:
        for code in (ev.get("rfidCodes") or []):
            pet_event_counts[code] += 1

    sorted_pets = sorted(pet_event_counts.items(), key=lambda x: x[1], reverse=True)
    resident_code = sorted_pets[0][0] if sorted_pets else None
    visitor_code = sorted_pets[1][0] if len(sorted_pets) > 1 else None
    resident_label = pet_map.get(resident_code, {}).get("label", "Oni") if resident_code else "Oni"
    visitor_label = pet_map.get(visitor_code, {}).get("label", "Misha") if visitor_code else "Misha"
    return resident_code, visitor_code, resident_label, visitor_label, pet_map


def _compute_trips(parsed_chrono, resident_code):
    """Compute trip history from chronological events."""
    oni_events = [
        (dt, ev) for dt, ev in parsed_chrono
        if resident_code and resident_code in (ev.get("rfidCodes") or [])
    ]
    trips = []
    trip_start = None
    for dt, ev in oni_events:
        trigger = ev.get("eventTriggerSource")
        if trigger == 2:  # Indoor motion = leaving
            trip_start = dt
        elif trigger == 3 and trip_start:  # Outdoor motion = returning
            duration = (dt - trip_start).total_seconds() / 60
            if 0 < duration < 24 * 60:
                trips.append({
                    "left_at": trip_start.isoformat(),
                    "returned_at": dt.isoformat(),
                    "duration_minutes": round(duration),
                })
            trip_start = None
    return trips, trip_start


@mcp.tool()
async def get_oni_status() -> dict:
    """Get Oni's current status: location (inside/outside), last event, direction, and current trip info."""
    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    parsed = _parse_events(all_events)
    parsed_chrono = sorted(parsed, key=lambda x: x[0])
    resident_code, _, _, _, _ = _identify_pets(parsed, pets_raw)

    status = "unknown"
    last_event_ts = None
    last_direction = None
    for dt, ev in reversed(parsed_chrono):
        codes = ev.get("rfidCodes") or []
        trigger = ev.get("eventTriggerSource")
        if resident_code and resident_code in codes and trigger in (2, 3):
            last_event_ts = dt.isoformat()
            if trigger == 2:
                status = "outside"
                last_direction = "left"
            elif trigger == 3:
                status = "inside"
                last_direction = "entered"
            break

    trips, trip_start = _compute_trips(parsed_chrono, resident_code)
    current_trip_start = None
    current_trip_duration = None
    if status == "outside" and trip_start:
        current_trip_start = trip_start.isoformat()
        current_trip_duration = round((datetime.now(TZ) - trip_start).total_seconds() / 60)

    last_sync = await store.get_meta("last_sync")

    return {
        "cat_name": "Oni",
        "location": status,
        "last_direction": last_direction,
        "last_event": last_event_ts,
        "current_trip_start": current_trip_start,
        "current_trip_duration_minutes": current_trip_duration,
        "last_sync": last_sync,
    }


@mcp.tool()
async def get_recent_events(limit: int = 20) -> list[dict]:
    """Get recent cat door events. Each event includes timestamp, trigger source, classification, and detected pets.

    Args:
        limit: Number of events to return (default 20, max 100)
    """
    limit = min(limit, 100)
    events = await store.get_recent(limit)
    pets_raw = await store.get_pets()
    pet_map = {p["rfid_code"]: p.get("label", p["rfid_code"]) for p in pets_raw}

    result = []
    for ev in events:
        ts = ev.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
            local_ts = dt.isoformat()
        except (ValueError, TypeError):
            local_ts = ts

        pet_names = [pet_map.get(code, code) for code in (ev.get("rfidCodes") or [])]
        result.append({
            "event_id": ev.get("eventId"),
            "timestamp": local_ts,
            "trigger": TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
            "classification": CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown"),
            "pets": pet_names,
            "direction": "leaving" if ev.get("eventTriggerSource") == 2 else "entering" if ev.get("eventTriggerSource") == 3 else "other",
        })
    return result


@mcp.tool()
async def get_activity_summary() -> dict:
    """Get a high-level activity summary: events today, this week, this month, averages, and records."""
    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    thirty_days_ago = now - timedelta(days=30)

    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    events_today = sum(1 for dt, _ in parsed if dt >= today_start)
    events_week = sum(1 for dt, _ in parsed if dt >= week_start)
    events_month = sum(1 for dt, _ in parsed if dt >= month_start)
    events_30d = sum(1 for dt, _ in parsed if dt >= thirty_days_ago)
    avg_per_day = round(events_30d / 30, 1) if events_30d else 0
    total_events = len(parsed)

    events_by_day: dict[str, int] = defaultdict(int)
    for dt, _ in parsed:
        events_by_day[dt.strftime("%Y-%m-%d")] += 1
    busiest_day = max(events_by_day, key=events_by_day.get) if events_by_day else None
    busiest_day_count = events_by_day.get(busiest_day, 0) if busiest_day else 0

    return {
        "events_today": events_today,
        "events_this_week": events_week,
        "events_this_month": events_month,
        "avg_per_day_30d": avg_per_day,
        "total_events": total_events,
        "busiest_day": busiest_day,
        "busiest_day_count": busiest_day_count,
    }


@mcp.tool()
async def get_hourly_activity(days: int = 30) -> dict:
    """Get hourly activity pattern (0-23h) over a given number of days. Useful for generating activity charts.

    Args:
        days: Number of days to include (default 30)
    """
    now = datetime.now(TZ)
    cutoff = now - timedelta(days=days)
    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    hourly = [0] * 24
    for dt, _ in parsed:
        if dt >= cutoff:
            hourly[dt.hour] += 1

    peak_hour = hourly.index(max(hourly)) if max(hourly) > 0 else None
    return {
        "period_days": days,
        "hourly_counts": {f"{h:02d}:00": count for h, count in enumerate(hourly)},
        "peak_hour": f"{peak_hour:02d}:00" if peak_hour is not None else None,
        "total": sum(hourly),
    }


@mcp.tool()
async def get_daily_activity(days: int = 30) -> dict:
    """Get daily event counts for a date range. Useful for generating daily activity charts and trends.

    Args:
        days: Number of days to include (default 30, max 365)
    """
    days = min(days, 365)
    now = datetime.now(TZ)
    cutoff = now - timedelta(days=days)
    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    daily: dict[str, int] = defaultdict(int)
    for dt, _ in parsed:
        if dt >= cutoff:
            daily[dt.strftime("%Y-%m-%d")] += 1

    # Fill in zero-days
    result = {}
    for i in range(days):
        d = (cutoff + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        result[d] = daily.get(d, 0)

    return {
        "period_days": days,
        "daily_counts": result,
        "total": sum(result.values()),
        "avg_per_day": round(sum(result.values()) / max(len(result), 1), 1),
    }


@mcp.tool()
async def get_heatmap(days: int = 30) -> dict:
    """Get a 7x24 activity heatmap (day-of-week x hour). Useful for visualizing weekly patterns.

    Args:
        days: Number of days to include (default 30)
    """
    now = datetime.now(TZ)
    cutoff = now - timedelta(days=days)
    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    heatmap = [[0] * 24 for _ in range(7)]
    for dt, _ in parsed:
        if dt >= cutoff:
            heatmap[dt.weekday()][dt.hour] += 1

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return {
        "period_days": days,
        "heatmap": {day_names[i]: heatmap[i] for i in range(7)},
        "description": "Each row is a day of the week, each column is an hour (0-23). Values are event counts.",
    }


@mcp.tool()
async def get_trip_history(limit: int = 20) -> dict:
    """Get Oni's recent outdoor trips with durations and stats.

    Args:
        limit: Number of recent trips to return (default 20)
    """
    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    parsed = _parse_events(all_events)
    parsed_chrono = sorted(parsed, key=lambda x: x[0])
    resident_code, _, _, _, _ = _identify_pets(parsed, pets_raw)

    trips, trip_start = _compute_trips(parsed_chrono, resident_code)

    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trips_today = [t for t in trips if datetime.fromisoformat(t["returned_at"]) >= today_start]

    avg_minutes = round(sum(t["duration_minutes"] for t in trips) / len(trips)) if trips else 0
    longest = max((t["duration_minutes"] for t in trips), default=0)
    time_outside_today = sum(t["duration_minutes"] for t in trips_today)

    recent_trips = list(reversed(trips[-limit:]))

    return {
        "recent_trips": recent_trips,
        "total_trips": len(trips),
        "trips_today": len(trips_today),
        "avg_duration_minutes": avg_minutes,
        "longest_trip_minutes": longest,
        "time_outside_today_minutes": time_outside_today,
    }


@mcp.tool()
async def get_contraband_report() -> dict:
    """Get contraband (prey) incident statistics: recent incidents, streak, patterns."""
    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    thirty_days_ago = now - timedelta(days=30)

    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    contraband = [(dt, ev) for dt, ev in parsed if ev.get("eventClassification") == 3]
    last_incident = contraband[0][0].isoformat() if contraband else None
    days_since = (now - contraband[0][0]).days if contraband else None

    this_week = sum(1 for dt, _ in contraband if dt >= week_start)
    this_month = sum(1 for dt, _ in contraband if dt >= month_start)

    by_hour = [0] * 24
    for dt, _ in contraband:
        if dt >= thirty_days_ago:
            by_hour[dt.hour] += 1

    # Contraband-free streak
    contraband_dates = {dt.date() for dt, _ in contraband}
    streak = 0
    check_date = now.date()
    while check_date not in contraband_dates and streak < 999:
        streak += 1
        check_date -= timedelta(days=1)

    recent = []
    for dt, ev in contraband[:10]:
        recent.append({
            "timestamp": dt.isoformat(),
            "event_id": ev.get("eventId"),
            "trigger": TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
        })

    return {
        "total_incidents": len(contraband),
        "last_incident": last_incident,
        "days_since_last": days_since,
        "current_clean_streak_days": streak,
        "this_week": this_week,
        "this_month": this_month,
        "hourly_pattern": {f"{h:02d}:00": count for h, count in enumerate(by_hour)},
        "recent_incidents": recent,
    }


@mcp.tool()
async def get_visitor_info() -> dict:
    """Get information about visiting cats (e.g., Misha): visit frequency, patterns, last seen."""
    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    parsed = _parse_events(all_events)
    _, visitor_code, _, visitor_label, _ = _identify_pets(parsed, pets_raw)

    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    thirty_days_ago = now - timedelta(days=30)

    if not visitor_code:
        return {"visitor_name": "None detected", "visits": 0}

    visitor_events = [(dt, ev) for dt, ev in parsed if visitor_code in (ev.get("rfidCodes") or [])]
    last_seen = visitor_events[0][0].isoformat() if visitor_events else None
    visits_today = sum(1 for dt, _ in visitor_events if dt >= today_start)
    visits_week = sum(1 for dt, _ in visitor_events if dt >= week_start)
    visits_month = sum(1 for dt, _ in visitor_events if dt >= month_start)

    hourly = [0] * 24
    for dt, _ in visitor_events:
        if dt >= thirty_days_ago:
            hourly[dt.hour] += 1
    peak_hour = hourly.index(max(hourly)) if max(hourly) > 0 else None

    return {
        "visitor_name": visitor_label,
        "last_seen": last_seen,
        "visits_today": visits_today,
        "visits_this_week": visits_week,
        "visits_this_month": visits_month,
        "usual_time": f"{peak_hour:02d}:00" if peak_hour is not None else None,
        "total_visits": len(visitor_events),
    }


@mcp.tool()
async def get_device_status() -> list[dict]:
    """Get status of all OnlyCat devices: connectivity, firmware, signal strength, and event stats."""
    devices = await store.get_devices()
    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    result = []
    for dev in devices:
        dev_id = dev["device_id"]
        conn = dev.get("connectivity", {})
        dev_events = [(dt, ev) for dt, ev in parsed if ev.get("deviceId") == dev_id]

        result.append({
            "device_id": dev_id,
            "description": dev.get("description", ""),
            "connected": conn.get("connected", False),
            "firmware_version": conn.get("firmwareVersion", "unknown"),
            "signal_strength": conn.get("signalStrength"),
            "events_today": sum(1 for dt, _ in dev_events if dt >= today_start),
            "events_this_week": sum(1 for dt, _ in dev_events if dt >= week_start),
            "total_events": len(dev_events),
        })
    return result


@mcp.tool()
async def get_weekly_comparison() -> dict:
    """Compare this week's activity with last week's: daily breakdowns and totals."""
    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_week_start = today_start - timedelta(days=today_start.weekday())
    last_week_start = this_week_start - timedelta(days=7)

    all_events = await store.get_all()
    parsed = _parse_events(all_events)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    this_week = {d: 0 for d in day_names}
    last_week = {d: 0 for d in day_names}

    for dt, _ in parsed:
        if dt >= this_week_start:
            this_week[day_names[dt.weekday()]] += 1
        elif dt >= last_week_start:
            last_week[day_names[dt.weekday()]] += 1

    this_total = sum(this_week.values())
    last_total = sum(last_week.values())
    change_pct = round((this_total - last_total) / last_total * 100, 1) if last_total > 0 else None

    return {
        "this_week": this_week,
        "last_week": last_week,
        "this_week_total": this_total,
        "last_week_total": last_total,
        "change_percent": change_pct,
    }


@mcp.tool()
async def get_events_by_date(date: str) -> list[dict]:
    """Get all events for a specific date. Useful for investigating a particular day.

    Args:
        date: Date in YYYY-MM-DD format
    """
    try:
        target = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TZ)
    except ValueError:
        return [{"error": "Invalid date format. Use YYYY-MM-DD."}]

    next_day = target + timedelta(days=1)
    all_events = await store.get_all()
    pets_raw = await store.get_pets()
    pet_map = {p["rfid_code"]: p.get("label", p["rfid_code"]) for p in pets_raw}
    parsed = _parse_events(all_events)

    result = []
    for dt, ev in parsed:
        if target <= dt < next_day:
            pet_names = [pet_map.get(code, code) for code in (ev.get("rfidCodes") or [])]
            result.append({
                "event_id": ev.get("eventId"),
                "timestamp": dt.isoformat(),
                "trigger": TRIGGER_SOURCE.get(ev.get("eventTriggerSource", -1), "Unknown"),
                "classification": CLASSIFICATION.get(ev.get("eventClassification", -1), "Unknown"),
                "pets": pet_names,
                "direction": "leaving" if ev.get("eventTriggerSource") == 2 else "entering" if ev.get("eventTriggerSource") == 3 else "other",
            })

    result.sort(key=lambda x: x["timestamp"])
    return result


@mcp.tool()
async def trigger_data_sync() -> dict:
    """Trigger a manual data sync from the OnlyCat Cloud API. Use this to get the freshest data."""
    from sync import run_sync
    result = await run_sync()
    return result
