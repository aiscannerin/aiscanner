"""
/api/scans  — scan history endpoints

GET /api/scans/recent                    — last 20 completed scan runs for the user
GET /api/scans/<scan_run_id>             — single scan run detail
GET /api/scans/<scan_run_id>/results     — paginated saved results for a run
GET /api/scans/symbol/<symbol>/history   — all saved results for a symbol (newest first)
"""
from flask import request

from app.api.scans import scans_bp
from app.middleware.auth_guard import require_auth
from app.repositories import scan_job_repository, scan_result_repository
from app.utils.response import error, paginated, success


# ── Recent scan runs ──────────────────────────────────────────────────────────

@scans_bp.get("/recent")
@require_auth
def recent_scans():
    from flask import g
    jobs = scan_job_repository.get_recent_for_user(g.current_user.id, limit=20)
    return success(data=[j.to_dict() for j in jobs])


# ── Single scan run ───────────────────────────────────────────────────────────

@scans_bp.get("/<scan_run_id>")
@require_auth
def get_scan_run(scan_run_id):
    from flask import g
    job = scan_job_repository.get_by_id(scan_run_id)
    if not job:
        return error("Scan run not found.", 404, error_code="SCAN_NOT_FOUND")
    if str(job.user_id) != str(g.current_user.id):
        return error("This scan does not belong to your account.", 403,
                     error_code="SCAN_OWNERSHIP_MISMATCH")
    return success(data=job.to_dict())


# ── Paginated results for a run ───────────────────────────────────────────────

@scans_bp.get("/<scan_run_id>/results")
@require_auth
def get_scan_results(scan_run_id):
    from flask import g
    job = scan_job_repository.get_by_id(scan_run_id)
    if not job:
        return error("Scan run not found.", 404, error_code="SCAN_NOT_FOUND")
    if str(job.user_id) != str(g.current_user.id):
        return error("This scan does not belong to your account.", 403,
                     error_code="SCAN_OWNERSHIP_MISMATCH")

    try:
        page     = max(1, int(request.args.get("page", 1)))
        per_page = min(200, max(1, int(request.args.get("per_page", 200))))
    except (TypeError, ValueError):
        return error("page and per_page must be positive integers.", 400)

    results, total = scan_result_repository.get_paginated(
        scan_job_id=job.id,
        page=page,
        per_page=per_page,
    )
    return paginated(
        items=[r.to_dict() for r in results],
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Symbol history ────────────────────────────────────────────────────────────

@scans_bp.get("/symbol/<symbol>/history")
@require_auth
def symbol_history(symbol):
    from flask import g
    sym = symbol.strip().upper()
    if not sym:
        return error("Symbol is required.", 400)

    try:
        limit = min(100, max(1, int(request.args.get("limit", 10))))
    except (TypeError, ValueError):
        limit = 10

    results = scan_result_repository.get_symbol_history(
        symbol=sym,
        user_id=g.current_user.id,
        limit=limit,
    )

    # Enrich each result with its parent scan run metadata (cached per job_id)
    out = []
    job_cache: dict = {}
    for r in results:
        job_id = str(r.scan_job_id)
        if job_id not in job_cache:
            job = scan_job_repository.get_by_id(job_id)
            job_cache[job_id] = {
                "scan_run_id":    job_id,
                "universe":       job.universe       if job else None,
                "timeframe":      job.timeframe      if job else None,
                "ltf":            job.ltf            if job else None,
                "mode":           job.scan_mode      if job else None,
                "candidate_mode": job.candidate_mode if job else None,
                "scanner_name":   job.scanner_name   if job else None,
                "created_at":     job.created_at.isoformat() if job else None,
            }
        row = {
            # identity
            "id":                    str(r.id),
            "scan_run_id":           job_id,
            "symbol":                r.symbol,
            # result fields
            "classification":        r.classification,
            "watchlist_level":       r.watchlist_level,
            "watchlist_level_label": r.watchlist_level_label,
            "score":                 float(r.score) if r.score is not None else None,
            "grade":                 r.grade,
            "direction":             r.direction,
            "current_stage_label":   r.current_stage_label,
            "trade_plan_type":       r.trade_plan_type,
            "quality_flags":         r.quality_flags,
            # progression
            "progression_type":          r.progression_type,
            "progression_label":         r.progression_label,
            "progression_priority":      r.progression_priority,
            "previous_status":           r.previous_status,
            "previous_watchlist_level":  r.previous_watchlist_level,
            "previous_score":            r.previous_score,
            "created_at":            r.created_at.isoformat(),
            # scan metadata
            "scan_run":              job_cache[job_id],
        }
        out.append(row)

    return success(data=out, meta={"symbol": sym, "count": len(out)})
