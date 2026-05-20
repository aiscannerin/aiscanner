"""
Max Pain Historical Data API Routes
=====================================
Mounted under /api/max-pain/history/

Endpoints
---------
GET  /api/max-pain/history/<symbol>          unified snapshot series (primary)
GET  /api/max-pain/history/<symbol>/latest   most recent snapshot
GET  /api/max-pain/history/latest            latest for multiple symbols
POST /api/max-pain/history/capture           manual snapshot trigger
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from flask import current_app

from app.services.max_pain_snapshot_service import (
    capture_symbols,
    capture_symbol,
    cleanup_old_snapshots,
    get_historical_snapshots,
    get_latest_snapshot,
)
from app.services.max_pain_history_service import (
    get_max_pain_trend,
    get_max_pain_drift,
    get_oi_wall_migration,
)

logger = logging.getLogger(__name__)

history_bp = Blueprint("max_pain_history", __name__, url_prefix="/api/max-pain/history")

VALID_WINDOWS = {"1h", "4h", "1d", "3d", "7d", "30d"}


def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _err(message: str, status: int = 500):
    return jsonify({"success": False, "error": message}), status


def _window(default: str = "1d") -> str:
    w = request.args.get("window", default)
    return w if w in VALID_WINDOWS else default


# ---------------------------------------------------------------------------
# GET /api/max-pain/history/<symbol>
# ---------------------------------------------------------------------------

@history_bp.route("/<string:symbol>", methods=["GET"])
@jwt_required()
def symbol_history(symbol: str):
    """
    Unified time-series history for a symbol.

    Query params:
      window     : 1h | 4h | 1d | 3d | 7d | 30d  (default: 1d)
      expiry     : NSE expiry date string (default: any)
      max_points : int — downsample to at most N points (default: 200)

    Response:
      {
        "symbol": str,
        "window": str,
        "expiry": str | null,
        "count":  int,
        "snapshots": [
          {
            "id", "captured_at", "spot_price", "max_pain",
            "distance_pct", "pcr", "pcr_bias",
            "total_ce_oi", "total_pe_oi",
            "ce_wall_strike", "ce_wall_oi",
            "pe_wall_strike", "pe_wall_oi",
            "atm_ce_iv", "atm_pe_iv", "avg_iv",
            "top_pain_strikes", "top_ce_strikes", "top_pe_strikes"
          }, …
        ]
      }
    """
    try:
        sym        = symbol.upper().strip()
        window     = _window()
        expiry     = request.args.get("expiry") or None
        max_points = max(1, min(int(request.args.get("max_points", 200)), 500))

        snapshots = get_historical_snapshots(sym, window=window,
                                             expiry=expiry, max_points=max_points)
        return _ok({
            "symbol":    sym,
            "window":    window,
            "expiry":    expiry,
            "count":     len(snapshots),
            "snapshots": snapshots,
        })
    except Exception as exc:
        logger.error("history error %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/history/<symbol>/latest
# ---------------------------------------------------------------------------

@history_bp.route("/<string:symbol>/latest", methods=["GET"])
@jwt_required()
def symbol_latest(symbol: str):
    """
    Return the most recent stored snapshot for symbol.

    Query params:
      expiry : optional expiry filter
    """
    try:
        sym    = symbol.upper().strip()
        expiry = request.args.get("expiry") or None
        snap   = get_latest_snapshot(sym, expiry=expiry)
        if snap is None:
            return _err(f"No snapshots found for {sym}", status=404)
        return _ok(snap.to_dict())
    except Exception as exc:
        logger.error("latest error %s: %s", symbol, exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/history/<symbol>/trend
# ---------------------------------------------------------------------------

@history_bp.route("/<string:symbol>/trend", methods=["GET"])
@jwt_required()
def trend(symbol: str):
    """
    Time-series of spot, max_pain, distance_pct, pcr, avg_iv for plotting.

    Query params: window, expiry, max_points
    """
    try:
        data = get_max_pain_trend(
            symbol=symbol.upper(),
            window=_window(),
            expiry=request.args.get("expiry") or None,
            max_points=int(request.args.get("max_points", 200)),
        )
        return _ok(data)
    except Exception as exc:
        logger.error("trend error %s: %s", symbol, exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/history/<symbol>/drift
# ---------------------------------------------------------------------------

@history_bp.route("/<string:symbol>/drift", methods=["GET"])
@jwt_required()
def drift(symbol: str):
    """
    Max pain drift — how far max pain moved since window start.

    Query params: window, expiry
    """
    try:
        data = get_max_pain_drift(
            symbol=symbol.upper(),
            window=_window(),
            expiry=request.args.get("expiry") or None,
        )
        return _ok(data)
    except Exception as exc:
        logger.error("drift error %s: %s", symbol, exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/history/<symbol>/oi-wall
# ---------------------------------------------------------------------------

@history_bp.route("/<string:symbol>/oi-wall", methods=["GET"])
@jwt_required()
def oi_wall_migration(symbol: str):
    """
    OI wall migration history.

    Query params: side=CE|PE, rank=1, window, expiry
    """
    try:
        side = request.args.get("side", "CE").upper()
        rank = int(request.args.get("rank", 1))
        if side not in ("CE", "PE"):
            return _err("side must be CE or PE", status=400)

        data = get_oi_wall_migration(
            symbol=symbol.upper(),
            side=side,
            rank=rank,
            window=_window(),
            expiry=request.args.get("expiry") or None,
        )
        return _ok(data)
    except Exception as exc:
        logger.error("oi-wall error %s: %s", symbol, exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/history/latest  (multi-symbol)
# ---------------------------------------------------------------------------

@history_bp.route("/latest", methods=["GET"])
@jwt_required()
def latest_snapshots():
    """
    Latest snapshot for multiple symbols.

    Query params:
      symbols : comma-separated, e.g. "NIFTY,BANKNIFTY,RELIANCE"
    """
    try:
        symbols_param = request.args.get("symbols", "")
        symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
        if not symbols:
            return _err("symbols param required", status=400)

        results = []
        for sym in symbols:
            snap = get_latest_snapshot(sym)
            if snap:
                results.append(snap.to_dict())

        return _ok({"count": len(results), "snapshots": results})
    except Exception as exc:
        logger.error("latest snapshots error: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# POST /api/max-pain/history/capture
# ---------------------------------------------------------------------------

@history_bp.route("/capture", methods=["POST"])
@jwt_required()
def manual_capture():
    """
    Immediately capture snapshots for the given symbols.

    Body (JSON):
      { "symbols": ["NIFTY", "BANKNIFTY"], "expiry": "25-Jul-2024" }

    Omit symbols to capture the full default universe.
    """
    try:
        body    = request.get_json(silent=True) or {}
        symbols = body.get("symbols") or None
        expiry  = body.get("expiry") or None

        from app.services.max_pain_scanner_service import DEFAULT_FO_UNIVERSE
        target = symbols or DEFAULT_FO_UNIVERSE

        result = capture_symbols(target, expiry=expiry)
        return _ok(result)
    except Exception as exc:
        logger.error("manual capture error: %s", exc)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# POST /api/max-pain/history/cleanup
# ---------------------------------------------------------------------------

@history_bp.route("/cleanup", methods=["POST"])
@jwt_required()
def manual_cleanup():
    """
    Trigger snapshot retention cleanup.

    Body (JSON, optional):
      { "retention_days": 30 }

    Defaults to MAX_PAIN_RETENTION_DAYS from app config.
    """
    try:
        body      = request.get_json(silent=True) or {}
        retention = int(
            body.get("retention_days")
            or current_app.config.get("MAX_PAIN_RETENTION_DAYS", 90)
        )
        deleted = cleanup_old_snapshots(retention)
        return _ok({"deleted": deleted, "retention_days": retention})
    except Exception as exc:
        logger.error("cleanup error: %s", exc)
        return _err(str(exc))
