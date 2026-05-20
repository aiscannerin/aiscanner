import uuid as _uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models.scan_job import ScanJob, ScanJobStatus


def create(
    user_id,
    tool_id,
    universe:       str,
    timeframe:      str,
    filters:        dict | None = None,
    total_symbols:  int  | None = None,
    scanner_name:   str  | None = None,
    ltf:            str  | None = None,
    scan_mode:      str  | None = None,
    candidate_mode: str  | None = None,
) -> ScanJob:
    job = ScanJob(
        user_id        = user_id,
        tool_id        = tool_id,
        universe       = universe,
        timeframe      = timeframe,
        filters        = filters or {},
        status         = ScanJobStatus.QUEUED,
        total_symbols  = total_symbols,
        progress       = 0,
        completed_symbols = 0,
        scanner_name   = scanner_name,
        ltf            = ltf,
        scan_mode      = scan_mode,
        candidate_mode = candidate_mode,
    )
    db.session.add(job)
    db.session.commit()
    return job


def get_by_id(job_id) -> ScanJob | None:
    try:
        jid = _uuid.UUID(str(job_id))
    except (ValueError, AttributeError):
        return None
    return db.session.get(ScanJob, jid)


def get_recent_for_user(user_id, limit: int = 20) -> list[ScanJob]:
    """Return the most recent *completed* scan runs for a user, newest first."""
    return db.session.execute(
        db.select(ScanJob)
        .where(ScanJob.user_id == user_id)
        .where(ScanJob.status == ScanJobStatus.COMPLETED)
        .order_by(ScanJob.created_at.desc())
        .limit(limit)
    ).scalars().all()


def mark_running(job: ScanJob, total_symbols: int) -> None:
    job.status        = ScanJobStatus.RUNNING
    job.total_symbols = total_symbols
    db.session.commit()


def mark_completed(job: ScanJob, completed_symbols: int) -> None:
    job.status            = ScanJobStatus.COMPLETED
    job.progress          = 100
    job.completed_symbols = completed_symbols
    job.completed_at      = datetime.now(timezone.utc)
    db.session.commit()


def update_run_stats(
    job:              ScanJob,
    confirmed_count:  int,
    watchlist_count:  int,
    near_miss_count:  int,
    no_result_count:  int,
    fetch_elapsed_s:  float,
    scan_elapsed_s:   float,
    cache_hits:       int,
    cache_misses:     int,
) -> None:
    """Persist per-run metrics collected after scan completion."""
    job.confirmed_count = confirmed_count
    job.watchlist_count = watchlist_count
    job.near_miss_count = near_miss_count
    job.no_result_count = no_result_count
    job.fetch_elapsed_s = round(fetch_elapsed_s, 2)
    job.scan_elapsed_s  = round(scan_elapsed_s,  2)
    job.cache_hits      = cache_hits
    job.cache_misses    = cache_misses
    db.session.commit()


def save_scan_health(job: ScanJob, health: dict) -> None:
    """Persist the scan_health object and its denormalised columns."""
    job.scan_health_json  = health
    job.symbols_requested = health.get("symbols_requested")
    job.symbols_scanned   = health.get("symbols_scanned")
    job.symbols_failed    = health.get("symbols_failed")
    job.partial_scan      = health.get("partial_scan")
    job.data_quality      = health.get("data_quality")
    db.session.commit()


def mark_failed(job: ScanJob) -> None:
    job.status       = ScanJobStatus.FAILED
    job.completed_at = datetime.now(timezone.utc)
    db.session.commit()


def mark_cancelled(job: ScanJob) -> None:
    job.status       = ScanJobStatus.CANCELLED
    job.completed_at = datetime.now(timezone.utc)
    db.session.commit()
