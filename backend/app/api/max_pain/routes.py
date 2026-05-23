"""
Max Pain Deviation Scanner API Routes
Data source: NSE option chain via headless Chromium (no per-user credentials needed).
"""

import logging
import threading
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services import nse_playwright_service as nse_pw
from app.services.scan_snapshot_service import (
    save_scan_snapshot,
    get_latest_snapshot,
    get_snapshot_history,
    load_snapshot_payload,
)
from app.services.max_pain_scanner_service import (
    run_scanner,
    scan_symbol,
    build_summary,
    _scan_symbol_internal,
    DEFAULT_FO_UNIVERSE,
)
from app.services.option_chain_monitor import monitor
from app.services.max_pain_engine import MaxPainError, calculate_max_pain, get_oi_walls

logger = logging.getLogger(__name__)

max_pain_bp = Blueprint("max_pain", __name__, url_prefix="/api/max-pain")

# Prevents two concurrent full-universe scans from colliding on the shared browser page
_scan_lock = threading.Lock()


# ── /scan ─────────────────────────────────────────────────────────────────────

@max_pain_bp.route("/scan", methods=["GET"])
@jwt_required()
def scan():
    if not _scan_lock.acquire(blocking=False):
        # A scan is already running — return the latest snapshot immediately
        logger.info("[SCAN /scan] Scan already in progress, returning cached snapshot")
        snapshot = get_latest_snapshot()
        if snapshot:
            return jsonify({**snapshot, "using_snapshot": True, "snapshot_reason": "scan_in_progress"}), 200
        return jsonify({"error": "Scan already in progress, please try again shortly"}), 429
    try:
        threshold     = float(request.args.get("threshold", 2.0))
        symbols_param = request.args.get("symbols", "")
        expiry        = request.args.get("expiry", None) or None

        symbols = (
            [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
            if symbols_param else None
        )
        symbol_count = len(symbols) if symbols else len(DEFAULT_FO_UNIVERSE)

        logger.info(
            "[SCAN /scan] threshold=%.1f%% symbols=%s expiry=%s",
            threshold, symbols or f"default({symbol_count})", expiry or "nearest",
        )

        # Run live scan at threshold=0 (capture full universe; filter in Python)
        result_full = run_scanner(
            symbols       = symbols,
            threshold_pct = 0.0,
            expiry        = expiry,
        )

        all_live           = result_full.get("results", [])
        market_closed_list = result_full.get("market_closed", [])
        has_live_data      = len(all_live) > 0

        # Apply user's threshold filter
        live_results      = [r for r in all_live if r.get("distance_pct", 0) >= threshold]
        below_from_filter = [r["symbol"] for r in all_live if r.get("distance_pct", 0) < threshold]
        full_below        = result_full.get("below_threshold", []) + below_from_filter

        metrics_out = {
            **result_full.get("metrics", {}),
            "returned_results":   len(live_results),
            "threshold_filtered": len(full_below),
        }
        summary_out = build_summary(
            live_results,
            total_scanned         = symbol_count,
            total_errors          = len(result_full.get("errors", [])),
            total_below_threshold = len(full_below),
            total_market_closed   = len(market_closed_list),
        )

        if has_live_data:
            save_scan_snapshot(result_full, threshold=0.0)

        result = {
            **result_full,
            "results":         live_results,
            "below_threshold": full_below,
            "summary":         summary_out,
            "metrics":         metrics_out,
        }

        # ── Snapshot fallback when no live data ───────────────────────────────
        using_snapshot   = False
        snapshot_age_min = None
        snapshot_created = None
        fallback_reason  = None

        if not has_live_data:
            if len(market_closed_list) > 0:
                fallback_reason = f"market_closed({len(market_closed_list)})"
            elif len(result_full.get("errors", [])) > 0:
                fallback_reason = f"nse_errors({len(result_full.get('errors', []))})"
            else:
                fallback_reason = "no_results"

            logger.info("[SCAN /scan] no live data (reason=%s) — snapshot fallback", fallback_reason)
            snapshot = get_latest_snapshot(threshold=None)

            if snapshot is not None:
                payload = load_snapshot_payload(snapshot)
                if payload is not None:
                    snap_all      = payload.get("results", [])
                    snap_filtered = [r for r in snap_all if r.get("distance_pct", 0) >= threshold]
                    snap_below    = payload.get("below_threshold", []) + [
                        r["symbol"] for r in snap_all if r.get("distance_pct", 0) < threshold
                    ]
                    snap_summary  = build_summary(
                        snap_filtered,
                        total_scanned         = symbol_count,
                        total_errors          = len(payload.get("errors", [])),
                        total_below_threshold = len(snap_below),
                        total_market_closed   = len(payload.get("market_closed", [])),
                    )
                    result = {
                        **payload,
                        "results":         snap_filtered,
                        "below_threshold": snap_below,
                        "summary":         snap_summary,
                    }
                    using_snapshot   = True
                    snapshot_age_min = round(snapshot.age_minutes(), 1)
                    snapshot_created = snapshot.created_at.isoformat()

        return jsonify({
            "success":                  True,
            "data":                     result,
            "nse_ok":                   len(result.get("errors", [])) == 0,
            "market_closed":            len(market_closed_list) > 0,
            "using_snapshot_fallback":  using_snapshot,
            "snapshot_age_minutes":     snapshot_age_min,
            "snapshot_created_at":      snapshot_created,
            "snapshot_fallback_reason": fallback_reason,
            "broker_connected":         True,   # NSE needs no credentials
            "broker_token_invalid":     False,
            "data_source":              "nse",
            "meta": {
                "threshold_pct":     threshold,
                "symbols_requested": symbol_count,
                "generated_at":      datetime.now(timezone.utc).isoformat(),
                "metrics":           metrics_out,
            },
        }), 200

    except Exception as exc:
        logger.error("[SCAN /scan] Unexpected error: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        _scan_lock.release()


# ── /symbol/<symbol> ──────────────────────────────────────────────────────────

@max_pain_bp.route("/symbol/<string:symbol>", methods=["GET"])
@jwt_required()
def symbol_detail(symbol: str):
    try:
        symbol = symbol.upper().strip()
        expiry = request.args.get("expiry", None) or None

        chain = nse_pw.get_option_chain(symbol, expiry=expiry)
        mp    = calculate_max_pain(chain)
        walls = get_oi_walls(chain)

        return jsonify({"success": True, "data": {
            "symbol":       symbol,
            "spot_price":   mp.spot_price,
            "max_pain":     mp.max_pain,
            "distance_pct": mp.distance_pct,
            "pcr":          mp.pcr,
            "total_ce_oi":  mp.total_ce_oi,
            "total_pe_oi":  mp.total_pe_oi,
            "pain_values":  [p.to_dict() for p in mp.pain_curve],
            "ce_wall":      walls.ce_wall.to_dict(),
            "pe_wall":      walls.pe_wall.to_dict(),
            "all_expiries": chain.all_expiries,
            "expiry":       chain.expiry,
            "timestamp":    chain.timestamp,
        }}), 200

    except Exception as exc:
        logger.error("Symbol detail error for %s: %s", symbol, exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── /universe ─────────────────────────────────────────────────────────────────

@max_pain_bp.route("/universe", methods=["GET"])
@jwt_required()
def universe():
    return jsonify({"success": True, "data": {"symbols": DEFAULT_FO_UNIVERSE}}), 200


# ── /<symbol> (legacy) ────────────────────────────────────────────────────────

@max_pain_bp.route("/<string:symbol>", methods=["GET"])
@jwt_required()
def max_pain_for_symbol(symbol: str):
    try:
        symbol  = symbol.upper().strip()
        expiry  = request.args.get("expiry") or None
        chain   = nse_pw.get_option_chain(symbol, expiry=expiry)
        result  = calculate_max_pain(chain)
        data    = result.to_dict()
        data.update({"symbol": chain.symbol, "expiry": chain.expiry,
                     "all_expiries": chain.all_expiries, "timestamp": chain.timestamp})
        return jsonify({"success": True, "data": data}), 200
    except MaxPainError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "CALC_ERROR"}), 422
    except Exception as exc:
        logger.error("Max pain error for %s: %s", symbol, exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── /option-chain/<symbol> ────────────────────────────────────────────────────

@max_pain_bp.route("/option-chain/<string:symbol>", methods=["GET"])
@jwt_required()
def option_chain(symbol: str):
    try:
        symbol = symbol.upper().strip()
        expiry = request.args.get("expiry", None) or None
        chain  = nse_pw.get_option_chain(symbol, expiry=expiry)
        return jsonify({"success": True, "data": chain.to_dict()}), 200
    except Exception as exc:
        logger.error("Option chain error for %s: %s", symbol, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── /snapshots ────────────────────────────────────────────────────────────────

@max_pain_bp.route("/snapshots/latest", methods=["GET"])
@jwt_required()
def snapshots_latest():
    threshold_raw = request.args.get("threshold")
    threshold     = float(threshold_raw) if threshold_raw is not None else None
    snapshot = get_latest_snapshot(threshold=threshold)
    if snapshot is None and threshold is not None:
        snapshot = get_latest_snapshot(threshold=None)
    if snapshot is None:
        return jsonify({"snapshot_found": False,
                        "message": "No snapshots yet. Run a scan during market hours first."}), 200
    payload = load_snapshot_payload(snapshot)
    if payload is None:
        return jsonify({"snapshot_found": False, "message": "Snapshot payload could not be decoded."}), 200
    return jsonify({
        "snapshot_found":  True,
        "created_at":      snapshot.created_at.isoformat(),
        "age_minutes":     round(snapshot.age_minutes(), 1),
        "threshold":       snapshot.threshold,
        "symbol_count":    snapshot.symbol_count,
        "avg_fetch_ms":    snapshot.avg_fetch_ms,
        "scan_elapsed_ms": snapshot.scan_elapsed_ms,
        "market_status":   snapshot.market_status,
        "data":            payload,
    }), 200


@max_pain_bp.route("/snapshots/history", methods=["GET"])
@jwt_required()
def snapshots_history():
    limit   = min(100, max(1, int(request.args.get("limit", 20))))
    history = get_snapshot_history(limit=limit)
    return jsonify({"success": True, "count": len(history), "data": history}), 200


# ── /debug/snapshots ─────────────────────────────────────────────────────────

@max_pain_bp.route("/debug/snapshots", methods=["GET"])
def debug_snapshots():
    import re, os as _os
    raw_uri  = _os.getenv("DATABASE_URL", "unknown")
    safe_uri = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", raw_uri)
    try:
        from app.services.scan_snapshot_service import count_snapshots
        from app.models.scan_snapshot import ScanSnapshot
        from app.extensions import db
        from sqlalchemy import distinct
        total      = count_snapshots()
        thresholds = [r[0] for r in db.session.execute(
            db.select(distinct(ScanSnapshot.threshold)).order_by(ScanSnapshot.threshold)
        ).all()]
        sample  = get_snapshot_history(limit=5)
        newest  = get_latest_snapshot(threshold=None)
        return jsonify({
            "success": True, "db_uri": safe_uri, "total_snapshots": total,
            "thresholds": thresholds, "newest": newest.to_meta() if newest else None,
            "recent": sample, "generated_at": datetime.now(timezone.utc).isoformat(),
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "db_uri": safe_uri, "error": str(exc)}), 500


# ── /debug/nse-status ────────────────────────────────────────────────────────

@max_pain_bp.route("/debug/nse-status", methods=["GET"])
def debug_nse_status():
    return jsonify({
        "success": True,
        "data": {
            "browser_ready": nse_pw.is_ready(),
            "data_source":   "playwright+chromium",
            "generated_at":  datetime.now(timezone.utc).isoformat(),
        }
    }), 200


# ── /debug/test-symbol/<symbol> ───────────────────────────────────────────────

@max_pain_bp.route("/debug/test-symbol/<string:symbol>", methods=["GET"])
def debug_test_symbol(symbol: str):
    symbol = symbol.upper().strip()
    expiry = request.args.get("expiry") or None
    diag   = {"symbol": symbol, "expiry": expiry, "stages": {}, "success": False,
               "generated_at": datetime.now(timezone.utc).isoformat()}
    try:
        chain = nse_pw.get_option_chain(symbol, expiry=expiry)
        diag["stages"]["nse_fetch"] = {
            "ok": True, "strikes": len(chain.strikes), "expiry": chain.expiry,
            "all_expiries": chain.all_expiries, "spot_price": chain.spot_price,
            "total_ce_oi": chain.total_ce_oi, "total_pe_oi": chain.total_pe_oi,
        }
    except Exception as exc:
        diag["stages"]["nse_fetch"] = {"ok": False, "error": str(exc)}
        return jsonify({"success": False, "data": diag}), 200

    try:
        mp = calculate_max_pain(chain)
        diag["stages"]["max_pain"] = {
            "ok": True, "max_pain": mp.max_pain, "spot_price": mp.spot_price,
            "distance_pct": mp.distance_pct, "pcr": mp.pcr,
        }
        result, skip_reason, error_msg = _scan_symbol_internal(symbol, expiry, 0.0)
        diag["stages"]["full_scan"] = {
            "ok": result is not None, "skip_reason": skip_reason, "error": error_msg,
            "distance_pct": result.get("distance_pct") if result else None,
        }
        if result:
            diag["result"]  = result
            diag["success"] = True
    except Exception as exc:
        diag["stages"]["error"] = str(exc)

    return jsonify({"success": diag["success"], "data": diag}), 200


# ── /debug/raw-scan ───────────────────────────────────────────────────────────

@max_pain_bp.route("/debug/raw-scan", methods=["GET"])
def debug_raw_scan():
    symbols_param = request.args.get("symbols", "")
    expiry        = request.args.get("expiry") or None
    symbols = (
        [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
        if symbols_param else DEFAULT_FO_UNIVERSE[:5]
    )
    result = run_scanner(symbols=symbols, threshold_pct=0.0, expiry=expiry)
    return jsonify({
        "success": True, "data": result,
        "meta": {"threshold_pct": 0.0, "symbols_tested": symbols,
                 "generated_at": datetime.now(timezone.utc).isoformat()},
    }), 200


# ── /debug/live-scan ──────────────────────────────────────────────────────────

@max_pain_bp.route("/debug/live-scan", methods=["GET"])
def debug_live_scan():
    import time as _time
    symbols_param = request.args.get("symbols", "")
    expiry        = request.args.get("expiry") or None
    threshold     = float(request.args.get("threshold", 2.0))
    symbols = (
        [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
        if symbols_param else DEFAULT_FO_UNIVERSE[:10]
    )
    rows_out = []
    for sym in symbols:
        entry = {"symbol": sym, "fetch_ok": False, "rows": 0, "spot": None,
                 "max_pain": None, "distance_pct": None, "threshold_pass": False,
                 "market_closed": False, "error": None, "fetch_ms": None}
        t0 = _time.monotonic()
        try:
            from app.services.nse_option_chain_service import NSEMarketClosedError, NSEFetchError, NSEDataError
            chain = nse_pw.get_option_chain(sym, expiry=expiry)
            entry["fetch_ok"] = True
            entry["fetch_ms"] = round((_time.monotonic() - t0) * 1000)
            entry["rows"]     = len(chain.strikes)
            entry["spot"]     = chain.spot_price
            if chain.strikes:
                mp = calculate_max_pain(chain)
                entry["max_pain"]      = mp.max_pain
                entry["distance_pct"]  = round(mp.distance_pct, 4)
                entry["threshold_pass"] = mp.distance_pct >= threshold
        except Exception as exc:
            entry["fetch_ms"]      = round((_time.monotonic() - t0) * 1000)
            entry["market_closed"] = "closed" in str(exc).lower()
            entry["error"]         = str(exc)
        rows_out.append(entry)

    return jsonify({
        "success": True,
        "data": {"symbols": rows_out, "summary": {
            "total": len(rows_out),
            "fetch_ok": sum(1 for r in rows_out if r["fetch_ok"]),
            "market_closed": sum(1 for r in rows_out if r["market_closed"]),
            "threshold_pass": sum(1 for r in rows_out if r["threshold_pass"]),
        }},
        "meta": {"threshold": threshold, "expiry": expiry or "nearest",
                 "generated_at": datetime.now(timezone.utc).isoformat()},
    }), 200
