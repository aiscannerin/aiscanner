<#
.SYNOPSIS
    Stop Hunter Pro - One-command bootstrap script.
    Sets up backend venv, installs all dependencies, runs DB migrations,
    and optionally seeds dev data.

.USAGE
    .\bootstrap.ps1                     # full setup
    .\bootstrap.ps1 -SkipMigrations    # skip flask db upgrade
    .\bootstrap.ps1 -SeedData          # also run flask seed-db + seed-scan-snapshot

.NOTES
    Requires: Python 3.11+, Node.js 18+, PostgreSQL 15+, Redis 7+
    Must be run from the project root directory.
#>

param(
    [switch]$SkipMigrations,
    [switch]$SeedData,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root     = $PSScriptRoot
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv     = Join-Path $Backend "venv"
$Python   = Join-Path $Venv "Scripts\python.exe"
$Pip      = Join-Path $Venv "Scripts\pip.exe"
$Flask    = Join-Path $Venv "Scripts\flask.exe"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "  ==> $msg" -ForegroundColor Cyan
}
function Write-OK($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}
function Write-Warn($msg) {
    Write-Host "  [!!] $msg" -ForegroundColor Yellow
}
function Write-Fail($msg) {
    Write-Host ""
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host "   Stop Hunter Pro - Bootstrap" -ForegroundColor Magenta
Write-Host "  ============================================================" -ForegroundColor Magenta

# -- 1. Check prerequisites -----------------------------------------------------
Write-Step "Checking prerequisites..."

try { $pyVer = & python --version 2>&1; Write-OK "Python: $pyVer" }
catch { Write-Fail "Python not found. Install Python 3.11+ and add to PATH." }

if (-not $SkipFrontend) {
    try { $nodeVer = & node --version 2>&1; Write-OK "Node.js: $nodeVer" }
    catch { Write-Fail "Node.js not found. Install Node.js 18+ and add to PATH." }
}

# -- 2. Check .env file ---------------------------------------------------------
Write-Step "Checking environment configuration..."

$EnvFile    = Join-Path $Backend ".env"
$EnvExample = Join-Path $Backend ".env.example"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-Warn "Created backend\.env from .env.example."
        Write-Warn "IMPORTANT: Edit backend\.env and fill in all required values before starting."
        Write-Warn "  Required: SECRET_KEY, DATABASE_URL, JWT_SECRET_KEY, REDIS_URL,"
        Write-Warn "            CELERY_BROKER_URL, CELERY_RESULT_BACKEND,"
        Write-Warn "            RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET"
    } else {
        Write-Fail "Neither backend\.env nor backend\.env.example found."
    }
} else {
    Write-OK "backend\.env found."
}

# -- 3. Create Python virtual environment ----------------------------------------
Write-Step "Setting up Python virtual environment..."

if (-not (Test-Path $Python)) {
    Write-Host "  Creating venv..."
    & python -m venv $Venv
    if (-not $?) { Write-Fail "Failed to create virtual environment." }
    Write-OK "Virtual environment created at backend\venv"
} else {
    Write-OK "Virtual environment already exists."
}

# -- 4. Install backend dependencies --------------------------------------------
Write-Step "Installing backend dependencies..."

$ReqFile = Join-Path $Backend "requirements.txt"
if (-not (Test-Path $ReqFile)) { Write-Fail "backend\requirements.txt not found." }

& $Pip install --upgrade pip --quiet
& $Pip install -r $ReqFile --quiet
if (-not $?) { Write-Fail "pip install failed. Check requirements.txt and your internet connection." }
Write-OK "Backend dependencies installed."

# -- 5. Run database migrations -------------------------------------------------
if (-not $SkipMigrations) {
    Write-Step "Running database migrations..."
    Write-Host "  (Requires DATABASE_URL in backend\.env to be valid)"

    Push-Location $Backend
    try {
        $env:FLASK_APP = "run.py"
        & $Flask db upgrade
        if (-not $?) { Write-Fail "flask db upgrade failed. Check DATABASE_URL in backend\.env." }
        Write-OK "All migrations applied."
    } finally {
        Pop-Location
    }
} else {
    Write-Warn "Skipping migrations (--SkipMigrations flag set)."
}

# -- 6. Seed dev data ------------------------------------------------------------
if ($SeedData) {
    Write-Step "Seeding development data..."

    Push-Location $Backend
    try {
        $env:FLASK_APP = "run.py"

        & $Flask seed-db
        Write-OK "Plans, roles, tools seeded."

        & $Flask seed-scan-snapshot --overwrite
        Write-OK "Scan snapshot seeded (for market-closed UI testing)."
    } catch {
        Write-Warn "Seeding encountered an error: $_"
        Write-Warn "You can seed manually later with: flask seed-db"
    } finally {
        Pop-Location
    }
}

# -- 7. Install frontend dependencies -------------------------------------------
if (-not $SkipFrontend) {
    Write-Step "Installing frontend dependencies..."

    if (-not (Test-Path $Frontend)) { Write-Fail "frontend/ directory not found." }

    Push-Location $Frontend
    try {
        & npm install --silent
        if (-not $?) { Write-Fail "npm install failed." }
        Write-OK "Frontend dependencies installed."
    } finally {
        Pop-Location
    }
}

# -- 8. Summary -----------------------------------------------------------------
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host "   Bootstrap complete!" -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Edit backend\.env with your real credentials" -ForegroundColor White
Write-Host "       (especially SECRET_KEY, DATABASE_URL, JWT_SECRET_KEY)" -ForegroundColor Gray
Write-Host "    2. Start the dev environment:" -ForegroundColor White
Write-Host "       .\start.bat" -ForegroundColor Yellow
Write-Host "    3. Open http://localhost:3000 in your browser" -ForegroundColor White
Write-Host ""
Write-Host "  Optional:" -ForegroundColor White
Write-Host "    Start Celery worker (background tasks):" -ForegroundColor White
Write-Host "    cd backend && venv\Scripts\celery -A celery_worker.celery worker --loglevel=info --pool=solo" -ForegroundColor Yellow
Write-Host ""
