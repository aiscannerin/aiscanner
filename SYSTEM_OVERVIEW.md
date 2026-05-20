# Stop Hunter Pro — System Overview

Complete architectural reference for developers.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Backend Layer Structure](#2-backend-layer-structure)
3. [Database Schema](#3-database-schema)
4. [Authentication Flow](#4-authentication-flow)
5. [NSE Fetch Layer](#5-nse-fetch-layer)
6. [Scanner Pipeline](#6-scanner-pipeline)
7. [Snapshot Fallback System](#7-snapshot-fallback-system)
8. [Max Pain Engine](#8-max-pain-engine)
9. [Celery Task System](#9-celery-task-system)
10. [Frontend Architecture](#10-frontend-architecture)
11. [API Endpoints Reference](#11-api-endpoints-reference)
12. [Debug Endpoints](#12-debug-endpoints)
13. [Telemetry System](#13-telemetry-system)
14. [Configuration Reference](#14-configuration-reference)

---

## 1. High-Level Architecture

```
Browser (React 18 / Vite)
    |
    | HTTP/JSON  (JWT Bearer token in every request)
    |
Flask API (port 3010)
    |         |
    |         +-- PostgreSQL (primary data store)
    |         |
    |         +-- Redis (session cache, rate limiting, Celery broker)
    |         |
    |         +-- NSE API (option chain data, via curl_cffi)
    |
Celery Worker + Beat (background tasks)
    |
    +-- Max pain snapshot capture (every 5 min)
    +-- Daily cleanup (every 24 h)
```

**Request flow:**
1. Frontend sends JWT Bearer token with every API request
2. Flask-JWT-Extended validates the token
3. Route handler calls the service layer
4. Service calls repositories (DB) or external providers (NSE)
5. Response is serialized and returned as JSON
6. Frontend unwraps the `{ success, data, meta }` envelope

---

## 2. Backend Layer Structure

```
app/
├── api/          Routes (HTTP ↔ service boundary)
├── services/     Business logic (no DB access, calls repositories)
├── repositories/ Data access (ORM queries only, no logic)
├── models/       SQLAlchemy ORM models (schema definition)
├── tasks/        Celery async tasks
├── providers/    External data sources (NSE, yfinance)
├── middleware/   Auth guards and tool-access checks
└── utils/        Shared utilities (response helpers, validators)
```

**Dependency rule:** Routes → Services → Repositories → Models.
Services must never import routes. Models must never import services.

---

## 3. Database Schema

### Core user & auth tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts (email, hashed password, verification status) |
| `roles` | Roles (admin, user) |
| `refresh_tokens` | JWT refresh token rotation log |
| `otp_verifications` | Email OTP records for registration / password reset |

### Subscription & billing

| Table | Purpose |
|-------|---------|
| `plans` | Pricing tiers (Free, Pro, Premium) |
| `tools` | Feature flags / tools available in the system |
| `plan_tool_map` | Which tools each plan includes |
| `subscriptions` | User plan enrollments |
| `payments` | Razorpay transaction records |

### Scanner & alerts

| Table | Purpose |
|-------|---------|
| `scan_jobs` | Scan execution records |
| `scan_results` | Per-symbol scan output rows |
| `scan_snapshots` | Full universe scan snapshots (for market-closed fallback) |
| `scanner_notifications` | Alert delivery records |
| `user_alert_settings` | Per-user alert configuration |
| `user_tracked_symbols` | User watchlist |

### Market data & analysis

| Table | Purpose |
|-------|---------|
| `max_pain_snapshots` | 5-minute max pain data points (captured by Celery) |
| `regime_snapshots` | Market regime classification records |
| `nse_stocks` | NSE stock metadata cache |
| `nse_universes` | F&O universe definitions |
| `nse_universe_stocks` | Stock membership in each universe |

### Migration chain (in order)

```
fd7589117cee  initial_schema
c3d4e5f6a7b8  extend_scan_tables
d4e5f6a7b8c9  add_progression_to_scan_results
e5de22952863  add_nse_universe_tables
e5f6a7b8c9d0  add_scanner_notifications
f6a7b8c9d0e1  add_user_tracked_symbols
g7b8c9d0e1f2  add_alert_preferences
h8c9d0e1f2g3  add_email_alerts
i9c0d1e2f3g4  add_scan_health
j0d1e2f3g4h5  add_max_pain_history
k1e2f3g4h5i6  add_top_pain_strikes
l2m3n4o5p6q7  add_regime_snapshots
m3n4o5p6q7r8  add_scan_snapshots          ← most recent
```

---

## 4. Authentication Flow

### Registration

```
POST /api/auth/register
  → create user (unverified)
  → generate 6-digit OTP
  → send OTP via Brevo (or print to console if BREVO_ENABLED=false)

POST /api/auth/verify-otp
  → validate OTP (expiry + attempt count)
  → mark user verified
  → issue access token (15 min) + refresh token (30 days)
```

### Login

```
POST /api/auth/login
  → validate email + bcrypt password check
  → require verified account
  → issue access token + refresh token
  → store refresh token in DB for rotation tracking
```

### Token refresh

```
POST /api/auth/refresh
  Authorization: Bearer <refresh_token>
  → validate refresh token against DB record
  → rotate: invalidate old, issue new pair
  → prevents replay attacks
```

### Protected routes

All scanner and data endpoints require:
```
Authorization: Bearer <access_token>
```

JWT errors return structured responses:
```json
{ "success": false, "error_code": "TOKEN_EXPIRED", "message": "..." }
```

---

## 5. NSE Fetch Layer

**File:** `app/services/nse_option_chain_service.py`

### Why `curl_cffi`?

NSE uses TLS fingerprinting to block non-browser clients. Standard `requests` and `httpx` are rejected with 403. `curl_cffi` with `impersonate="chrome124"` presents a real Chrome TLS handshake and passes NSE's checks.

### Payload detection

NSE sometimes returns the option chain data nested at different levels:

```python
def _detect_response_type(data):
    # Type A: data["records"]["data"] — standard shape
    # Type B: data["data"]           — alternate shape
    # Type C: data itself is list    — raw array
    # Empty:  {} or {"status":"market closed"} → NSEMarketClosedError
```

### Market closed detection

When NSE market is closed (outside 09:15–15:30 IST, Mon–Fri), the API returns `{}` or an empty records structure. The service raises `NSEMarketClosedError`, which the scanner places in the `market_closed` list (not the `errors` list).

### Retry logic

Each symbol fetch retries up to 3 times with exponential backoff. `NSEMarketClosedError` is NOT retried — it short-circuits immediately.

### Adaptive throttling

Between symbol fetches, a random delay of `uniform(0.5, 1.5)` seconds prevents rate limiting. The delay is logged as `[THROTTLE]` for visibility.

---

## 6. Scanner Pipeline

**File:** `app/services/max_pain_scanner_service.py`

**Endpoint:** `GET /api/max-pain/scan?threshold=2.0`

### Execution flow

```
run_scanner(symbols, threshold_pct, expiry, max_workers=6)
    |
    +-- ThreadPoolExecutor (6 workers)
    |   |
    |   +-- _scan_symbol_internal(symbol)
    |       |
    |       +-- get_option_chain(symbol)     # NSE fetch layer
    |       +-- calculate_max_pain(chain)    # max pain engine
    |       +-- get_oi_walls(chain)          # OI wall detection
    |       +-- reversal_probability(...)    # reversal scoring
    |       |
    |       Returns:
    |         symbol, spot_price, max_pain, distance_pct,
    |         reversal_score, conviction, pcr, avg_iv,
    |         ce_wall, pe_wall, expiry
    |
    +-- Aggregate results
    +-- Filter by threshold (distance_pct >= threshold_pct)
    +-- Sort by reversal_score descending
    |
    Returns:
      results:         list of hits above threshold
      errors:          list of {symbol, error} for fetch failures
      below_threshold: list of symbols that fetched OK but below threshold
      market_closed:   list of symbols that returned NSEMarketClosedError
      summary:         { total_scanned, total_hits, total_below_threshold }
      metrics:         { avg_fetch_ms, scan_elapsed_ms, fetch_success,
                         fetch_failed, market_closed, symbols_total,
                         threshold_filtered, returned_results }
```

### Scan result fields

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | NSE ticker |
| `spot_price` | float | Current underlying price |
| `max_pain` | float | Max pain strike price |
| `distance_pct` | float | `abs(spot - max_pain) / max_pain * 100` |
| `reversal_score` | int 0–100 | Composite reversal probability |
| `conviction` | string | `"strong"` / `"moderate"` / `"weak"` |
| `pcr` | float | Put-call ratio |
| `avg_iv` | float | Average implied volatility |
| `direction` | string | `"bullish"` / `"bearish"` |
| `ce_wall` | object | Largest call OI strike |
| `pe_wall` | object | Largest put OI strike |
| `expiry` | string | Option expiry date |

---

## 7. Snapshot Fallback System

### Purpose

NSE option chain data is only available during market hours (Mon–Fri 09:15–15:30 IST). Outside these hours, the scanner returns empty results. The snapshot system stores the last successful scan and serves it as a fallback so the UI remains useful 24/7.

### Components

**Model:** `app/models/scan_snapshot.py` — `scan_snapshots` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `created_at` | DateTime (UTC) | Snapshot timestamp |
| `threshold` | Float | Threshold % used for the scan |
| `symbol_count` | Integer | Number of result rows |
| `avg_fetch_ms` | Float | Average NSE fetch time |
| `scan_elapsed_ms` | Float | Total scan wall-clock time |
| `market_status` | String | `"open"` / `"closed"` / `"unknown"` |
| `payload_json` | Text | Full `run_scanner()` response as JSON |

**Service:** `app/services/scan_snapshot_service.py`

- `save_scan_snapshot(scan_response, threshold)` — persists after every successful live scan
- `get_latest_snapshot(threshold=None)` — two-step lookup: approx threshold match → any-threshold fallback
- `get_snapshot_history(limit=20)` — returns metadata list (no payload)
- `load_snapshot_payload(snapshot)` — deserializes `payload_json`
- `count_snapshots()` — total row count

### Fallback trigger (backend `/scan` route)

The fallback activates whenever `has_live_data = False`, regardless of reason:

```python
if not has_live_data:
    # Reason logged: market_closed(N) / nse_errors(N) / no_results
    snapshot = get_latest_snapshot(threshold=threshold)
    if snapshot is not None:
        result = load_snapshot_payload(snapshot)
        using_snapshot = True
```

The response envelope always includes:
```json
{
  "using_snapshot_fallback": true,
  "snapshot_age_minutes": 26.1,
  "snapshot_created_at": "2026-05-20T13:30:00+00:00",
  "snapshot_fallback_reason": "market_closed(46)"
}
```

### Threshold matching

Exact float equality is not used. Instead:
```python
func.abs(ScanSnapshot.threshold - threshold) < 0.01
```

If no approx match is found, falls back to the newest row of any threshold.

### Frontend behaviour

When `using_snapshot_fallback: true`:
1. Blue `SNAPSHOT` badge replaces the `LIVE` badge
2. Blue `SnapshotBanner` appears above the table with snapshot time and age
3. Auto-refresh is paused
4. `TelemetryBar` is hidden (live-scan metrics would be confusing)
5. Scanner table renders snapshot rows identically to live rows

### Seeding test snapshots

```bash
flask seed-scan-snapshot             # insert one fake snapshot
flask seed-scan-snapshot --overwrite # replace all snapshots with fresh seed
flask inspect-snapshots              # show DB diagnostics
```

---

## 8. Max Pain Engine

**File:** `app/services/max_pain_engine.py`

Max pain is the strike price at which option writers would lose the least money. It is calculated by:

1. For each strike, calculate total payout if spot expires there:
   - Call payout: `max(0, spot - strike) * call_OI`
   - Put payout:  `max(0, strike - spot) * put_OI`
2. Sum across all strikes
3. The strike with **minimum total payout** is max pain

### Reversal probability scoring

The `reversal_score` (0–100) is a composite of:
- Distance from max pain (higher distance → higher score)
- Put-Call ratio imbalance
- OI wall proximity (calls above spot, puts below)
- Average IV relative to historical
- Regime context (trending vs. range-bound)

---

## 9. Celery Task System

**Files:** `app/tasks/`, `celery_worker.py`

### Scheduled tasks (Celery Beat)

| Task | Schedule | Purpose |
|------|----------|---------|
| `capture_max_pain_snapshot` | Every 5 min | Store max pain data during market hours |
| `cleanup_snapshots` | Daily | Delete snapshots older than `MAX_PAIN_RETENTION_DAYS` (default 90) |

### Starting workers

```bash
# Worker (processes tasks)
celery -A celery_worker.celery worker --loglevel=info --pool=solo

# Beat scheduler (fires tasks on schedule)
celery -A celery_worker.celery beat --loglevel=info
```

**Note:** `--pool=solo` is required on Windows because the default prefork pool is not supported.

---

## 10. Frontend Architecture

### State management

No Redux or Zustand. State is managed via:
- `AuthContext` — JWT tokens, user profile, login/logout/refresh logic
- `ToastContext` — Non-blocking notification queue
- Local `useState` in page components for UI-local state

### Token refresh strategy

`api/client.js` uses an Axios response interceptor:
1. On 401 response → call `POST /api/auth/refresh` with refresh token
2. On success → store new tokens, retry original request
3. On failure → clear tokens, redirect to login

### Vite proxy

In development, Vite proxies `/api/*` to `http://localhost:3010` so there are no CORS issues during development. In production, configure a real reverse proxy (nginx/Caddy) to do the same.

### Key pages

| Page | Route | Auth Required |
|------|-------|--------------|
| `LandingPage` | `/` | No |
| `LoginPage` | `/login` | No |
| `RegisterPage` | `/register` | No |
| `DashboardPage` | `/dashboard` | Yes |
| `MaxPainScannerPage` | `/scanner/max-pain` | Yes |
| `ScannerPage` | `/scanner` | Yes |
| `PricingPage` | `/pricing` | No |
| `SettingsPage` | `/settings` | Yes |

---

## 11. API Endpoints Reference

### Auth — `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/register` | No | Create account, send OTP |
| POST | `/verify-otp` | No | Verify email OTP |
| POST | `/login` | No | Login, receive token pair |
| POST | `/refresh` | Refresh token | Rotate access + refresh tokens |
| POST | `/logout` | Access token | Invalidate refresh token |
| POST | `/forgot-password` | No | Send password reset OTP |
| POST | `/reset-password` | No | Reset password with OTP |

### Max Pain Scanner — `/api/max-pain`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/scan` | Yes | Full universe scanner with snapshot fallback |
| GET | `/symbol/<symbol>` | Yes | Single symbol detail |
| GET | `/universe` | Yes | Default F&O universe list |
| GET | `/snapshots/latest` | Yes | Latest scan snapshot (meta + payload) |
| GET | `/snapshots/history` | Yes | Snapshot history list (meta only) |

### Other endpoints (all `GET`, all `JWT` required unless noted)

| Path | Description |
|------|-------------|
| `GET /api/health` | Health check (no auth) |
| `GET /api/plans` | Pricing plans list |
| `GET /api/subscriptions/current` | Current user subscription |
| `GET /api/market-data/*` | Market data endpoints |
| `GET /api/scanners/*` | Scanner management |
| `GET /api/watchlist` | User tracked symbols |
| `GET /api/notifications` | User notifications |
| `GET /api/alert-settings` | User alert preferences |
| `GET /api/max-pain/history/*` | Max pain history analysis |
| `GET /api/max-pain/regime/*` | Market regime classification |
| `GET /api/max-pain/trade/*` | Trade simulation |
| `GET /api/max-pain/portfolio/*` | Portfolio analysis |
| `GET /api/max-pain/monte-carlo/*` | Monte Carlo simulation |
| `GET /api/max-pain/research/*` | Research engine |
| `GET /api/max-pain/walkforward/*` | Walk-forward analysis |

---

## 12. Debug Endpoints

These require no JWT and are intended for development/diagnosis:

| Path | Description |
|------|-------------|
| `GET /api/max-pain/debug/nse-status` | NSE connectivity probe + cache stats |
| `GET /api/max-pain/debug/live-scan` | Live scan of 10 symbols (real NSE data) |
| `GET /api/max-pain/debug/test-symbol/<symbol>` | Full diagnostic for one symbol |
| `GET /api/max-pain/debug/raw-scan` | Scan at 0% threshold (all symbols) |
| `GET /api/max-pain/debug/snapshots` | Snapshot store diagnostics (count, thresholds, newest meta) |

**Example: check if snapshot fallback is configured correctly:**
```
curl http://localhost:3010/api/max-pain/debug/snapshots
```

---

## 13. Telemetry System

Every scan response includes a `metrics` block inside `meta`:

```json
{
  "meta": {
    "metrics": {
      "symbols_total": 46,
      "fetch_success": 42,
      "fetch_failed": 2,
      "market_closed": 2,
      "threshold_filtered": 35,
      "returned_results": 7,
      "avg_fetch_ms": 312.4,
      "scan_elapsed_ms": 4820.1
    }
  }
}
```

The `TelemetryBar` component in `MaxPainScannerPage.jsx` renders this as a one-line chip strip below the control bar. It is hidden when serving snapshot fallback data (the metrics would reflect the empty live scan, not the snapshot).

Flask logs every decision branch with structured prefixes:
- `[SCAN /scan]` — scanner route
- `[snapshot.save]` — save path
- `[snapshot.get]` — lookup path with step-by-step fallback logging
- `[snapshot.load]` — payload deserialization
- `[NSE]` — NSE fetch layer
- `[SCAN]` — per-symbol scanner

---

## 14. Configuration Reference

See `backend/app/config.py` for the full config class hierarchy:

```
BaseConfig
├── DevelopmentConfig  (FLASK_ENV=development)
├── TestingConfig      (FLASK_ENV=testing, in-memory SQLite, rate limiting disabled)
└── ProductionConfig   (secure cookies, no debug)
```

`get_config()` selects the class based on `FLASK_ENV`.

All required variables are read via `_require(key)` which raises a clear `EnvironmentError` at startup if missing — preventing silent misconfigurations.
