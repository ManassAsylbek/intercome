# Intercom Management Server

A fully local IP intercom management server for Leelen-compatible devices.
Manages door stations, home stations, SIP accounts, RTSP streams, and HTTP unlock actions via a clean web UI and REST API.

```
┌─────────────────────────────────────────────────────────┐
│                     Browser / Admin UI                  │
│              React + Vite  (port 5173 / 80)             │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API  /api/*
┌──────────────────────▼──────────────────────────────────┐
│              FastAPI Backend  (port 8000)                │
│   Auth │ Devices │ Routing Rules │ Dashboard            │
│   Unlock Service │ Connectivity Check │ Polling         │
└───────┬────────────────────┬────────────────────────────┘
        │                    │
   SQLite / PostgreSQL    HTTP unlock / TCP ping
   (local data store)    (to devices on LAN)
```

---

## Project Structure

```
intercom-v2/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py            # Auth dependencies
│   │   │   └── routes/
│   │   │       ├── auth.py        # POST /api/auth/login, GET /api/auth/me
│   │   │       ├── devices.py     # CRUD + test-connection + test-unlock
│   │   │       ├── routing_rules.py
│   │   │       └── dashboard.py   # /api/health, /api/system/info, /api/dashboard/summary
│   │   ├── core/
│   │   │   ├── config.py          # Pydantic settings from .env
│   │   │   ├── logging.py         # Structured logging (structlog)
│   │   │   └── security.py        # JWT, bcrypt
│   │   ├── db/
│   │   │   └── session.py         # Async SQLAlchemy engine + Base
│   │   ├── models/
│   │   │   └── __init__.py        # User, Device, RoutingRule, ActivityLog
│   │   ├── schemas/
│   │   │   └── __init__.py        # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── device_service.py   # Device CRUD + activity logging
│   │   │   ├── unlock_service.py   # HTTP GET/POST unlock
│   │   │   ├── connectivity_service.py  # HTTP ping + TCP fallback
│   │   │   ├── polling_service.py  # Background online/offline poller
│   │   │   ├── sip_service.py      # Asterisk placeholder
│   │   │   └── rtsp_service.py     # MediaMTX placeholder
│   │   └── main.py                # FastAPI app, lifespan, CORS
│   ├── alembic/                   # DB migrations
│   ├── tests/                     # pytest async tests
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/           # Axios client + typed API functions
│   │   ├── components/
│   │   │   ├── ui/        # Button, Badge, Card, FormFields, Modal, Toast
│   │   │   ├── layout/    # AppLayout (sidebar), RequireAuth
│   │   │   └── devices/   # DeviceFormModal
│   │   ├── hooks/         # useDevices, useRoutingRules, useDashboard, useAuth
│   │   ├── lib/           # cn(), formatters, label maps
│   │   ├── pages/         # Login, Dashboard, Devices, DeviceDetail, Routing, Settings
│   │   └── types/         # TypeScript interfaces matching backend schemas
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   ├── nginx.conf
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## macOS Local Development

### Prerequisites

```bash
# Install Homebrew (if needed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.11+ and Node 20+
brew install python@3.11 node@20

# Verify
python3.11 --version   # Python 3.11.x
node --version         # v20.x.x
npm --version          # 10.x.x
```

### 1. Clone & enter project

```bash
git clone <repo-url> intercom-v2
cd intercom-v2
```

### 2. Backend setup

```bash
cd backend

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy and edit environment config
cp .env.example .env
# Edit .env if needed (defaults work out-of-the-box for local dev)

# Run database migrations
alembic upgrade head
# → Creates backend/data/intercom.db with all tables
# → Seeds admin user (admin/admin123)
# → Seeds example door station (192.168.31.31) and home station (192.168.31.100)

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API is available at: **http://localhost:8000**
Interactive docs: **http://localhost:8000/api/docs**

### 3. Frontend setup

```bash
# In a new terminal tab
cd frontend

# Install dependencies
npm install

# Start dev server (proxies /api/* to http://localhost:8000)
npm run dev
```

Frontend is available at: **http://localhost:5173**

### 4. Login

| Field    | Value      |
| -------- | ---------- |
| Username | `admin`    |
| Password | `admin123` |

> Change the password in `.env` before deploying.

---

## Running Tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v --cov=app --cov-report=term-missing
```

Expected: **30 tests, all passing**.

---

## Docker (Production)

### Quick start

```bash
# From repo root
cp backend/.env.example backend/.env
# Edit backend/.env — set APP_SECRET_KEY and ADMIN_PASSWORD

docker-compose up --build
```

| Service  | URL                            |
| -------- | ------------------------------ |
| Frontend | http://localhost               |
| Backend  | http://localhost:8000          |
| API Docs | http://localhost:8000/api/docs |

### Stop / reset

```bash
docker-compose down          # stop
docker-compose down -v       # stop + delete database volume
```

---

## API Reference

### Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# → {"access_token": "eyJ...", "token_type": "bearer", "expires_in": 28800}

# Store token
TOKEN="eyJ..."

# Get current user
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/me
```

### Devices

```bash
# List all devices
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/devices

# List door stations only
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/devices?device_type=door_station"

# Create a device
curl -X POST http://localhost:8000/api/devices \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Front Door",
    "device_type": "door_station",
    "ip_address": "192.168.31.31",
    "web_port": 8000,
    "sip_enabled": true,
    "sip_account": "door001",
    "sip_server": "192.168.31.132",
    "sip_port": 5060,
    "rtsp_enabled": true,
    "rtsp_url": "rtsp://admin:123456@192.168.31.31:554/h264",
    "unlock_enabled": true,
    "unlock_method": "http_get",
    "unlock_url": "http://192.168.31.31:8000/unlock",
    "unlock_username": "admin",
    "unlock_password": "123456"
  }'

# Get device by ID
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/devices/1

# Update a device
curl -X PUT http://localhost:8000/api/devices/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Main Entrance", "enabled": true}'

# Test device connectivity
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/devices/1/test-connection

# Test door unlock
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/devices/1/test-unlock

# Delete device
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/devices/1
```

### Routing Rules

```bash
# List all rules
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/routing-rules

# Create a rule
curl -X POST http://localhost:8000/api/routing-rules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Front Door → Living Room",
    "call_code": "101",
    "source_device_id": 1,
    "target_device_id": 2,
    "enabled": true,
    "priority": 10
  }'

# Update a rule
curl -X PUT http://localhost:8000/api/routing-rules/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Delete a rule
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/routing-rules/1
```

### Dashboard

```bash
# System health (no auth required)
curl http://localhost:8000/api/health

# Dashboard summary
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/dashboard/summary

# System info
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/system/info
```

---

## Device Model Reference

| Field            | Type             | Description                                                             |
| ---------------- | ---------------- | ----------------------------------------------------------------------- |
| `name`           | string           | Human-readable name                                                     |
| `device_type`    | enum             | `door_station`, `home_station`, `guard_station`, `sip_client`, `camera` |
| `ip_address`     | string \| null   | Device IP on local network                                              |
| `web_port`       | int \| null      | HTTP web interface port                                                 |
| `enabled`        | bool             | Whether device is active                                                |
| `sip_enabled`    | bool             | SIP registration enabled                                                |
| `sip_account`    | string \| null   | SIP extension number                                                    |
| `sip_server`     | string \| null   | SIP registrar IP/hostname                                               |
| `sip_port`       | int \| null      | SIP port (default 5060)                                                 |
| `rtsp_enabled`   | bool             | RTSP stream enabled                                                     |
| `rtsp_url`       | string \| null   | Full RTSP URL with credentials                                          |
| `unlock_enabled` | bool             | HTTP unlock enabled                                                     |
| `unlock_method`  | enum             | `http_get`, `http_post`, `sip_dtmf`, `none`                             |
| `unlock_url`     | string \| null   | URL to call for unlock                                                  |
| `is_online`      | bool \| null     | Set by background polling                                               |
| `last_seen`      | datetime \| null | Last successful connectivity check                                      |

---

## Seed Data (pre-loaded)

### Door Station

| Field         | Value                                        |
| ------------- | -------------------------------------------- |
| Name          | Front Door Station                           |
| IP            | 192.168.31.31                                |
| Web Port      | 8000                                         |
| SIP Account   | door001                                      |
| SIP Server    | 192.168.31.132                               |
| RTSP URL      | `rtsp://admin:123456@192.168.31.31:554/h264` |
| Unlock URL    | `http://192.168.31.31:8000/unlock`           |
| Unlock Method | HTTP GET                                     |

### Home Station

| Field       | Value                    |
| ----------- | ------------------------ |
| Name        | Living Room Home Station |
| IP          | 192.168.31.100           |
| SIP Account | home001                  |
| SIP Server  | 192.168.31.132           |

---

## Future Integrations

### Asterisk / SIP

The `sip_service.py` is a ready placeholder. To integrate:

1. Add Asterisk AMI credentials to `.env`
2. Install `panoramisk` or `aioasterisk`
3. Implement `SIPService.originate_call()` and `send_dtmf_unlock()`

### RTSP / Media Server

The `rtsp_service.py` is a ready placeholder. To integrate:

1. Set up [MediaMTX](https://github.com/bluenviron/mediamtx)
2. Implement `RTSPService.get_stream_url()` to return HLS/WebRTC URLs
3. Add a video player component to the Device Detail page

### PostgreSQL Migration

Change `DATABASE_URL` in `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/intercom
```

Then run:

```bash
alembic upgrade head
```

---

## Environment Variables

| Variable                          | Default                                  | Description             |
| --------------------------------- | ---------------------------------------- | ----------------------- |
| `APP_ENV`                         | `development`                            | App environment         |
| `APP_SECRET_KEY`                  | _change this_                            | JWT signing secret      |
| `APP_ACCESS_TOKEN_EXPIRE_MINUTES` | `480`                                    | Token TTL (8 hours)     |
| `APP_CORS_ORIGINS`                | `http://localhost:5173,...`              | Allowed CORS origins    |
| `DATABASE_URL`                    | `sqlite+aiosqlite:///./data/intercom.db` | Database connection URL |
| `ADMIN_USERNAME`                  | `admin`                                  | Initial admin username  |
| `ADMIN_PASSWORD`                  | `admin123`                               | Initial admin password  |
| `SERVER_IP`                       | `192.168.31.132`                         | This server's LAN IP    |
| `LOG_LEVEL`                       | `INFO`                                   | Logging level           |
| `LOG_FORMAT`                      | `json`                                   | `json` or `console`     |

---

## Tech Stack

| Layer     | Technology                                          |
| --------- | --------------------------------------------------- |
| Backend   | Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic |
| Auth      | JWT (python-jose), bcrypt (passlib)                 |
| HTTP      | httpx (async outbound requests)                     |
| Frontend  | React 19, TypeScript, Vite                          |
| State     | TanStack Query v5                                   |
| Forms     | react-hook-form + zod                               |
| Styling   | Tailwind CSS v3                                     |
| Icons     | lucide-react                                        |
| Container | Docker + Docker Compose                             |
| DB        | SQLite (dev) / PostgreSQL (prod-ready)              |
