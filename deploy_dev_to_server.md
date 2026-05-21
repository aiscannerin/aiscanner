# Stop Hunter Pro — Dev → Server Deployment Workflow

Defines the exact process for pushing code changes from the development PC to the production Windows server. This is the only sanctioned deployment method.

---

## Architecture

```
DEV PC (Windows)                     SERVER PC (Windows Server 2022)
─────────────────                    ─────────────────────────────────
Claude edits files                   D:\stop_hunt_pro\
  ↓                                    stop hunter pro 02\
git add / commit / push                  aiscanner\            ← project root
  ↓                                        update_and_restart.cmd
GitHub (aiscannerin/aiscanner)           stop_servers.cmd
  ↑                                       start_servers.cmd
  └── git pull (done by update script)    backend\  (Flask :3010)
                                          frontend\ (Vite  :3000)
```

---

## The Only Workflow — Follow This Every Time

### On the DEV PC

1. **Edit code** locally with Claude Code or your editor.

2. **Test locally** — run the app on your dev machine first:
   ```
   .\start.bat
   ```

3. **Commit and push:**
   ```bash
   git add <files>
   git commit -m "your message"
   git push origin main
   ```

4. **Confirm the push succeeded** on GitHub before touching the server.

### On the SERVER PC

5. **Run a single command:**
   ```
   update_and_restart.cmd
   ```
   Double-click it, or run from an Administrator command prompt.

6. **Watch the output.** The script prints each step. Any failure is printed in red with an explanation.

7. **Check the log** if anything looks wrong:
   ```
   update.log               ← in the project root
   backend\logs\backend.log
   frontend\logs\frontend.log
   ```

That is the entire workflow. There are no other steps.

---

## What `update_and_restart.cmd` Does

| Step | Action | Skipped if... |
|------|--------|---------------|
| 1 | Stop servers (kill PIDs on ports 3010 + 3000) | — |
| 2 | `git pull origin main` | — |
| 3 | `pip install -r requirements.txt` | `requirements.txt` not changed |
| 4 | `npm install` | `package-lock.json` not changed |
| 5 | `flask db upgrade` | Never skipped — always runs (idempotent) |
| 6 | Start backend + frontend | — |

**If `git pull` fails:** servers are restarted on the previous version immediately. The server never goes dark.

---

## Safety Rules — Read These

> **Violating these rules can corrupt the database, cause data loss, or break the live server.**

### Never develop directly on the server

- Do not edit `.py`, `.jsx`, `.js`, `.json`, or any source file directly on the server PC.
- Do not use a mapped network drive to edit server files from the dev PC.
- The server's files are a clean clone from GitHub. Treat them as read-only.
- If you edit files directly on the server, `git pull` will conflict and the update script will fail.

### Never run git pull while migrations are actively writing

- `git pull` + `flask db upgrade` during an active write-heavy migration can corrupt Alembic state.
- The update script stops the servers **before** pulling. Do not bypass `stop_servers.cmd`.
- If you must deploy during a long-running migration: wait for it to finish, then deploy.

### Never push broken code to `main`

- `main` is the production branch. Anything pushed to `main` goes live the next time `update_and_restart.cmd` runs.
- Test locally first. If something breaks on the server, the old version is restored automatically, but you still have downtime.

### Never skip the stop step

- Running `git pull` while the backend is writing `flask_out.txt` or active log files is safe.
- Running `flask db upgrade` while Flask is serving requests is **not safe** for schema-changing migrations.
- The update script always stops first. Never run `git pull` and `flask db upgrade` manually without stopping servers first.

---

## Rollback

If the new version has a bug and you need to revert immediately:

```bash
# On the dev PC
git revert HEAD       # creates a new revert commit
git push origin main

# On the server
update_and_restart.cmd
```

Or hard-reset to a known good commit:
```bash
# On the dev PC
git reset --hard <good-commit-hash>
git push --force-with-lease origin main   # only if no one else is using this repo

# On the server
update_and_restart.cmd
```

---

## Individual Scripts

| Script | Purpose |
|--------|---------|
| `update_and_restart.cmd` | Full update pipeline — **this is the one you run** |
| `stop_servers.cmd` | Stop both servers safely (called by update script) |
| `start_servers.cmd` | Start both servers (called by update script) |

You can run `stop_servers.cmd` or `start_servers.cmd` individually if you need to bounce the servers without pulling new code (e.g., after manually editing `.env` on the server).

---

## Log Files

| File | Contains |
|------|---------|
| `update.log` | Full git pull output, pip/npm install output, migration output, timestamps |
| `backend\logs\backend.log` | Flask stdout + stderr for each session |
| `frontend\logs\frontend.log` | Vite stdout + stderr for each session |

Logs **append** across restarts — each session gets a timestamped header. Log files are excluded from git (`.gitignore` covers `*.log`).

---

## Port Reference

| Service | Port | URL |
|---------|------|-----|
| Flask backend | 3010 | http://localhost:3010 |
| Vite frontend | 3000 | http://localhost:3000 |
| PostgreSQL | 5432 | (default) |
| Redis | 6379 | (default) |

Cloudflare Tunnel routes external traffic to the appropriate local port. No changes needed to the tunnel when updating code.

---

## First-Time Server Setup

Run this once when setting up a new server, before using `update_and_restart.cmd`:

```powershell
# 1. Clone the repo
git clone https://github.com/aiscannerin/aiscanner.git
cd aiscanner

# 2. Configure environment
copy backend\.env.example backend\.env
# Edit backend\.env — set SECRET_KEY, DATABASE_URL, REDIS_URL,
# JWT_SECRET_KEY, RAZORPAY_*, BREVO_*

# 3. Bootstrap (installs venv, npm, runs migrations, seeds DB)
.\bootstrap.ps1 -SeedData

# 4. From now on, all updates use:
.\update_and_restart.cmd
```

See `PROJECT_TRANSFER_CHECKLIST.md` for the full first-time setup checklist.

---

## Checklist Before Each Deploy

- [ ] Code tested locally and working
- [ ] All changes committed and pushed to GitHub
- [ ] Push confirmed on https://github.com/aiscannerin/aiscanner
- [ ] No long-running migration currently executing on server
- [ ] No critical user activity expected in next 60 seconds (restart causes ~5s downtime)
