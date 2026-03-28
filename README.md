# OnlyCat Dashboard

A self-hosted web dashboard for monitoring cat activity via the [OnlyCat](https://onlycat.com) smart cat door. Built with Python, FastAPI, and Chart.js.

## Features

**Activity Monitoring**
- Real-time event tracking with 10-minute sync interval
- Inside/outside status detection based on motion sensor direction
- Trip tracking with duration, averages, and predictions
- Today's visual timeline with event markers

**Analytics**
- Hourly activity patterns and weekly heatmap
- Historical comparison (this week vs last week)
- Health trends (12-week activity chart with trend detection)
- GitHub-style 365-day activity calendar
- Weather correlation (via Open-Meteo, no API key needed)
- Moon phase tracking and activity correlation
- Classification breakdown (Clear, Suspicious, Contraband)
- Records and milestones

**Multi-Pet Support**
- Automatic identification of resident vs visitor pets via RFID
- Per-pet activity patterns and statistics
- Visitor sighting tracker

**Cat Door Control**
- Remote lock/unlock (Both Ways, In Only, Out Only, Locked)
- Scheduled auto-lock/unlock with day-of-week selection

**Alerts & Notifications**
- Configurable alert rules (outside too long, contraband, visitor, no activity, night activity)
- Browser push notifications for contraband events
- Event annotations (add notes to specific events)

**Extras**
- AI-generated daily diary entries (requires Anthropic API key)
- Achievement badges (15+ unlockable)
- CSV export of all event history
- Dark/light mode with section collapse/expand
- Public share page at `/share`
- PWA support (installable on mobile)
- Device stats tab with per-device analytics

## Quick Start

### Prerequisites
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- An OnlyCat account with an API token (found in the OnlyCat mobile app under Account)

### Local Development

```bash
git clone https://github.com/slederer/onlycat-tool.git
cd onlycat-tool

# Configure
cp .env.example .env
# Edit .env with your ONLYCAT_TOKEN

# Run
uv run main.py
# Open http://localhost:8000
```

### Docker

```bash
docker compose up -d --build
# Open http://localhost
```

### Deploy to AWS EC2

```bash
# SSH into your instance
ssh -i your-key.pem ec2-user@your-ec2-ip

# Install Docker
sudo dnf install -y docker git
sudo systemctl enable --now docker

# Clone and run
git clone https://github.com/slederer/onlycat-tool.git
cd onlycat-tool
echo "ONLYCAT_TOKEN=your-token" > .env
sudo docker compose up -d --build
```

Make sure your EC2 security group allows inbound HTTP (port 80).

## Configuration

All configuration is via environment variables (set in `.env` or `docker-compose.yml`):

| Variable | Default | Description |
|---|---|---|
| `ONLYCAT_TOKEN` | (required) | Auth token from OnlyCat mobile app |
| `SYNC_INTERVAL_MINUTES` | `10` | Minutes between automatic syncs |
| `LATITUDE` | `48.8566` | Latitude for weather data |
| `LONGITUDE` | `2.3522` | Longitude for weather data |
| `TIMEZONE` | `Europe/Paris` | Timezone for analytics (IANA format) |
| `DB_PATH` | `./onlycat_events.db` | Path to SQLite database |
| `ANTHROPIC_API_KEY` | (optional) | Enables AI diary feature |

## Architecture

```
main.py              FastAPI app, analytics engine, API endpoints
sync.py              Periodic data sync from OnlyCat Cloud (Socket.IO)
event_store.py       SQLite storage for events, devices, pets, alerts, schedules
commands.py          Cat door control commands via OnlyCat gateway
templates/
  dashboard.html     Main dashboard (Jinja2 + Chart.js + vanilla JS)
  share.html         Public read-only share page
static/
  manifest.json      PWA manifest
  sw.js              Service worker for offline support
  oni.jpg            Cat photo
  icon.svg           App icon
tests/
  test_event_store.py   SQLite CRUD tests
  test_api.py           API endpoint tests
  test_analytics.py     Analytics computation tests
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Dashboard |
| GET | `/share` | Public share page |
| POST | `/api/sync` | Trigger manual sync |
| GET | `/api/status` | Sync status and event count |
| GET | `/api/export` | Download all events as CSV |
| GET | `/api/diary` | AI-generated diary entry |
| POST | `/api/device/{id}/policy` | Set door policy (lock/unlock) |
| GET/POST/DELETE | `/api/annotations` | Event annotations |
| GET/POST/PUT/DELETE | `/api/alerts` | Custom alert rules |
| GET/POST/DELETE | `/api/schedules` | Door schedules |
| WS | `/ws` | WebSocket for live dashboard updates |

## Tests

```bash
uv run pytest tests/ -v
```

66 tests covering the event store, API endpoints, and analytics engine.

## CI/CD

GitHub Actions runs tests on every push and PR. On successful merge to `main`, auto-deploys to EC2 via SSH.

To enable auto-deploy, add these GitHub repository secrets:
- `EC2_HOST` — your EC2 public IP
- `EC2_SSH_KEY` — contents of your `.pem` private key

## OnlyCat Cloud API

The OnlyCat API uses Socket.IO over WebSocket (not REST). Auth is a static token passed via `auth={"token": ...}` on connect. The gateway URL is `https://gateway.onlycat.com`.

**Fetch operations:** `getDevices`, `getDevice`, `getDeviceEvents`, `getEvent`, `getRfidProfile`, `getLastSeenRfidCodesByDevice`

**Control operations:** `activateDeviceTransitPolicy`, `runDeviceCommand`

**Server pushes:** `deviceUpdate`, `deviceEventUpdate`, `eventUpdate`, `userUpdate`

## License

MIT
