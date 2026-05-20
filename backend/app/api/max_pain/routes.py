"""
Max Pain Deviation Scanner API Routes
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.scan_snapshot_service import (
    save_scan_snapshot,
    get_latest_snapshot,
    get_snapshot_history,
    load_snapshot_payload,
)
from app.services.max_pain_scanner_service import (
    run_scanner,
    scan_symbol,
    _scan_symbol_internal,
    DEFAULT_FO_UNIVERSE,
)
from app.services.nse_option_chain_service import (
    get_option_chain,
    _get_service as _get_nse_service,
    NSEMarketClosedError,
    _extract_nse_payload,
)
from app.services.option_chain_monitor import monitor
from app.services.max_pain_engine import MaxPainError, calculate_max_pain, get_oi_walls

logger = logging.getLogger(__name__)

max_pain_bp = Blueprint("max_pain", __name__, url_prefix="/api/max-pain")


# ---------------------------------------------------------------------------
# /scan — main scanner endpoint
# ---------------------------------------------------------------------------

@max_pain_bp.route("/scan", methods=["GET"])
@jwt_required()
def scan():
    """
    Run the deviation scanner across the F&O universe.

    Query params:
      threshold  : float (default 2.0) — minimum deviation % to include
      symbols    : comma-separated symbol list (default: full FO universe)
      expiry     : expiry date string (default: nearest)
    """
    try:
        threshold = float(request.args.get("threshold", 2.0))
        symbols_param = request.args.get("symbols", "")
        expiry = request.args.get("expiry", None) or None

        symbols = (
            [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
            if symbols_param
            else None
        )

        logger.info(
            "[SCAN /scan] threshold=%.1f%% symbols=%s expiry=%s",
            threshold,
            symbols or f"default({len(DEFAULT_FO_UNIVERSE)})",
            expiry or "nearest",
        )

        result = run_scanner(
            symbols=symbols,
            threshold_pct=threshold,
            expiry=expiry,
            max_workers=6,
        )

        metrics = result.get("metrics", {})
        logger.info(
            "[SCAN /scan] done — hits=%d errors=%d below_threshold=%d "
            "market_closed=%d fetch_success=%d avg_fetch_ms=%.0f",
            len(result["results"]),
            len(result["errors"]),
            len(result.get("below_threshold", [])),
            len(result.get("market_closed", [])),
            metrics.get("fetch_success", 0),
            metrics.get("avg_fetch_ms", 0),
        )

        live_results        = result.get("results", [])
        market_closed_list  = result.get("market_closed", [])
        market_closed_count = len(market_closed_list)
        has_live_data       = len(live_results) > 0

        logger.info(
            "[SCAN /scan] fallback-check — has_live_data=%s live=%d "
            "market_closed=%d errors=%d threshold=%.2f",
            has_live_data, len(live_results), market_closed_count,
            len(result.get("errors", [])), threshold,
        )

        # ── Persist successful scan ──────────────────────────────────────────
        if has_live_data:
            save_scan_snapshot(result, threshold=threshold)

        # ── Snapshot fallback — any time there are no live results ─────────────
        # Deliberately does NOT require market_closed_count > 0:
        # NSE can return errors (timeouts, TLS failures) instead of explicit
        # market-closed signals, so we fall back to the latest snapshot
        # whenever live data is absent for any reason.
        using_snapshot   = False
        snapshot_age_min = None
        snapshot_created = None
        fallback_reason  = None

        if not has_live_data:
            if market_closed_count > 0:
                fallback_reason = f"market_closed({market_closed_count})"
            elif len(result.get("errors", [])) > 0:
                fallback_reason = f"nse_errors({len(result.get('errors', []))})"
            else:
                fallback_reason = "no_results"

            logger.info(
                "[SCAN /scan] no live data (reason=%s) — "
                "attempting snapshot fallback (threshold=%.2f)",
                fallback_reason, threshold,
            )
            # get_latest_snapshot does its own two-step lookup internally:
            # 1) approx threshold match, 2) any-threshold fallback
            snapshot = get_latest_snapshot(threshold=threshold)

            if snapshot is not None:
                payload = load_snapshot_payload(snapshot)
                if payload is not None:
                    result           = payload
                    using_snapshot   = True
                    snapshot_age_min = round(snapshot.age_minutes(), 1)
                    snapshot_created = snapshot.created_at.isoformat()
                    logger.info(
                        "[SCAN /scan] SNAPSHOT ACTIVE id=%s age=%.1fmin "
                        "results=%d reason=%s",
                        str(snapshot.id)[:8], snapshot_age_min,
                        len(payload.get("results", [])), fallback_reason,
                    )
                else:
                    logger.warning(
                        "[SCAN /scan] snapshot id=%s found but payload "
                        "decode failed — frontend will show empty state",
                        str(snapshot.id)[:8],
                    )
            else:
                logger.info(
                    "[SCAN /scan] no snapshot found (reason=%s) — "
                    "frontend will show 'no snapshot available' message",
                    fallback_reason,
                )

        return jsonify({
            "success":       True,
            "data":          result,
            "nse_ok":        len(result.get("errors", [])) == 0,
            "market_closed": market_closed_count > 0,
            "using_snapshot_fallback":  using_snapshot,
            "snapshot_age_minutes":     snapshot_age_min,
            "snapshot_created_at":      snapshot_created,
            "snapshot_fallback_reason": fallback_reason,
            "meta": {
                "threshold_pct":       threshold,
                "symbols_requested":   len(symbols) if symbols else len(DEFAULT_FO_UNIVERSE),
                "generated_at":        datetime.now(timezone.utc).isoformat(),
                "metrics":             metrics,
            },
        }), 200

    except Exception as exc:
        logger.error("[SCAN /scan] Unexpected error: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /symbol/<symbol> — single symbol detail
# ---------------------------------------------------------------------------

@max_pain_bp.route("/symbol/<string:symbol>", methods=["GET"])
@jwt_required()
def symbol_detail(symbol: str):
    """
    Get full max pain analysis for a single symbol.

    Query params:
      expiry : expiry date string (default: nearest)
    """
    try:
        symbol = symbol.upper().strip()
        expiry = request.args.get("expiry", None) or None

        result = scan_symbol(symbol, expiry=expiry, threshold_pct=0.0)
        if result is None:
            chain = get_option_chain(symbol, expiry=expiry)
            mp    = calculate_max_pain(chain)
            walls = get_oi_walls(chain)
            result = {
                "symbol":      symbol,
                "spot_price":  mp.spot_price,
                "max_pain":    mp.max_pain,
                "distance_pct": mp.distance_pct,
                "pcr":         mp.pcr,
                "total_ce_oi": mp.total_ce_oi,
                "total_pe_oi": mp.total_pe_oi,
                "pain_values": [p.to_dict() for p in mp.pain_curve],
                "ce_wall":     walls.ce_wall.to_dict(),
                "pe_wall":     walls.pe_wall.to_dict(),
                "all_expiries": chain.all_expiries,
                "expiry":      chain.expiry,
                "timestamp":   chain.timestamp,
            }

        return jsonify({"success": True, "data": result}), 200

    except Exception as exc:
        logger.error("Symbol detail error for %s: %s", symbol, exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /universe
# ---------------------------------------------------------------------------

@max_pain_bp.route("/universe", methods=["GET"])
@jwt_required()
def universe():
    """Return the default F&O universe list."""
    return jsonify({"success": True, "data": {"symbols": DEFAULT_FO_UNIVERSE}}), 200


# ---------------------------------------------------------------------------
# /<symbol> — max pain for one symbol (legacy route)
# ---------------------------------------------------------------------------

@max_pain_bp.route("/<string:symbol>", methods=["GET"])
@jwt_required()
def max_pain_for_symbol(symbol: str):
    try:
        symbol  = symbol.upper().strip()
        expiry  = request.args.get("expiry") or None
        refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")

        chain  = get_option_chain(symbol, expiry=expiry)
        result = calculate_max_pain(chain)

        data = result.to_dict()
        data["symbol"]       = chain.symbol
        data["expiry"]       = chain.expiry
        data["all_expiries"] = chain.all_expiries
        data["timestamp"]    = chain.timestamp

        return jsonify({"success": True, "data": data}), 200

    except MaxPainError as exc:
        logger.warning("Max pain calculation error for %s: %s", symbol, exc)
        return jsonify({"success": False, "error": str(exc), "code": "CALC_ERROR"}), 422
    except Exception as exc:
        logger.error("Max pain error for %s: %s", symbol, exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /option-chain/<symbol>
# ---------------------------------------------------------------------------

@max_pain_bp.route("/option-chain/<string:symbol>", methods=["GET"])
@jwt_required()
def option_chain(symbol: str):
    try:
        symbol = symbol.upper().strip()
        expiry = request.args.get("expiry", None) or None
        chain = get_option_chain(symbol, expiry=expiry)
        return jsonify({"success": True, "data": chain.to_dict()}), 200
    except Exception as exc:
        logger.error("Option chain error for %s: %s", symbol, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /snapshots — scan snapshot endpoints
# ---------------------------------------------------------------------------

@max_pain_bp.route("/snapshots/latest", methods=["GET"])
@jwt_required()
def snapshots_latest():
    """
    Return the most recent successful scan snapshot, optionally filtered
    by threshold.

    Query params:
      threshold : float — if provided, only snapshots at this threshold
                          are considered; falls back to any threshold if
                          none found.

    Response:
      {
        "snapshot_found": true,
        "created_at":     "2026-05-20T09:30:00+00:00",
        "age_minutes":    42.3,
        "threshold":      2.0,
        "symbol_count":   46,
        "data":           { ...full run_scanner() payload... }
      }
    """
    threshold_raw = request.args.get("threshold")
    threshold     = float(threshold_raw) if threshold_raw is not None else None

    snapshot = get_latest_snapshot(threshold=threshold)
    # Fallback: if threshold-specific misses, try any snapshot
    if snapshot is None and threshold is not None:
        snapshot = get_latest_snapshot(threshold=None)

    if snapshot is None:
        return jsonify({
            "snapshot_found": False,
            "message":        "No scan snapshots have been saved yet. "
                              "Run a scan during market hours first.",
        }), 200

    payload = load_snapshot_payload(snapshot)
    if payload is None:
        return jsonify({
            "snapshot_found": False,
            "message":        "Snapshot exists but payload could not be decoded.",
        }), 200

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
    """
    Return metadata for the N most recent scan snapshots (no payload).

    Query params:
      limit : int (default 20, max 100)
    """
    limit = min(100, max(1, int(request.args.get("limit", 20))))
    history = get_snapshot_history(limit=limit)
    return jsonify({
        "success": True,
        "count":   len(history),
        "data":    history,
    }), 200


# ---------------------------------------------------------------------------
# /debug/snapshots — snapshot diagnostic endpoint (no JWT)
# ---------------------------------------------------------------------------

@max_pain_bp.route("/debug/snapshots", methods=["GET"])
def debug_snapshots():
    """
    Snapshot store diagnostic — no JWT required.

    Returns:
      total_snapshots, db_uri, newest snapshot metadata,
      all distinct thresholds present, sample IDs.

    Usage:
        curl http://localhost:3010/api/max-pain/debug/snapshots
    """
    import re
    import os as _os

    raw_uri  = _os.getenv("DATABASE_URL", "unknown")
    safe_uri = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", raw_uri)

    try:
        from app.services.scan_snapshot_service import (
            count_snapshots, get_snapshot_history, get_latest_snapshot,
        )
        from app.models.scan_snapshot import ScanSnapshot
        from app.extensions import db
        from sqlalchemy import func, distinct

        total = count_snapshots()

        # All distinct thresholds
        thresholds = [
            row[0] for row in
            db.session.execute(
                db.select(distinct(ScanSnapshot.threshold))
                .order_by(ScanSnapshot.threshold)
            ).all()
        ]

        # Newest 5 IDs
        sample = get_snapshot_history(limit=5)

        newest = get_latest_snapshot(threshold=None)
        newest_meta = newest.to_meta() if newest else None

        return jsonify({
            "success":          True,
            "db_uri":           safe_uri,
            "total_snapshots":  total,
            "thresholds":       thresholds,
            "newest":           newest_meta,
            "recent":           sample,
            "generated_at":     datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as exc:
        logger.error("[debug/snapshots] error: %s", exc, exc_info=True)
        return jsonify({
            "success": False,
            "db_uri":  safe_uri,
            "error":   str(exc),
        }), 500


# ---------------------------------------------------------------------------
# DEBUG ENDPOINTS (no JWT — for rapid local diagnosis)
# Remove or add @jwt_required() before going to production.
# ---------------------------------------------------------------------------

@max_pain_bp.route("/debug/nse-status", methods=["GET"])
def debug_nse_status():
    """
    Return NSE fetcher health: session age, cache stats, fetch success rates,
    and a live connectivity probe against the NSE homepage.
    """
    import requests as req_lib

    # -- Monitor stats (from singleton) -----------------------------------------
    fetcher   = monitor.fetcher_stats()
    cache     = monitor.cache_stats()
    validation = monitor.validation_stats()
    session   = monitor.session_stats()

    # -- Live connectivity probe ------------------------------------------------
    probe = {"reachable": False, "status_code": None, "error": None, "latency_ms": None}
    try:
        import time
        t0 = time.monotonic()
        r = req_lib.get(
            "https://www.nseindia.com",
            timeout=10,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
                )
            },
            allow_redirects=True,
        )
        probe["latency_ms"]  = round((time.monotonic() - t0) * 1000)
        probe["status_code"] = r.status_code
        probe["reachable"]   = r.status_code < 400
        ct = r.headers.get("Content-Type", "")
        probe["content_type"] = ct
        # Check if we got HTML or JSON (block page vs homepage)
        probe["looks_like_block"] = any(
            kw in r.text[:500].lower()
            for kw in ["captcha", "access denied", "blocked", "cloudflare"]
        )
    except Exception as exc:
        probe["error"] = str(exc)

    return jsonify({
        "success": True,
        "data": {
            "nse_probe":       probe,
            "fetcher":         fetcher,
            "cache":           cache,
            "validation":      validation,
            "session":         session,
            "symbols_tracked": monitor.all_symbols(),
            "generated_at":    datetime.now(timezone.utc).isoformat(),
        }
    }), 200


@max_pain_bp.route("/debug/test-symbol/<string:symbol>", methods=["GET"])
def debug_test_symbol(symbol: str):
    """
    Run a full diagnostic for a single symbol — bypasses threshold filter
    and returns raw data + errors at every stage.

    Usage:
      GET /api/max-pain/debug/test-symbol/RELIANCE
      GET /api/max-pain/debug/test-symbol/NIFTY?expiry=26-Jun-2025
    """
    symbol = symbol.upper().strip()
    expiry = request.args.get("expiry") or None

    diag = {
        "symbol":  symbol,
        "expiry":  expiry,
        "stages":  {},
        "success": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Stage 1: NSE fetch
    try:
        chain = get_option_chain(symbol, expiry=expiry)
        diag["stages"]["nse_fetch"] = {
            "ok":          True,
            "strikes":     len(chain.strikes),
            "expiry":      chain.expiry,
            "all_expiries": chain.all_expiries,
            "spot_price":  chain.spot_price,
            "total_ce_oi": chain.total_ce_oi,
            "total_pe_oi": chain.total_pe_oi,
            "pcr":         chain.pcr,
            "atm_ce_iv":   chain.atm_ce_iv,
            "atm_pe_iv":   chain.atm_pe_iv,
            "from_cache":  chain.fetched_from_cache,
        }
    except Exception as exc:
        diag["stages"]["nse_fetch"] = {"ok": False, "error": str(exc)}
        logger.error("[DEBUG test-symbol] NSE fetch failed for %s: %s", symbol, exc, exc_info=True)
        return jsonify({"success": False, "data": diag, "error": f"NSE fetch failed: {exc}"}), 200

    chain_data = chain

    # Stage 2: Max pain calculation
    try:
        mp = calculate_max_pain(chain_data)
        diag["stages"]["max_pain"] = {
            "ok":           True,
            "max_pain":     mp.max_pain,
            "spot_price":   mp.spot_price,
            "distance_pct": mp.distance_pct,
            "distance_abs": mp.distance_from_spot,
            "pcr":          mp.pcr,
            "total_ce_oi":  mp.total_ce_oi,
            "total_pe_oi":  mp.total_pe_oi,
            "ce_wall":      mp.ce_wall.to_dict() if mp.ce_wall else None,
            "pe_wall":      mp.pe_wall.to_dict() if mp.pe_wall else None,
            "pain_curve_points": len(mp.pain_curve),
        }
    except Exception as exc:
        diag["stages"]["max_pain"] = {"ok": False, "error": str(exc)}
        return jsonify({"success": False, "data": diag, "error": f"Max pain calc failed: {exc}"}), 200

    # Stage 3: Full scan (threshold=0 to bypass filter)
    try:
        result, skip_reason, error_msg = _scan_symbol_internal(symbol, expiry, threshold_pct=0.0)
        diag["stages"]["full_scan"] = {
            "ok":          result is not None,
            "skip_reason": skip_reason,
            "error":       error_msg,
            "result_keys": list(result.keys()) if result else None,
            "distance_pct": result.get("distance_pct") if result else None,
            "reversal_score": result.get("reversal_score") if result else None,
        }
        if result:
            diag["result"] = result
            diag["success"] = True
    except Exception as exc:
        diag["stages"]["full_scan"] = {"ok": False, "error": str(exc)}

    # Per-symbol monitor stats
    sym_stats = monitor.per_symbol_stats(symbol)
    diag["monitor"] = sym_stats

    return jsonify({"success": diag["success"], "data": diag}), 200


@max_pain_bp.route("/debug/raw-scan", methods=["GET"])
def debug_raw_scan():
    """
    Run the scanner with threshold=0 (no filtering) so ALL successfully fetched
    symbols appear in the output.  Used to verify the pipeline works end-to-end
    independently of threshold tuning.

    Query params:
      symbols  : comma-separated (default: first 5 of default universe)
      expiry   : specific expiry (default: nearest)
      workers  : int 1–10 (default: 3)
    """
    symbols_param = request.args.get("symbols", "")
    expiry        = request.args.get("expiry") or None
    workers       = min(10, max(1, int(request.args.get("workers", 3))))

    if symbols_param:
        symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    else:
        # Default: first 5 symbols to keep the debug call fast
        symbols = DEFAULT_FO_UNIVERSE[:5]

    logger.info(
        "[DEBUG raw-scan] symbols=%s expiry=%s workers=%d",
        symbols, expiry or "nearest", workers,
    )

    result = run_scanner(
        symbols=symbols,
        threshold_pct=0.0,   # ← bypass ALL threshold filtering
        expiry=expiry,
        max_workers=workers,
    )

    return jsonify({
        "success": True,
        "data":    result,
        "meta": {
            "threshold_pct":    0.0,
            "note":             "Threshold is 0 — all successfully fetched symbols are returned",
            "symbols_tested":   symbols,
            "generated_at":     datetime.now(timezone.utc).isoformat(),
        },
    }), 200


@max_pain_bp.route("/debug/live-scan", methods=["GET"])
def debug_live_scan():
    """
    Per-symbol pipeline verification for the first N symbols.
    Returns a row per symbol showing exactly which pipeline stage succeeded/failed.

    Query params:
      symbols  : comma-separated (default: first 10 of default universe)
      expiry   : specific expiry (default: nearest)
      threshold: float threshold for threshold_pass flag (default: 2.0)

    Response per symbol:
      {
        "symbol":          "NIFTY",
        "fetch_ok":        true,
        "normalized_ok":   true,
        "rows":            153,
        "spot":            23450.0,
        "max_pain":        23400.0,
        "distance_pct":    0.21,
        "threshold_pass":  false,    ← distance_pct >= threshold
        "market_closed":   false,
        "error":           null,
        "fetch_ms":        312,
      }
    """
    import time as _time
    from app.services.nse_option_chain_service import (
        _URL_INDEX_CHAIN, _URL_EQUITY_CHAIN, INDEX_SYMBOLS,
        NSEFetchError, NSEDataError, NSEMarketClosedError,
    )

    symbols_param = request.args.get("symbols", "")
    expiry        = request.args.get("expiry") or None
    threshold     = float(request.args.get("threshold", 2.0))

    if symbols_param:
        symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    else:
        symbols = DEFAULT_FO_UNIVERSE[:10]

    rows_out = []
    for sym in symbols:
        entry = {
            "symbol":        sym,
            "fetch_ok":      False,
            "normalized_ok": False,
            "rows":          0,
            "spot":          None,
            "max_pain":      None,
            "distance_pct":  None,
            "threshold_pass": False,
            "market_closed": False,
            "error":         None,
            "fetch_ms":      None,
        }
        t0 = _time.monotonic()
        try:
            chain = get_option_chain(sym, expiry=expiry)
            fetch_ms = round((_time.monotonic() - t0) * 1000)
            entry["fetch_ok"]  = True
            entry["fetch_ms"]  = fetch_ms
            entry["rows"]      = len(chain.strikes)
            entry["spot"]      = chain.spot_price

            if chain.strikes:
                entry["normalized_ok"] = True
                try:
                    mp = calculate_max_pain(chain)
                    entry["max_pain"]      = mp.max_pain
                    entry["distance_pct"]  = round(mp.distance_pct, 4)
                    entry["threshold_pass"] = mp.distance_pct >= threshold
                    logger.info(
                        "[LIVE-SCAN] symbol=%s rows=%d spot=%.2f max_pain=%.2f "
                        "distance_pct=%.2f%% threshold_pass=%s fetch_ms=%d",
                        sym, len(chain.strikes), chain.spot_price,
                        mp.max_pain, mp.distance_pct,
                        entry["threshold_pass"], fetch_ms,
                    )
                except MaxPainError as exc:
                    entry["error"] = f"max_pain_calc: {exc}"
            else:
                entry["error"] = "zero strike rows"

        except NSEMarketClosedError as exc:
            entry["fetch_ms"]      = round((_time.monotonic() - t0) * 1000)
            entry["market_closed"] = True
            entry["error"]         = str(exc)
            logger.warning("[LIVE-SCAN] symbol=%s market_closed", sym)

        except (NSEFetchError, NSEDataError) as exc:
            entry["fetch_ms"] = round((_time.monotonic() - t0) * 1000)
            entry["error"]    = str(exc)
            logger.error("[LIVE-SCAN] symbol=%s fetch_error=%s", sym, exc)

        except Exception as exc:
            entry["fetch_ms"] = round((_time.monotonic() - t0) * 1000)
            entry["error"]    = f"unexpected: {exc}"
            logger.error("[LIVE-SCAN] symbol=%s unexpected=%s", sym, exc)

        rows_out.append(entry)

    # Aggregate summary
    fetch_ok_count    = sum(1 for r in rows_out if r["fetch_ok"])
    market_closed_cnt = sum(1 for r in rows_out if r["market_closed"])
    pass_count        = sum(1 for r in rows_out if r["threshold_pass"])

    return jsonify({
        "success": True,
        "data": {
            "symbols": rows_out,
            "summary": {
                "total":           len(rows_out),
                "fetch_ok":        fetch_ok_count,
                "fetch_failed":    len(rows_out) - fetch_ok_count - market_closed_cnt,
                "market_closed":   market_closed_cnt,
                "threshold_pass":  pass_count,
            },
        },
        "meta": {
            "threshold":     threshold,
            "expiry":        expiry or "nearest",
            "generated_at":  datetime.now(timezone.utc).isoformat(),
        },
    }), 200
