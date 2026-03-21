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

- **`main.py`** — FastAPI app entry point. Serves the dashboard HTML, exposes a `/ws` WebSocket for live browser updates, and manages the OnlyCat client lifecycle via FastAPI's lifespan.
- **`onlycat_client.py`** — Async Socket.IO client connecting to `https://gateway.onlycat.com`. Maintains in-memory state (devices, events, pets) and calls a callback on every state change to push updates to the browser.
- **`templates/dashboard.html`** — Single Jinja2 template with inline CSS/JS. Receives initial state server-rendered, then updates live via browser WebSocket.

## OnlyCat Cloud API

The API is Socket.IO over WebSocket (not REST). Auth is a static token from the OnlyCat mobile app, passed via `auth={"token": ...}` on connect. Key events: `getDevices`, `getDevice`, `getDeviceEvents`, `getEvent`, `getRfidProfile`, `getLastSeenRfidCodesByDevice`, `activateDeviceTransitPolicy`, `runDeviceCommand`. Server pushes: `deviceUpdate`, `deviceEventUpdate`, `eventUpdate`, `userUpdate`.

## Configuration

Set `ONLYCAT_TOKEN` in a `.env` file (see `.env.example`). The token is obtained from the OnlyCat mobile app under "Account".
