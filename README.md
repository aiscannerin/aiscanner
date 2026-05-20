# Stop Hunter Pro

Full-stack options trading analysis platform for Indian markets (NSE F&O).

Provides max pain analysis, reversal probability scoring, market-closed snapshot fallback, portfolio simulation, and subscription management.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13 · Flask 3.1 · SQLAlchemy 2.0 · Alembic |
| Database | PostgreSQL 15+ |
| Cache / Broker | Redis 7+ |
| Task Queue | Celery 5.6 |
| Frontend | React 18 · Vite 6 · TailwindCSS 3 |
| Auth | JWT (access + refresh) · Bcrypt · OTP via Brevo |
| Payments | Razorpay |
| Market Data | NSE Option Chain API via `curl_cffi` |

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | 3.13 recommended |
| Node.js | 18+ | 20 LTS recommended |
| PostgreSQL | 15+ | Local or hosted |
| Redis | 7+ | Local or hosted |

---

## Quick Start (Windows)

### 1. Clone / copy the repository

```
git clone <your-repo-url>
cd "Stp hunter pro"
```

### 2. Run the bootstrap script

```powershell
.\bootstrap.ps1
```

This script will:
- Create the Python virtual environment
- Install all backend dependencies
- Install all frontend dependencies
- Run all database migrations
- Optionally seed dev data

### 3. Configure environment variables

```
copy backend\.env.example backend\.env
# Edit backend\.env — fill in SECRET_KEY, DATABASE_URL, JWT_SECRET_KEY, etc.
```

### 4. Start the development servers

```
start.bat
```

Opens two console windows:
- **Backend** on http://localhost:5000
- **Frontend** on http://localhost:3000

---

## Manual Setup (Step-by-Step)

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your values

# Run database migrations
flask db upgrade

# (Optional) Seed dev data
flask seed-db

# Start Flask dev server
python run.py
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start Vite dev server (proxies /api to localhost:5000)
npm run dev
```

### Celery (Background Tasks)

Required for max pain snapshot capture every 5 minutes:

```bash
cd backend

# Worker (processes tasks)
celery -A celery_worker.celery worker --loglevel=info --pool=solo

# Beat (scheduler — runs tasks on schedule)
celery -A celery_worker.celery beat --loglevel=info
```

---

## Environment Variables

See `backend/.env.example` for all required variables with descriptions.

### Required (app will not start without these)

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask secret key (32+ random chars) |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `CELERY_BROKER_URL` | Redis URL for Celery broker |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery results |
| `JWT_SECRET_KEY` | JWT signing secret (32+ random chars) |
| `RAZORPAY_KEY_ID` | Razorpay API key |
| `RAZORPAY_KEY_SECRET` | Razorpay secret |
| `RAZORPAY_WEBHOOK_SECRET` | Razorpay webhook secret |

### Optional (have safe defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_ENV` | `development` | `development` / `production` |
| `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` | `15` | Access token TTL |
| `JWT_REFRESH_TOKEN_EXPIRES_DAYS` | `30` | Refresh token TTL |
| `BREVO_ENABLED` | `false` | Enable Brevo transactional email |
| `BREVO_API_KEY` | `""` | Brevo API key (required if enabled) |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `OTP_EXPIRES_MINUTES` | `10` | OTP validity window |
| `MAX_PAIN_RETENTION_DAYS` | `90` | Days to keep max pain snapshots |

---

## Database Migrations

All 13 migrations are included in `backend/migrations/versions/`. Apply them in order:

```bash
flask db upgrade        # applies all pending migrations
flask db current        # shows current revision
flask db history        # shows full migration chain
```

To roll back one step:
```bash
flask db downgrade -1
```

---

## CLI Commands

```bash
flask seed-db                        # seed plans, roles, tools
flask seed-scan-snapshot             # insert a fake scan snapshot for UI testing
flask seed-scan-snapshot --overwrite # replace all snapshots with fresh seed
flask inspect-snapshots              # print snapshot store diagnostics
flask nse status                     # test NSE connectivity
flask nse fetch NIFTY                # fetch option chain for one symbol
flask create-dev-user                # create a test user account
flask verify-user <email>            # manually verify a user email
```

---

## Running Tests

```bash
cd backend

# All tests (702 tests)
venv\Scripts\python.exe -m pytest tests/ -q

# Specific module
venv\Scripts\python.exe -m pytest tests/test_scan_snapshot_service.py -v
```

Tests use an in-memory SQLite database — no PostgreSQL or Redis required.

---

## Ports

| Service | Port | Notes |
|---------|------|-------|
| Flask backend | 5000 | `python run.py` |
| Vite frontend | 3000 | `npm run dev` |
| PostgreSQL | 5432 | default |
| Redis | 6379 | default |

---

## Project Structure

```
Stp hunter pro/
├── backend/
│   ├── app/
│   │   ├── api/          # API blueprints (15 modules)
│   │   ├── models/       # SQLAlchemy models (19 models)
│   │   ├── services/     # Business logic (25+ services)
│   │   ├── repositories/ # Data access layer
│   │   ├── tasks/        # Celery async tasks
│   │   └── utils/        # Shared utilities
│   ├── migrations/       # Alembic migration files (13 revisions)
│   ├── tests/            # Test suite (702 tests)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios API modules
│   │   ├── components/   # React components
│   │   ├── pages/        # Page-level components
│   │   ├── context/      # Auth & Toast context
│   │   └── hooks/        # Custom hooks
│   ├── package.json
│   └── vite.config.js
├── bootstrap.ps1         # One-command setup script
├── start.bat             # Windows dev launcher
└── README.md
```

---

## Known Limitations

- NSE option chain data only available during market hours (Mon–Fri 09:15–15:30 IST)
- Celery Beat must run separately for scheduled max pain snapshots
- `curl_cffi` with `impersonate="chrome124"` is required for NSE TLS fingerprinting
- `psycopg2-binary` is Windows-friendly; Linux/Mac may need the `psycopg2` package instead
- Windows terminals with CP1252 encoding cannot display Unicode symbols in CLI output
