import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models.plan import Plan, PlanName

from app.models.plan_tool_map import PlanToolMap
from app.models.role import Role, RoleName
from app.models.tool import Tool


# ── verify-user ────────────────────────────────────────────────────────────────
# Development helper: mark a user's email as verified so they can log in
# without going through the OTP flow.  NOT for production use.

@click.command("verify-user")
@click.argument("email")
@with_appcontext
def verify_user_command(email):
    """
    [DEV] Force-verify a user's email address so they can log in.

    This bypasses the OTP email-verification flow — only use in development
    when you've seeded a user directly into the database.

    Usage:
        flask verify-user user@example.com
    """
    from datetime import datetime, timezone
    from app.models.user import User

    email = email.strip().lower()
    user = db.session.execute(
        db.select(User).where(User.email == email)
    ).scalar_one_or_none()

    if not user:
        click.secho(f"  ERROR: No user found with email '{email}'", fg="red")
        return

    if user.email_verified:
        click.secho(f"  Already verified: {email}", fg="cyan")
        return

    user.email_verified = True
    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    click.secho(f"  Email verified for: {email} (id={user.id})", fg="green")


# ── create-dev-user ────────────────────────────────────────────────────────────
# Development helper: create a fully verified user in one command.

@click.command("create-dev-user")
@click.option("--email",    default="dev@example.com", show_default=True)
@click.option("--password", default="Password1!",      show_default=True)
@click.option("--username", default="devuser",         show_default=True)
@click.option("--name",     default="Dev User",        show_default=True)
@with_appcontext
def create_dev_user_command(email, password, username, name):
    """
    [DEV] Create a pre-verified user account for local testing.

    Skips OTP verification and subscription provisioning.
    Safe to re-run — skips if user already exists.

    Usage:
        flask create-dev-user
        flask create-dev-user --email alice@test.com --password MyPass1!
    """
    from datetime import datetime, timezone
    from flask_bcrypt import Bcrypt
    from app.models.user import User
    from app.models.role import Role, RoleName

    email    = email.strip().lower()
    username = username.strip().lower()

    # Check if user already exists
    existing = db.session.execute(
        db.select(User).where(User.email == email)
    ).scalar_one_or_none()

    if existing:
        click.secho(
            f"  User already exists: {email} (email_verified={existing.email_verified})",
            fg="cyan",
        )
        return

    # Ensure roles are seeded
    user_role = db.session.execute(
        db.select(Role).where(Role.name == RoleName.USER)
    ).scalar_one_or_none()

    if not user_role:
        click.secho(
            "  ERROR: No 'user' role found. Run `flask seed-db` first.",
            fg="red",
        )
        return

    bcrypt = Bcrypt()
    pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    user = User(
        full_name       = name,
        username        = username,
        email           = email,
        password_hash   = pw_hash,
        phone           = "9999999999",
        gender          = "prefer_not_to_say",
        trading_experience = "beginner",
        address         = "Dev Address, Test City",
        role_id         = user_role.id,
        email_verified  = True,
        is_active       = True,
    )
    db.session.add(user)
    db.session.commit()

    click.secho(f"  Created dev user: {email}  password: {password}  id: {user.id}", fg="green")
    click.secho("  This user can log in immediately.", fg="green")


@click.command("seed-db")
@with_appcontext
def seed_db_command():
    """
    Seed the database with roles, plans, tools, and plan-tool mappings.
    Safe to run multiple times — skips records that already exist.

    Usage:
        flask seed-db
    """
    _seed_roles()
    _seed_plans()
    _seed_tools()
    _seed_plan_tool_maps()
    click.echo("Database seeded successfully.")


# ── Roles ─────────────────────────────────────────────────────────────────────────

def _seed_roles():
    seeds = [
        (RoleName.ADMIN, "Platform administrator with full access."),
        (RoleName.USER, "Regular registered user."),
    ]
    for name, description in seeds:
        exists = db.session.execute(
            db.select(Role).where(Role.name == name)
        ).scalar_one_or_none()
        if not exists:
            db.session.add(Role(name=name, description=description))
            click.echo(f"  Created role: {name}")
        else:
            click.echo(f"  Role already exists, skipping: {name}")
    db.session.commit()


# ── Plans ─────────────────────────────────────────────────────────────────────────

def _seed_plans():
    seeds = [
        {
            "name": PlanName.FREE,
            "monthly_price": 0.00,
            "yearly_price": 0.00,
            "description": "Free plan. Access to the dashboard only.",
        },
        {
            "name": PlanName.PRO,
            "monthly_price": 999.00,
            "yearly_price": 9999.00,
            "description": "Pro plan. Access to core scanner tools.",
        },
        {
            "name": PlanName.EXPERT,
            "monthly_price": 1999.00,
            "yearly_price": 19999.00,
            "description": "Expert plan. Unlimited access to all tools.",
        },
    ]
    for plan_data in seeds:
        exists = db.session.execute(
            db.select(Plan).where(Plan.name == plan_data["name"])
        ).scalar_one_or_none()
        if not exists:
            db.session.add(Plan(**plan_data))
            click.echo(f"  Created plan: {plan_data['name']}")
        else:
            click.echo(f"  Plan already exists, skipping: {plan_data['name']}")
    db.session.commit()


# ── Tools ─────────────────────────────────────────────────────────────────────────

_TOOLS = [
    {
        "slug": "stop-hunter-pro",
        "name": "Stop Hunter Pro",
        "description": "Identifies institutional stop-hunt zones and liquidity sweeps in real time.",
    },
    {
        "slug": "smc-liquidity-scanner",
        "name": "SMC Liquidity Scanner",
        "description": "Smart Money Concepts scanner — detects order blocks, fair value gaps, and BOS/CHoCH.",
    },
    {
        "slug": "master-screener",
        "name": "Master Screener",
        "description": "Multi-filter stock screener with technical and fundamental criteria.",
    },
    {
        "slug": "volume-profile-scanner",
        "name": "Volume Profile Scanner",
        "description": "Scans for high-volume nodes, POC levels, and value area breakouts.",
    },
    {
        "slug": "options-scanner",
        "name": "Options Scanner",
        "description": "Screens options chains for unusual activity, OI buildup, and PCR signals.",
    },
]


def _seed_tools():
    for tool_data in _TOOLS:
        exists = db.session.execute(
            db.select(Tool).where(Tool.slug == tool_data["slug"])
        ).scalar_one_or_none()
        if not exists:
            db.session.add(Tool(**tool_data))
            click.echo(f"  Created tool: {tool_data['slug']}")
        else:
            click.echo(f"  Tool already exists, skipping: {tool_data['slug']}")
    db.session.commit()


# ── Plan-tool mappings ────────────────────────────────────────────────────────────

# Free plan: no tool access (dashboard only).
# Pro:    stop-hunter-pro, smc-liquidity-scanner, master-screener
# Expert: all tools
_PLAN_TOOL_MAP = {
    PlanName.PRO: [
        "stop-hunter-pro",
        "smc-liquidity-scanner",
        "master-screener",
    ],
    PlanName.EXPERT: [
        "stop-hunter-pro",
        "smc-liquidity-scanner",
        "master-screener",
        "volume-profile-scanner",
        "options-scanner",
    ],
}


def _seed_plan_tool_maps():
    for plan_name, slugs in _PLAN_TOOL_MAP.items():
        plan = db.session.execute(
            db.select(Plan).where(Plan.name == plan_name)
        ).scalar_one_or_none()
        if not plan:
            click.echo(f"  [WARN] Plan '{plan_name}' not found — skipping tool mapping.")
            continue

        for slug in slugs:
            tool = db.session.execute(
                db.select(Tool).where(Tool.slug == slug)
            ).scalar_one_or_none()
            if not tool:
                click.echo(f"  [WARN] Tool '{slug}' not found — skipping.")
                continue

            already = db.session.execute(
                db.select(PlanToolMap).where(
                    PlanToolMap.plan_id == plan.id,
                    PlanToolMap.tool_id == tool.id,
                )
            ).scalar_one_or_none()

            if not already:
                db.session.add(PlanToolMap(plan_id=plan.id, tool_id=tool.id))
                click.echo(f"  Mapped {plan_name} → {slug}")
            else:
                click.echo(f"  Mapping already exists, skipping: {plan_name} → {slug}")

    db.session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# flask nse  — NSE universe & stock master CLI
# ══════════════════════════════════════════════════════════════════════════════

@click.group("nse")
def nse_group():
    """Commands for NSE stock universe and sector management."""


@nse_group.command("sync-stocks")
@with_appcontext
def nse_sync_stocks():
    """
    Fetch EQUITY_L.csv from NSE archives and upsert all equity symbols.

    Downloads the full list of NSE-listed equities and creates/updates rows
    in the nse_stocks table.  Symbols no longer on NSE are marked inactive.

    Usage:
        flask nse sync-stocks
    """
    from app.services.universe_service import sync_nse_equity_master
    click.echo("Syncing NSE equity master list...")
    result = sync_nse_equity_master()

    if result.get("error"):
        click.secho(f"  ERROR: {result['error']}", fg="red")
        click.echo("  Tip: download EQUITY_L.csv manually from NSE and place it in backend/data/nse_cache/")
    else:
        click.secho(f"  Total: {result['total']}", fg="cyan")
        click.secho(f"  Created: {result['created']}", fg="green")
        click.secho(f"  Updated: {result['updated']}", fg="yellow")
        click.secho(f"  Deactivated: {result.get('deactivated', 0)}", fg="yellow")
        click.secho("  Done.", fg="green")


@nse_group.command("sync-universes")
@click.option("--slug", multiple=True, help="Sync only specific universe slugs (repeatable).")
@with_appcontext
def nse_sync_universes(slug):
    """
    Fetch index constituents from NSE and populate universe memberships.

    Syncs all default universes (nifty50, nifty_bank, nifty_it, etc.)
    or only the ones specified with --slug.

    Usage:
        flask nse sync-universes
        flask nse sync-universes --slug nifty50 --slug nifty_bank
    """
    from app.services.universe_service import sync_sectoral_universes
    slugs = list(slug) if slug else None
    click.echo(f"Syncing universes: {slugs or 'all'}...")

    results = sync_sectoral_universes(slugs)
    for s, res in results.items():
        if res.get("error"):
            click.secho(f"  [{s}] ERROR: {res['error']}", fg="red")
        else:
            click.secho(
                f"  [{s}] added={res['added']} skipped={res['skipped']}",
                fg="green",
            )
    click.echo("Done.")


@nse_group.command("import-industry-csv")
@click.argument("filepath", default="", required=False)
@with_appcontext
def nse_import_industry_csv(filepath):
    """
    Import NSE industry classification CSV to enrich sector/industry data.

    If FILEPATH is not provided, looks for backend/data/nse_industry.csv.

    Download the CSV manually from:
    https://www.nseindia.com/market-data/securities-available-for-trading
    (Click "Download CSV" while logged in to the NSE website.)

    Usage:
        flask nse import-industry-csv
        flask nse import-industry-csv /path/to/nse_industry.csv
    """
    from pathlib import Path
    from app.services.universe_service import import_industry_csv

    if not filepath:
        base = Path(__file__).resolve().parent.parent
        filepath = base / "data" / "nse_industry.csv"

    filepath = Path(filepath)
    if not filepath.exists():
        click.secho(
            f"File not found: {filepath}\n"
            "Download it manually from NSE website and place it at that path.",
            fg="red",
        )
        return

    click.echo(f"Importing industry CSV from {filepath}...")
    result = import_industry_csv(filepath)

    if result.get("error"):
        click.secho(f"  ERROR: {result['error']}", fg="red")
    else:
        click.secho(f"  Total records: {result['total']}", fg="cyan")
        click.secho(f"  Updated: {result['updated']}", fg="green")
        click.secho(f"  Skipped: {result['skipped']}", fg="yellow")
        click.secho("  Done.", fg="green")


@nse_group.command("list-sectors")
@with_appcontext
def nse_list_sectors():
    """
    List all distinct sectors currently in the nse_stocks table.

    Usage:
        flask nse list-sectors
    """
    from app.services.universe_service import get_all_sectors
    sectors = get_all_sectors()
    if not sectors:
        click.echo("No sectors found.  Run `flask nse import-industry-csv` first.")
        return
    click.echo(f"Found {len(sectors)} sectors:")
    for s in sectors:
        click.echo(f"  {s}")


@nse_group.command("sync-industry-classification")
@with_appcontext
def nse_sync_industry_classification():
    """
    Fetch industry classification from niftyindices.com and enrich nse_stocks.

    Fetches constituent CSVs from 13 NIFTY indices (NIFTY 500, Midcap 150,
    Smallcap 250, Bank, IT, Pharma, Auto, FMCG, Media, Metal, Oil & Gas,
    Realty, Fin Services) and writes:
        nse_stocks.sector       — e.g. "Financial Services"
        nse_stocks.industry     — same
        nse_stocks.macro_sector — e.g. "FINANCIAL SERVICES"

    No NSE login or session cookie required — uses publicly accessible CSVs.

    Prerequisite: run `flask nse sync-stocks` first so that nse_stocks rows
    exist.  Stocks in the classification CSVs but not in nse_stocks are skipped.

    Usage:
        flask nse sync-industry-classification
    """
    from app.services.universe_service import sync_industry_classification

    click.echo("Fetching industry classification from niftyindices.com...")
    click.echo("(fetching 13 index CSVs — takes 10-20 seconds)")
    result = sync_industry_classification()

    if result.get("error"):
        click.echo()
        click.secho("  FAILED to fetch classification data.", fg="red")
        click.echo()
        click.echo(result["error"])
        click.echo()
        click.secho(
            "  Manual fallback: download the CSV from NSE and run:\n"
            "    flask nse import-industry-csv /path/to/your_file.csv",
            fg="yellow",
        )
        return

    click.secho(f"  Stocks classified (sector updated): {result['classified']}", fg="green")
    click.secho(f"  Stocks skipped (not in any index CSV): {result['skipped']}", fg="yellow")
    click.secho(f"  Symbols in index CSVs not in DB: {result['not_in_db']}", fg="yellow")
    click.echo()

    if result["skipped"] > 0:
        click.echo(
            "  Note: unlisted/non-NIFTY stocks have no sector data.\n"
            "  For complete coverage run:\n"
            "    flask nse import-industry-csv\n"
            "  with the manually downloaded NSE classification CSV.\n"
            "  Expected columns: Symbol, Series, Company Name, ISIN,\n"
            "                    Macro Sector, Sector, Industry, Basic Industry"
        )

    click.secho("Done. Run `flask nse list-sectors` to verify.", fg="green")


# ══════════════════════════════════════════════════════════════════════════════
# flask seed-scan-snapshot — inject fake scan data for UI development
# ══════════════════════════════════════════════════════════════════════════════

@click.command("inspect-snapshots")
@with_appcontext
def inspect_snapshots_command():
    """
    [DEV] Print a diagnostic report of all saved ScanSnapshot rows.

    Shows DB URI, total rows, all thresholds present, newest snapshot
    metadata, and symbol counts — without printing the full payload.

    Usage:
        flask inspect-snapshots
    """
    import re
    import os as _os
    from app.models.scan_snapshot import ScanSnapshot
    from app.extensions import db
    from sqlalchemy import func

    raw_uri  = _os.getenv("DATABASE_URL", "not set")
    safe_uri = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", raw_uri)

    click.echo()
    click.secho("  Snapshot Store Diagnostics", fg="cyan", bold=True)
    click.secho(f"  DB URI : {safe_uri}", fg="cyan")
    click.echo()

    # Total rows
    total = db.session.query(ScanSnapshot).count()
    click.secho(f"  Total snapshots : {total}", fg=("green" if total > 0 else "yellow"))

    if total == 0:
        click.secho(
            "\n  No snapshots found. Run `flask seed-scan-snapshot` first,\n"
            "  or trigger a live scan during market hours.",
            fg="yellow",
        )
        click.echo()
        return

    # All distinct thresholds
    thresholds = [
        row[0] for row in
        db.session.query(ScanSnapshot.threshold).distinct().order_by(ScanSnapshot.threshold).all()
    ]
    click.secho(f"  Thresholds      : {thresholds}", fg="cyan")

    # Newest snapshot
    newest = (
        db.session.query(ScanSnapshot)
        .order_by(ScanSnapshot.created_at.desc())
        .first()
    )

    click.echo()
    click.secho("  Newest snapshot:", fg="white", bold=True)
    click.secho(f"    id             : {newest.id}", fg="green")
    click.secho(f"    created_at     : {newest.created_at}", fg="green")
    click.secho(f"    age            : {newest.age_minutes():.1f} minutes ago", fg="green")
    click.secho(f"    threshold      : {newest.threshold}%", fg="green")
    click.secho(f"    symbol_count   : {newest.symbol_count}", fg="green")
    click.secho(f"    market_status  : {newest.market_status}", fg="green")
    click.secho(f"    avg_fetch_ms   : {newest.avg_fetch_ms}", fg="green")

    # All rows summary
    if total > 1:
        click.echo()
        click.secho(f"  All {total} snapshots (newest first):", fg="white", bold=True)
        rows = (
            db.session.query(ScanSnapshot)
            .order_by(ScanSnapshot.created_at.desc())
            .limit(10)
            .all()
        )
        for r in rows:
            click.secho(
                f"    [{str(r.id)[:8]}]  threshold={r.threshold}%  "
                f"symbols={r.symbol_count}  "
                f"age={r.age_minutes():.0f}min  "
                f"status={r.market_status}",
                fg="cyan",
            )

    click.echo()
    click.secho(
        "  Tip: run `flask seed-scan-snapshot --overwrite` to replace all\n"
        "  snapshots with a fresh seed row for UI testing.",
        fg="yellow",
    )
    click.echo()


@click.command("seed-scan-snapshot")
@click.option(
    "--threshold", default=2.0, show_default=True, type=float,
    help="Threshold % to tag the snapshot with (default 2.0).",
)
@click.option(
    "--overwrite", is_flag=True, default=False,
    help="Delete ALL existing scan_snapshots rows before inserting.",
)
@with_appcontext
def seed_scan_snapshot_command(threshold, overwrite):
    """
    [DEV] Insert one fake ScanSnapshot row for market-closed fallback UI testing.

    Creates a realistic scanner payload with RELIANCE, NIFTY, and BANKNIFTY
    so you can verify the blue SnapshotBanner and SNAPSHOT badge in the frontend
    without waiting for NSE market hours.

    Usage:
        flask seed-scan-snapshot
        flask seed-scan-snapshot --threshold 0
        flask seed-scan-snapshot --overwrite
    """
    import json
    from datetime import datetime, timezone
    from app.models.scan_snapshot import ScanSnapshot

    # ── Optional wipe ────────────────────────────────────────────────────────
    if overwrite:
        deleted = db.session.query(ScanSnapshot).delete()
        db.session.commit()
        click.secho(f"  Deleted {deleted} existing snapshot(s).", fg="yellow")

    # ── Fake scanner results ─────────────────────────────────────────────────
    now_ist_str  = datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M IST")
    fake_results = [
        {
            "symbol":            "RELIANCE",
            "spot_price":        2847.35,
            "max_pain":          2750.00,
            "distance_pct":      3.54,
            "distance_level":    "high",
            "direction":         "bearish",
            "reversal_score":    72,
            "reversal_category": "Strong",
            "reversal_color":    "#fb923c",
            "pcr":               0.74,
            "pcr_bias":          "bearish",
            "oi_bias":           "bearish",
            "days_to_expiry":    4,
            "expiry":            "26-Jun-2025",
            "atm_ce_iv":         22.4,
            "atm_pe_iv":         24.1,
            "total_ce_oi":       8_420_000,
            "total_pe_oi":       6_230_000,
            "ce_oi_wall":        2900,
            "pe_oi_wall":        2800,
            "ce_oi_wall_oi":     3_150_000,
            "pe_oi_wall_oi":     2_640_000,
        },
        {
            "symbol":            "NIFTY",
            "spot_price":        24_318.50,
            "max_pain":          24_000.00,
            "distance_pct":      1.33,
            "distance_level":    "moderate",
            "direction":         "bearish",
            "reversal_score":    58,
            "reversal_category": "Moderate",
            "reversal_color":    "#facc15",
            "pcr":               1.12,
            "pcr_bias":          "neutral",
            "oi_bias":           "neutral",
            "days_to_expiry":    2,
            "expiry":            "19-Jun-2025",
            "atm_ce_iv":         13.8,
            "atm_pe_iv":         14.2,
            "total_ce_oi":       52_800_000,
            "total_pe_oi":       59_200_000,
            "ce_oi_wall":        24_500,
            "pe_oi_wall":        24_000,
            "ce_oi_wall_oi":     18_900_000,
            "pe_oi_wall_oi":     22_100_000,
        },
        {
            "symbol":            "BANKNIFTY",
            "spot_price":        51_240.80,
            "max_pain":          52_000.00,
            "distance_pct":      1.46,
            "distance_level":    "moderate",
            "direction":         "bullish",
            "reversal_score":    81,
            "reversal_category": "Extreme",
            "reversal_color":    "#f87171",
            "pcr":               1.68,
            "pcr_bias":          "bullish",
            "oi_bias":           "bullish",
            "days_to_expiry":    2,
            "expiry":            "19-Jun-2025",
            "atm_ce_iv":         16.5,
            "atm_pe_iv":         18.0,
            "total_ce_oi":       31_400_000,
            "total_pe_oi":       52_700_000,
            "ce_oi_wall":        52_000,
            "pe_oi_wall":        51_000,
            "ce_oi_wall_oi":     12_300_000,
            "pe_oi_wall_oi":     19_800_000,
        },
    ]

    # ── Build the full run_scanner()-shaped payload ───────────────────────────
    payload = {
        "results":         fake_results,
        "errors":          [],
        "below_threshold": [],
        "market_closed":   [],
        "summary": {
            "total_scanned":       3,
            "total_hits":          3,
            "total_errors":        0,
            "total_below_threshold": 0,
            "threshold_pct":       threshold,
            "generated_at":        now_ist_str,
        },
        "metrics": {
            "symbols_total":    3,
            "fetch_success":    3,
            "fetch_failed":     0,
            "market_closed":    0,
            "threshold_filtered": 0,
            "returned_results": 3,
            "avg_fetch_ms":     287.4,
            "scan_elapsed_ms":  1842.0,
        },
    }

    # ── Persist ───────────────────────────────────────────────────────────────
    snapshot = ScanSnapshot(
        threshold        = threshold,
        symbol_count     = len(fake_results),
        avg_fetch_ms     = payload["metrics"]["avg_fetch_ms"],
        scan_elapsed_ms  = payload["metrics"]["scan_elapsed_ms"],
        market_status    = "open",   # data was live when captured
        payload_json     = json.dumps(payload),
    )
    db.session.add(snapshot)
    db.session.commit()

    # ── Report ────────────────────────────────────────────────────────────────
    click.echo()
    click.secho("  [OK] ScanSnapshot seeded successfully", fg="green", bold=True)
    click.echo()
    click.secho(f"  ID            : {snapshot.id}", fg="cyan")
    click.secho(f"  Symbol count  : {snapshot.symbol_count}", fg="cyan")
    click.secho(f"  Threshold     : {snapshot.threshold}%", fg="cyan")
    click.secho(f"  Market status : {snapshot.market_status}", fg="cyan")
    click.secho(f"  Created at    : {snapshot.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}", fg="cyan")
    click.echo()
    click.secho("  Symbols seeded:", fg="white", bold=True)
    for r in fake_results:
        direction_arrow = "^" if r["direction"] == "bullish" else "v"
        click.secho(
            f"    {direction_arrow} {r['symbol']:<12}"
            f"  spot={r['spot_price']:,.2f}"
            f"  max_pain={r['max_pain']:,.0f}"
            f"  dist={r['distance_pct']}%"
            f"  score={r['reversal_score']}/100"
            f"  pcr={r['pcr']}",
            fg="green" if r["direction"] == "bullish" else "red",
        )
    click.echo()
    click.secho(
        "  Frontend: run the scan while market is closed — the snapshot fallback\n"
        "  banner should appear with a blue 'SNAPSHOT' badge in the header.",
        fg="yellow",
    )
    click.echo()


@nse_group.command("init-universes")
@with_appcontext
def nse_init_universes():
    """
    Create all default universe rows in the DB (without syncing memberships).

    Run this once after migrations to ensure universe stubs exist.
    Then run `flask nse sync-stocks` + `flask nse sync-universes` to populate them.

    Usage:
        flask nse init-universes
    """
    from app.services.universe_service import sync_default_universes
    click.echo("Initialising default universe rows...")
    result = sync_default_universes()
    click.secho(f"  Created: {result['created']}", fg="green")
    click.secho(f"  Already existed: {result['existing']}", fg="cyan")
    click.secho("Done.", fg="green")
