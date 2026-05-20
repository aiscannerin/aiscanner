"""
/api/watchlist — user symbol tracking list

GET    /api/watchlist                list all active tracked symbols (with latest scan state)
POST   /api/watchlist                add a symbol to tracking
DELETE /api/watchlist/<id>           remove a tracked entry
PATCH  /api/watchlist/<id>           update note on a tracked entry
"""
import uuid as _uuid

from flask import g, request

from app.api.watchlist import watchlist_bp
from app.extensions import db
from app.middleware.auth_guard import require_auth
from app.repositories import user_tracked_symbol_repository as repo
from app.repositories import scan_result_repository
from app.utils.response import error, success


# ── GET /api/watchlist ────────────────────────────────────────────────────────

@watchlist_bp.get("")
@require_auth
def list_tracked():
    user_id = g.current_user.id
    entries = repo.get_all_for_user(user_id)

    # Batch-fetch latest scan results for all tracked symbols in one query
    symbols   = list({e.symbol for e in entries})
    latest_map = scan_result_repository.get_latest_per_symbol(user_id, symbols) if symbols else {}

    return success(
        data=[e.to_dict(latest_result=latest_map.get(e.symbol)) for e in entries],
        meta={"total": len(entries)},
    )


# ── POST /api/watchlist ───────────────────────────────────────────────────────

@watchlist_bp.post("")
@require_auth
def add_tracked():
    user_id = g.current_user.id
    body    = request.get_json(silent=True) or {}

    symbol       = (body.get("symbol") or "").strip().upper()
    scanner_name = (body.get("scanner_name") or "Stop Hunter Pro").strip()
    htf          = (body.get("htf") or "").strip()
    ltf          = (body.get("ltf") or "").strip() or None
    note         = (body.get("note") or "").strip() or None

    if not symbol:
        return error("symbol is required.", 400, error_code="MISSING_SYMBOL")
    if not htf:
        return error("htf is required.", 400, error_code="MISSING_HTF")

    # Duplicate protection — return 409 if already actively tracked
    existing = repo.find_active(user_id, symbol, scanner_name, htf, ltf)
    if existing:
        return error(
            f"{symbol} is already being tracked with these settings.",
            409,
            error_code="ALREADY_TRACKED",
        )

    entry = repo.create(user_id, symbol, scanner_name, htf, ltf, note)
    return success(
        message=f"{symbol} added to watchlist.",
        data=entry.to_dict(),
        status_code=201,
    )


# ── DELETE /api/watchlist/<id> ────────────────────────────────────────────────

@watchlist_bp.delete("/<tracked_id>")
@require_auth
def remove_tracked(tracked_id):
    user_id = g.current_user.id

    try:
        tid = _uuid.UUID(str(tracked_id))
    except (ValueError, AttributeError):
        return error("Invalid watchlist entry ID.", 400)

    entry = repo.get_by_id(tid)
    if not entry:
        return error("Watchlist entry not found.", 404, error_code="TRACKED_NOT_FOUND")
    if entry.user_id and str(entry.user_id) != str(user_id):
        return error("This entry does not belong to your account.", 403,
                     error_code="TRACKED_OWNERSHIP_MISMATCH")

    symbol = entry.symbol
    repo.delete(entry)
    return success(message=f"{symbol} removed from watchlist.")


# ── PATCH /api/watchlist/<id> ─────────────────────────────────────────────────

@watchlist_bp.patch("/<tracked_id>")
@require_auth
def update_tracked(tracked_id):
    user_id = g.current_user.id

    try:
        tid = _uuid.UUID(str(tracked_id))
    except (ValueError, AttributeError):
        return error("Invalid watchlist entry ID.", 400)

    entry = repo.get_by_id(tid)
    if not entry:
        return error("Watchlist entry not found.", 404, error_code="TRACKED_NOT_FOUND")
    if entry.user_id and str(entry.user_id) != str(user_id):
        return error("This entry does not belong to your account.", 403,
                     error_code="TRACKED_OWNERSHIP_MISMATCH")

    body = request.get_json(silent=True) or {}

    # Update note if present in body
    if "note" in body:
        entry = repo.update_note(entry, body["note"] or None)

    # Update alert preferences if any pref key is present
    pref_keys = {
        "alert_became_confirmed", "alert_improved_level",
        "alert_became_watchlist", "alert_degraded",
        "alert_score_crossed_threshold", "score_threshold",
    }
    prefs = {k: body[k] for k in pref_keys if k in body}
    if prefs:
        entry = repo.update_alert_prefs(entry, prefs)

    # Include latest scan result in response
    latest_map = scan_result_repository.get_latest_per_symbol(user_id, [entry.symbol])
    return success(
        message="Watchlist entry updated.",
        data=entry.to_dict(latest_result=latest_map.get(entry.symbol)),
    )
