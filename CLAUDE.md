# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

onlycat-tool is a web dashboard for monitoring cat activity via the OnlyCat Cloud API. Python, managed with [uv](https://docs.astral.sh/uv/).

## Common Commands

```bash
# Run the dashboard (serves on http://localhost:8000)
uv run main.py

# Add a dependency
uv add <package>

# Sync dependencies (install from lockfile)
uv sync
```

## Architecture

- **`main.py`** — FastAPI app entry point. Serves the dashboard from SQLite, runs a background sync task on a configurable interval, exposes `/ws` WebSocket for browser updates and `/api/sync` for manual triggers.
- **`sync.py`** — Connects to OnlyCat Cloud via Socket.IO, fetches all devices/pets/events, stores in SQLite, then disconnects. Used by the background scheduler and the manual sync endpoint.
- **`onlycat_client.py`** — Legacy persistent Socket.IO client (kept for reference). The app now uses `sync.py` for periodic batch syncing instead.
- **`event_store.py`** — SQLite-backed storage for events, devices, pets, and sync metadata. DB path configurable via `DB_PATH` env var.
- **`templates/dashboard.html`** — Single Jinja2 template with inline CSS/JS. Receives initial state server-rendered, then updates live via browser WebSocket.

## Deployment

Dockerized for Fly.io. Uses a persistent volume mounted at `/data` for the SQLite database.

```bash
# Deploy to Fly.io
fly launch          # first time
fly deploy          # subsequent deploys
fly secrets set ONLYCAT_TOKEN=your-token

# Create the persistent volume (first time)
fly volumes create onlycat_data --region ewr --size 1
```

## OnlyCat Cloud API

The API is Socket.IO over WebSocket (not REST). Auth is a static token from the OnlyCat mobile app, passed via `auth={"token": ...}` on connect. Key events: `getDevices`, `getDevice`, `getDeviceEvents`, `getEvent`, `getRfidProfile`, `getLastSeenRfidCodesByDevice`, `activateDeviceTransitPolicy`, `runDeviceCommand`. Server pushes: `deviceUpdate`, `deviceEventUpdate`, `eventUpdate`, `userUpdate`.

## Configuration

Set `ONLYCAT_TOKEN` in a `.env` file (see `.env.example`). The token is obtained from the OnlyCat mobile app under "Account".

| Variable | Default | Description |
|---|---|---|
| `ONLYCAT_TOKEN` | (required) | Auth token from OnlyCat app |
| `SYNC_INTERVAL_HOURS` | `24` | Hours between automatic syncs |
| `DB_PATH` | `./onlycat_events.db` | Path to SQLite database file |
