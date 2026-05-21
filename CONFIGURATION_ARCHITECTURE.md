# Configuration Architecture — Stop Hunter Pro

This document explains how configuration is managed across environments,
which files must stay identical in git, and how to safely deploy updates.

---

## 1. Two Environments

| | Local Development | Production Server |
|--|--|--|
| **Machine** | Mum PC (coding machine) | Windows Server 2022 |
| **Path** | `C:\Users\Admin\Desktop\New Claude code\Stp hunter pro` | `D:\stop_hunt_pro\stop hunter pro 02\aiscanner` |
| **Network** | localhost only | LAN + Cloudflare Tunnel → `aiscanner.in` |
| **Flask env** | `development` | `production` |
| **Debug mode** | `FLASK_DEBUG=1` | `FLASK_DEBUG=0` |
| **CORS origins** | `http://localhost:3000` | `http://localhost:3000,https://aiscanner.in` |
| **Dashboard URL** | `http://localhost:3000` | `https://aiscanner.in` |
| **Brevo email** | Disabled (`BREVO_ENABLED=false`) | Enabled (`BREVO_ENABLED=true`) |
| **DB password** | local postgres password | server postgres password |

---

## 2. Standard Ports (non-negotiable)

| Service | Port |
|--|--|
| **Frontend (Vite)** | `3000` |
| **Backend (Flask)** | `3010` |

These ports are set in:
- `vite.config.js` → `server.port: 3000`
- `backend/run.py` → `os.getenv("PORT", 3010)`
- `backend/.env` → `PORT=3010` (optional override)
- `start_servers.cmd` / `stop_servers.cmd` → hardcoded constants

To change a port: update the `.env` file AND `vite.config.js`.

---

## 3. File Classification

### ✅ Must be IDENTICAL in git (committed, same on every machine)

| File | What it controls |
|--|--|
| `frontend/vite.config.js` | Vite server config, proxy, host/allowedHosts |
| `backend/app/config.py` | Python config classes, env var loading |
| `backend/run.py` | Flask startup, reads `PORT` from env |
| `backend/requirements.txt` | Python dependencies |
| `frontend/package.json` | Node dependencies |
| `frontend/package-lock.json` | Locked Node versions |
| `start_servers.cmd` | Server startup script |
| `stop_servers.cmd` | Server stop script |
| `update_and_restart.cmd` | Update + restart script |
| `bootstrap.ps1` | First-time environment setup |
| `.gitignore` | What git ignores |
| All `backend/migrations/` | Database schema history |
| All `backend/app/` source code | Application logic |
| All `frontend/src/` source code | UI code |
| `backend/.env.example` | Master template with all variables documented |
| `backend/.env.local.example` | Local dev values template |
| `backend/.env.server.example` | Server values template |
| `frontend/.env.example` | Frontend env template |
| `frontend/.env.local.example` | Frontend local template |
| `frontend/.env.server.example` | Frontend server template |

### 🔒 Machine-specific — NEVER committed (in .gitignore)

| File | Who creates it | Why it differs |
|--|--|--|
| `backend/.env` | Each machine manually | Different DB passwords, secrets, Razorpay keys, CORS origins |
| `frontend/.env` | Each machine manually | Usually just `VITE_API_URL=/api` (same), but still machine-managed |
| `backend/venv/` | `bootstrap.ps1` or manual | Python virtual environment — machine-specific binaries |
| `frontend/node_modules/` | `npm install` | Node dependencies — machine-specific paths |
| `backend/logs/` | Created at runtime | Log files are per-machine |
| `frontend/logs/` | Created at runtime | Log files are per-machine |
| `update.log` | Created at runtime | Update history is per-machine |

---

## 4. Setting Up a New Machine

### First time (bootstrap):
```
git clone <repo-url> .
.\bootstrap.ps1
```

`bootstrap.ps1` will:
1. Check Python and Node are installed
2. Create `backend/venv` (if missing)
3. Install Python dependencies
4. Copy `backend/.env.example` → `backend/.env` (if `.env` is missing)
5. Run `flask db upgrade`
6. Install npm dependencies

After bootstrap completes, **edit `backend/.env`** with your machine's real values:
- For local dev → use `backend/.env.local.example` as a guide
- For the server → use `backend/.env.server.example` as a guide

Also create `frontend/.env`:
- Copy `frontend/.env.example` → `frontend/.env`
- Both environments use `VITE_API_URL=/api` (no change needed)

### Start:
```
start_servers.cmd
```

---

## 5. Server-Specific .env Checklist

When setting up or updating the server's `backend/.env`, verify these values:

```
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=<long random string, min 32 chars>
DATABASE_URL=postgresql://postgres:<URL-encoded-password>@localhost:5432/stophunterpro
JWT_SECRET_KEY=<different long random string>
RAZORPAY_KEY_ID=<real rzp_test_ or rzp_live_ key>
RAZORPAY_KEY_SECRET=<real secret>
RAZORPAY_WEBHOOK_SECRET=<real webhook secret>
BREVO_API_KEY=<real xkeysib-... key>
BREVO_SENDER_EMAIL=aiscannerin@gmail.com
BREVO_ENABLED=true
CORS_ORIGINS=http://localhost:3000,https://aiscanner.in
DASHBOARD_URL=https://aiscanner.in
MAX_PAIN_RETENTION_DAYS=90
PORT=3010
```

> **Note on URL-encoding**: If your PostgreSQL password contains `@`, encode it as `%40`.
> Example: `Confirm@123` → `Confirm%40123`

---

## 6. Cloudflare Tunnel Compatibility

The following settings ensure `aiscanner.in` works through Cloudflare Tunnel:

### `frontend/vite.config.js`
```js
server: {
  host: '0.0.0.0',      // bind all interfaces — required for Tunnel
  port: 3000,
  allowedHosts: true,   // accept any hostname (aiscanner.in, LAN IPs, localhost)
  proxy: {
    '/api': {
      target: 'http://localhost:3010',
      changeOrigin: true,
    },
  },
}
```

**Do NOT** remove `host: '0.0.0.0'` or `allowedHosts: true` — they are required
for external access through Cloudflare Tunnel and LAN.

### `backend/.env` (server)
```
CORS_ORIGINS=http://localhost:3000,https://aiscanner.in
DASHBOARD_URL=https://aiscanner.in
```

The `CORS_ORIGINS` value is read in `backend/app/config.py` and split on commas:
```python
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
```

---

## 7. Safe Git Workflow

### On the dev machine (Mum PC):
```bash
# Make changes
git add <specific files>   # Never: git add -A (risk of committing .env)
git commit -m "description"
git push origin main
```

### Things to NEVER commit:
- `backend/.env` (real secrets)
- `frontend/.env`
- `backend/venv/`
- `frontend/node_modules/`
- `*.log`, `update.log`
- `__pycache__/`, `*.pyc`

### Safe check before committing:
```bash
git status   # Verify no .env files appear as staged
git diff --cached   # Review exactly what is being committed
```

---

## 8. Server Update Workflow

### Standard update (most common):
```
update_and_restart.cmd
```

This script:
1. Stops running servers
2. `git pull origin main`
3. `pip install` only if `requirements.txt` changed
4. `npm install` only if `package-lock.json` changed
5. `flask db upgrade` (always — idempotent)
6. Restarts servers

### After pulling changes that affect `.env` variables:

If new environment variables were added to `.env.example`, you must manually
add them to the server's `backend/.env` **before** running the update:

1. Check `backend/.env.example` for new variables
2. Check `backend/.env.server.example` for recommended server values
3. Update the server's `backend/.env` accordingly
4. Then run `update_and_restart.cmd`

### Manual steps (if something breaks):
```
stop_servers.cmd
git pull origin main
cd backend && venv\Scripts\pip install -r requirements.txt
cd backend && venv\Scripts\flask db upgrade
start_servers.cmd
```

---

## 9. Adding a New Environment Variable

When adding a new env var to the codebase:

1. Add it to `backend/app/config.py` (read from `os.getenv(...)`)
2. Add it to `backend/.env.example` with a placeholder and comment
3. Add it to `backend/.env.local.example` with a sensible dev default
4. Add it to `backend/.env.server.example` with the production value
5. Update your local `backend/.env` with the value
6. Notify that the server's `backend/.env` also needs updating
7. Commit `.env.example`, `.env.local.example`, `.env.server.example` — never `.env`

---

## 10. Quick Reference

| Task | Command |
|--|--|
| First-time setup | `.\bootstrap.ps1` |
| Start servers | `start_servers.cmd` |
| Stop servers | `stop_servers.cmd` |
| Update + restart | `update_and_restart.cmd` |
| Run migrations only | `cd backend && venv\Scripts\flask db upgrade` |
| View backend log | `notepad backend\logs\backend.log` |
| View frontend log | `notepad frontend\logs\frontend.log` |
| View update log | `notepad update.log` |
