# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

onlycat-tool is a web dashboard for monitoring cat activity via the OnlyCat Cloud API. Python, managed with [uv](https://docs.astral.sh/uv/).

## Common Commands

```bash
# Run the dashboard (serves on http://localhost:8000)
uv run main.py

# Run the tests
uv run pytest tests/ -v

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
- **`content.py`** — All *public* content for the personal site at slederer.com (bio, angel portfolio, SPV-led rounds, AI Incubator cohorts, side projects). This is the only file to edit when that content changes; `tests/test_content.py` validates it.
- **`portfolio_store.py`** — SQLite-backed *private* investment tracking (cheque, date, instrument, marks, status) joined to `content.PORTFOLIO` by company name, plus the analytics behind `/admin`. `public_overlay()` is deliberately the only path from private data to the public page, and it passes just status/round/year — never money.
- **`templates/site_base.html`, `macros.html`, `homepage.html`, `projects.html`** — The personal site. `site_base.html` holds the shared design tokens (same palette as the dashboard) and light/dark handling.

### Two sites, one app

The app serves two properties, branching on the `Host` header:

| Host | Serves |
|---|---|
| `slederer.com`, `www.slederer.com` | Personal site (`/`, `/projects`, `/admin`) |
| anything else (e.g. `oni.slederer.com`) | OnlyCat dashboard |

`is_homepage_host()` / `require_homepage_host()` in `main.py` gate this; `/projects` and `/admin` return 404 on the dashboard host. To preview the personal site locally:

```bash
EXTRA_HOMEPAGE_HOSTS=localhost uv run main.py
```

### Portfolio tracker

`/admin` is the private portfolio tracker: personal-site host only, behind Google OAuth, and further restricted to `ALLOWED_EMAILS` by `require_admin()`. It records what was invested and what it is worth, computes exposure/concentration/TVPI, and feeds `status` back to the public page so companies stop being listed as `active` forever. Every figure reports its own coverage — a TVPI over a third of the book is labelled as such rather than printed as a portfolio return.

Tracking data lives in the `investments` table in the same SQLite DB (`DB_PATH`), keyed by the company name in `content.PORTFOLIO`. Renaming a company in `content.py` orphans its row, so rename in both places.

The tracker also records **when each company last wrote to Stefan** (`last_heard_on`), separately from when he last edited the row. Silence is the earliest warning an angel position gives — companies stop sending updates long before they admit trouble — so `/admin` buckets the portfolio by how long it has been quiet and can sort quietest-first.

**There is no live Gmail sync**, and adding one is not a config tweak: the app's Google OAuth requests only `openid email profile` with `access_type=online`, so it has neither a Gmail scope nor a refresh token to act with later. Contact data is produced by Claude sweeping the mailbox in a session, written to `scripts/gmail_scan_<date>.json`, and loaded with:

```bash
uv run python scripts/import_gmail_scan.py scripts/gmail_scan_2026_09_20.json [--dry-run]
```

A company absent from a scan is recorded as *unmatched*, never as *silent* — it may simply send from a domain the sweep did not search.

### Signals: what the companies reported

`portfolio_signals.py` holds what founders said, as opposed to what Stefan knows first-hand: ARR/MRR over time, runway, burn, headcount, plus events (raises, layoffs, pivots) and the intros they asked for. Loaded the same snapshot way:

```bash
uv run python scripts/import_signals.py scripts/signals_2026_09_20.json [--dry-run]
```

Rules that matter when adding to it:

- **Every number must cite its Gmail thread.** The importer refuses a metric or event with no `source_thread`. Provenance is the only defence against a figure that was extracted wrong, and the UI links each one back to the email.
- **Never mix monthly and annual magnitudes.** Report what the founder reported (`arr`, `mrr`, or `revenue_month`); `trajectory()` annualises for the chart.
- **No FX conversion.** Kickscale reports EUR, the rest USD; converting would invent precision.
- **`shutdown` means the company is winding up.** Retiring a product line is a `pivot` — conflating them once ranked Rownd as the most distressed company in the book the same month it won a $2.5M USAF contract.

`triage()` ranks companies by silence, distance from peak revenue, runway and events. It returns the *reasons* alongside each score; the UI always renders them, because an unexplained number is one nobody can argue with or trust.

## Deployment

Production runs on EC2 `i-059c9a5411e34d874` (us-east-2, `13.59.224.218`, user `ec2-user`, key `~/Downloads/onlycats.pem`) via `docker compose` (services `onlycat`, `nginx`, `certbot`). `fly.toml` is unused.

```bash
ssh -i ~/Downloads/onlycats.pem ec2-user@13.59.224.218 \
  'cd ~/onlycat-tool && git pull --ff-only && docker compose up -d --build onlycat'
curl -s https://slederer.com/ | grep mailto   # verify
```

Email: `stefan@slederer.com` forwards to Gmail via Cloudflare Email Routing (configured in Cloudflare, not in this repo).

## OnlyCat Cloud API

The API is Socket.IO over WebSocket (not REST). Auth is a static token from the OnlyCat mobile app, passed via `auth={"token": ...}` on connect. Key events: `getDevices`, `getDevice`, `getDeviceEvents`, `getEvent`, `getRfidProfile`, `getLastSeenRfidCodesByDevice`, `activateDeviceTransitPolicy`, `runDeviceCommand`. Server pushes: `deviceUpdate`, `deviceEventUpdate`, `eventUpdate`, `userUpdate`.

## Configuration

Set `ONLYCAT_TOKEN` in a `.env` file (see `.env.example`). The token is obtained from the OnlyCat mobile app under "Account".

| Variable | Default | Description |
|---|---|---|
| `ONLYCAT_TOKEN` | (required) | Auth token from OnlyCat app |
| `SYNC_INTERVAL_HOURS` | `24` | Hours between automatic syncs |
| `DB_PATH` | `./onlycat_events.db` | Path to SQLite database file |
