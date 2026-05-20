from app.extensions import db
from app.models.scan_result import ScanResult


def bulk_create(results: list[dict]) -> list[ScanResult]:
    """
    Insert a list of result dicts in one flush.
    Each dict must contain at minimum: scan_job_id, symbol.
    Returns the created ORM objects after commit.
    """
    objects = [ScanResult(**r) for r in results]
    db.session.add_all(objects)
    db.session.commit()
    return objects


def get_paginated(
    scan_job_id,
    page:     int = 1,
    per_page: int = 20,
) -> tuple[list[ScanResult], int]:
    """Return (results_page, total_count) ordered by score desc."""
    base = db.select(ScanResult).where(ScanResult.scan_job_id == scan_job_id)

    total = db.session.execute(
        db.select(db.func.count()).select_from(base.subquery())
    ).scalar_one()

    results = db.session.execute(
        base
        .order_by(ScanResult.score.desc().nulls_last())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).scalars().all()

    return results, total


def get_latest_per_symbol(
    user_id,
    symbols: list[str],
) -> dict[str, "ScanResult"]:
    """
    For each symbol in *symbols*, return the most recently saved ScanResult
    from any *completed* scan by user_id.

    Uses a MAX(created_at) subquery so this is a single round-trip regardless
    of symbol-list length.  Returns {symbol: ScanResult}.
    """
    from app.models.scan_job import ScanJob

    if not symbols:
        return {}

    upper_syms = [s.upper() for s in symbols]

    # Subquery: latest created_at per symbol
    max_ts_sub = (
        db.select(
            ScanResult.symbol.label("sym"),
            db.func.max(ScanResult.created_at).label("max_ts"),
        )
        .join(ScanJob, ScanResult.scan_job_id == ScanJob.id)
        .where(ScanResult.symbol.in_(upper_syms))
        .where(ScanJob.user_id == user_id)
        .where(ScanJob.status == "completed")
        .group_by(ScanResult.symbol)
        .subquery()
    )

    # Join back to retrieve full ORM objects
    rows = db.session.execute(
        db.select(ScanResult)
        .join(ScanJob, ScanResult.scan_job_id == ScanJob.id)
        .join(
            max_ts_sub,
            db.and_(
                ScanResult.symbol == max_ts_sub.c.sym,
                ScanResult.created_at == max_ts_sub.c.max_ts,
            ),
        )
        .where(ScanJob.user_id == user_id)
        .where(ScanJob.status == "completed")
    ).scalars().all()

    # In the (rare) case of a timestamp tie, last-seen wins
    return {r.symbol: r for r in rows}


def get_symbol_history(
    symbol:   str,
    user_id   = None,
    limit:    int = 50,
) -> list[ScanResult]:
    """
    All scan results for a given symbol, newest first.
    If user_id is provided, only returns results from that user's scans.
    """
    from app.models.scan_job import ScanJob

    query = (
        db.select(ScanResult)
        .join(ScanJob, ScanResult.scan_job_id == ScanJob.id)
        .where(ScanResult.symbol == symbol.upper())
        .where(ScanJob.status == "completed")
    )
    if user_id is not None:
        query = query.where(ScanJob.user_id == user_id)

    query = query.order_by(ScanResult.created_at.desc()).limit(limit)
    return db.session.execute(query).scalars().all()
