from flask import Blueprint, g, request

from app.middleware.auth_guard import require_auth
from app.middleware.tool_access import tool_access_required
from app.services import scanner_job_service
from app.utils.response import error

scanners_bp = Blueprint("scanners", __name__)

_TOOL_SLUG = "stop-hunter-pro"


# ── Start scan ────────────────────────────────────────────────────────────────────

@scanners_bp.post("/stop-hunter-pro/start")
@tool_access_required(_TOOL_SLUG)
def start_stop_hunter_scan():
    data = request.get_json(silent=True) or {}
    return scanner_job_service.start_scan(data)


# ── Job status ────────────────────────────────────────────────────────────────────

@scanners_bp.get("/jobs/<job_id>")
@require_auth
def get_job(job_id):
    return scanner_job_service.get_job_status(job_id)


# ── Job results ───────────────────────────────────────────────────────────────────

@scanners_bp.get("/jobs/<job_id>/results")
@require_auth
def get_job_results(job_id):
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except (TypeError, ValueError):
        return error("page and per_page must be positive integers.", 400)
    return scanner_job_service.get_job_results(job_id, page=page, per_page=per_page)


# ── Cancel job ────────────────────────────────────────────────────────────────────

@scanners_bp.post("/jobs/<job_id>/cancel")
@require_auth
def cancel_job(job_id):
    return scanner_job_service.cancel_job(job_id)


# ── Recent jobs ───────────────────────────────────────────────────────────────────

@scanners_bp.get("/recent")
@require_auth
def recent_jobs():
    return scanner_job_service.get_recent_jobs()
