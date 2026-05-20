# Stop Hunter Pro — Project Transfer Checklist

Use this checklist when moving the project to a new machine, repository, or hosting environment. Work through it top-to-bottom.

---

## Phase 1 — Source Code

- [ ] Clone or copy the repository to the target machine
- [ ] Confirm the following are present at the project root:
  - [ ] `backend/` directory
  - [ ] `frontend/` directory
  - [ ] `start.bat` (Windows launcher)
  - [ ] `bootstrap.ps1` (setup script)
  - [ ] `README.md`
  - [ ] `.gitignore`
  - [ ] `SYSTEM_OVERVIEW.md`
- [ ] Confirm these are NOT present in the repository (they must be in `.gitignore`):
  - [ ] `backend/venv/`
  - [ ] `frontend/node_modules/`
  - [ ] `backend/.env` (secrets)
  - [ ] `backend/__pycache__/`
  - [ ] `backend/flask_out.txt`
  - [ ] `backend/debug/`
  - [ ] `frontend/dist/`

---

## Phase 2 — Prerequisites on Target Machine

- [ ] Python 3.11+ installed (`python --version`)
- [ ] Node.js 18+ installed (`node --version`)
- [ ] npm installed (`npm --version`)
- [ ] PostgreSQL 15+ running and accessible
- [ ] Redis 7+ running and accessible
- [ ] Git installed (optional, for version control)

---

## Phase 3 — Environment Configuration

### Backend

- [ ] Copy `backend/.env.example` to `backend/.env`
- [ ] Set `SECRET_KEY` — generate: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Set `DATABASE_URL` — example: `postgresql://postgres:yourpassword@localhost:5432/stophunterpro`
- [ ] Set `REDIS_URL` — example: `redis://localhost:6379/0`
- [ ] Set `CELERY_BROKER_URL` — same as REDIS_URL or different DB index
- [ ] Set `CELERY_RESULT_BACKEND` — example: `redis://localhost:6379/1`
- [ ] Set `JWT_SECRET_KEY` — generate: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Set `RAZORPAY_KEY_ID` — from Razorpay dashboard
- [ ] Set `RAZORPAY_KEY_SECRET` — from Razorpay dashboard
- [ ] Set `RAZORPAY_WEBHOOK_SECRET` — from Razorpay dashboard
- [ ] Set `CORS_ORIGINS` — the frontend URL (e.g., `http://localhost:3000` or production URL)
- [ ] Set `FLASK_ENV` — `development` for local, `production` for server
- [ ] (Optional) Set `BREVO_API_KEY` and `BREVO_ENABLED=true` for transactional email
- [ ] (Optional) Set `DASHBOARD_URL` for email alert links

### Frontend

- [ ] Check `frontend/.env.example` — no changes typically needed for local dev
- [ ] For production: set `VITE_API_URL` to the backend URL if not using a proxy

---

## Phase 4 — Database Setup

- [ ] Create the PostgreSQL database:
  ```sql
  CREATE DATABASE stophunterpro;
  ```
- [ ] Run all migrations:
  ```bash
  cd backend
  venv\Scripts\flask db upgrade
  ```
- [ ] Verify migration head:
  ```bash
  venv\Scripts\flask db current
  # Should show: m3n4o5p6q7r8 (head)
  ```
- [ ] Confirm all 13 migrations applied (check `alembic_version` table)

### Migration chain verification

All 13 migration files must be present in `backend/migrations/versions/`:
- [ ] `fd7589117cee_initial_schema.py`
- [ ] `c3d4e5f6a7b8_extend_scan_tables.py`
- [ ] `d4e5f6a7b8c9_add_progression_to_scan_results.py`
- [ ] `e5de22952863_add_nse_universe_tables.py`
- [ ] `e5f6a7b8c9d0_add_scanner_notifications.py`
- [ ] `f6a7b8c9d0e1_add_user_tracked_symbols.py`
- [ ] `g7b8c9d0e1f2_add_alert_preferences.py`
- [ ] `h8c9d0e1f2g3_add_email_alerts.py`
- [ ] `i9c0d1e2f3g4_add_scan_health.py`
- [ ] `j0d1e2f3g4h5_add_max_pain_history.py`
- [ ] `k1e2f3g4h5i6_add_top_pain_strikes.py`
- [ ] `l2m3n4o5p6q7_add_regime_snapshots.py`
- [ ] `m3n4o5p6q7r8_add_scan_snapshots.py`

---

## Phase 5 — Installation

### Option A — Automated (recommended)

```powershell
.\bootstrap.ps1 -SeedData
```

### Option B — Manual

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\flask db upgrade

# Frontend
cd ..\frontend
npm install
```

---

## Phase 6 — Seed Development Data

- [ ] Seed plans, roles, and tools:
  ```bash
  cd backend
  venv\Scripts\flask seed-db
  ```
- [ ] Create a dev user:
  ```bash
  venv\Scripts\flask create-dev-user
  ```
- [ ] (Optional) Seed a scan snapshot for market-closed UI testing:
  ```bash
  venv\Scripts\flask seed-scan-snapshot
  ```

---

## Phase 7 — Startup Verification

### Start backend

```bash
cd backend
venv\Scripts\python run.py
```

Expected output:
```
* Running on http://127.0.0.1:5000
* Debug mode: on
```

### Health check

```
curl http://localhost:5000/api/health
```

Expected: `{"status": "ok"}`

### Start frontend

```bash
cd frontend
npm run dev
```

Expected:
```
VITE v6.x.x  ready in Xms
Local:   http://localhost:3000/
```

---

## Phase 8 — Functional Verification

### Auth

- [ ] Register a new account at `http://localhost:3000/register`
- [ ] Verify OTP (check Flask console if BREVO_ENABLED=false)
- [ ] Login successfully
- [ ] Check JWT refresh works (access token expires after 15 min by default)

### Scanner

- [ ] Navigate to the Max Pain Scanner page
- [ ] Click "Run Scan" with default threshold (2%)
- [ ] Verify diagnostics panel shows scan metrics
- [ ] If market closed: verify snapshot banner appears (blue) with SNAPSHOT badge
- [ ] Check browser devtools Console for `[Scanner] runScan response` log group

### Snapshot fallback

- [ ] Run: `curl http://localhost:5000/api/max-pain/debug/snapshots`
- [ ] Confirm `total_snapshots` > 0
- [ ] During market hours: scan shows live data
- [ ] Outside market hours: scan shows snapshot banner

### Celery (optional but required for production)

- [ ] Start worker: `celery -A celery_worker.celery worker --loglevel=info --pool=solo`
- [ ] Start beat: `celery -A celery_worker.celery beat --loglevel=info`
- [ ] Verify max pain snapshots captured every 5 minutes (check `max_pain_snapshots` table)

---

## Phase 9 — Production Hardening (if deploying to server)

- [ ] Set `FLASK_ENV=production`
- [ ] Set `FLASK_DEBUG=0`
- [ ] Generate new `SECRET_KEY` and `JWT_SECRET_KEY` (never reuse dev keys)
- [ ] Use environment variables or secrets manager instead of `.env` file
- [ ] Set `CORS_ORIGINS` to the production frontend domain
- [ ] Configure nginx/Caddy to reverse-proxy `/api` to Flask
- [ ] Configure SSL/TLS on the reverse proxy
- [ ] Set `SESSION_COOKIE_SECURE=True` (handled by ProductionConfig)
- [ ] Set `BREVO_ENABLED=true` and configure real API key
- [ ] Set `DASHBOARD_URL` to the production frontend URL
- [ ] Use `gunicorn` instead of Flask dev server:
  ```bash
  gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
  ```
- [ ] Set up a process manager (systemd, supervisor, PM2) for Flask, Celery worker, and Celery beat

---

## Phase 10 — Tests

- [ ] Run full test suite:
  ```bash
  cd backend
  venv\Scripts\python -m pytest tests/ -q
  ```
- [ ] Confirm all 702 tests pass
- [ ] No tests require external DB or Redis (tests use in-memory SQLite)

---

## Important Files Inventory

### Backend

| File | Purpose |
|------|---------|
| `backend/run.py` | Flask app entry point |
| `backend/celery_worker.py` | Celery worker entry point |
| `backend/app/__init__.py` | App factory (`create_app`) |
| `backend/app/config.py` | Configuration (reads env vars) |
| `backend/app/extensions.py` | Flask extensions (db, jwt, celery, ...) |
| `backend/app/commands.py` | CLI commands (seed-db, inspect-snapshots, ...) |
| `backend/requirements.txt` | Python dependencies |
| `backend/.env.example` | Environment template (safe to commit) |
| `backend/migrations/` | All 13 Alembic migrations |
| `backend/tests/` | 702 tests across 10 test files |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/main.jsx` | React entry point |
| `frontend/src/App.jsx` | Router + auth wrapper |
| `frontend/src/api/client.js` | Axios client with JWT interceptor |
| `frontend/src/context/AuthContext.jsx` | Auth state & token management |
| `frontend/src/pages/MaxPainScannerPage.jsx` | Main scanner UI with snapshot fallback |
| `frontend/package.json` | Node dependencies |
| `frontend/package-lock.json` | Locked dependency versions |
| `frontend/vite.config.js` | Vite configuration (port 3000, API proxy) |

### Root

| File | Purpose |
|------|---------|
| `start.bat` | Windows dev launcher (opens two console windows) |
| `bootstrap.ps1` | PowerShell setup script |
| `.gitignore` | Excludes venv, node_modules, .env, debug, dist, ... |
| `README.md` | Getting started guide |
| `SYSTEM_OVERVIEW.md` | Architectural reference |
| `PROJECT_TRANSFER_CHECKLIST.md` | This file |

---

## Ports Used

| Port | Service |
|------|---------|
| 5000 | Flask backend |
| 3000 | Vite dev server (frontend) |
| 5432 | PostgreSQL |
| 6379 | Redis |

---

## Environment Variables — Complete Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FLASK_ENV` | Yes | `development` | `development` / `production` |
| `FLASK_DEBUG` | No | `1` in dev | `0` in production |
| `SECRET_KEY` | **Required** | — | Flask signing key |
| `DATABASE_URL` | **Required** | — | PostgreSQL connection string |
| `REDIS_URL` | **Required** | — | Redis URL |
| `CELERY_BROKER_URL` | **Required** | — | Redis URL for Celery broker |
| `CELERY_RESULT_BACKEND` | **Required** | — | Redis URL for task results |
| `JWT_SECRET_KEY` | **Required** | — | JWT signing secret |
| `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` | No | `15` | Access token TTL |
| `JWT_REFRESH_TOKEN_EXPIRES_DAYS` | No | `30` | Refresh token TTL |
| `RAZORPAY_KEY_ID` | **Required** | — | Razorpay API key |
| `RAZORPAY_KEY_SECRET` | **Required** | — | Razorpay secret |
| `RAZORPAY_WEBHOOK_SECRET` | **Required** | — | Razorpay webhook validation |
| `BREVO_API_KEY` | Optional | `""` | Brevo email API key |
| `BREVO_SENDER_EMAIL` | Optional | `""` | From email address |
| `BREVO_SENDER_NAME` | Optional | `Stop Hunter Pro` | From display name |
| `BREVO_ENABLED` | Optional | `false` | Enable Brevo (OTP in console if false) |
| `MAIL_SERVER` | Optional | — | SMTP server (alternative to Brevo) |
| `MAIL_PORT` | Optional | — | SMTP port |
| `MAIL_USE_TLS` | Optional | — | SMTP TLS |
| `MAIL_USERNAME` | Optional | — | SMTP username |
| `MAIL_PASSWORD` | Optional | — | SMTP password |
| `MAIL_DEFAULT_SENDER` | Optional | — | SMTP from address |
| `RATELIMIT_STORAGE_URI` | Optional | `REDIS_URL` | Rate limit storage (defaults to REDIS_URL) |
| `OTP_EXPIRES_MINUTES` | No | `10` | OTP validity window |
| `OTP_MAX_ATTEMPTS` | No | `5` | Max OTP verification attempts |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated allowed origins |
| `DASHBOARD_URL` | No | `""` | Frontend URL for email links |
| `MAX_PAIN_RETENTION_DAYS` | No | `90` | Max pain snapshot retention |

---

## Known Limitations

| Limitation | Detail |
|------------|--------|
| Market hours dependency | NSE data only available Mon–Fri 09:15–15:30 IST. Snapshot fallback covers off-hours. |
| Windows terminal encoding | CLI commands use ASCII-only output to avoid CP1252 encoding errors |
| Celery on Windows | Must use `--pool=solo` (prefork not supported on Windows) |
| TLS fingerprinting | NSE requires `curl_cffi` with `impersonate="chrome124"`. Standard HTTP clients are rejected with 403. |
| `psycopg2-binary` | Pre-compiled binary for easy install. On Linux, may need `psycopg2` compiled from source for better performance. |
| Float threshold matching | Snapshot threshold matching uses `abs(stored - requested) < 0.01` to avoid IEEE-754 issues |
| No WebSockets | Real-time updates use polling (auto-refresh interval). WebSocket support not implemented. |
| Single-region | No geographic redundancy in current setup. |
