"""
NSE Option Chain API Routes
============================
All endpoints return a consistent envelope:
  { "success": true,  "data": { … } }
  { "success": false, "error": "…", "code": "…" }

Rate-limiting is inherited from Flask-Limiter (200 req/hr default).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.services.nse_option_chain_service import (
    NSEBlockedError,
    NSEDataError,
    NSEFetchError,
    NSERateLimitError,
    _get_service,
    get_atm_strike,
    get_expiries,
    get_nearest_expiry,
    get_option_chain,
)
from app.services.option_chain_monitor import monitor

logger = logging.getLogger(__name__)

options_bp = Blueprint("options", __name__, url_prefix="/api/options")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data: dict | list, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _err(message: str, code: str = "FETCH_ERROR", status: int = 500):
    return jsonify({"success": False, "error": message, "code": code}), status


def _map_exception(exc: Exception):
    """Map service exceptions to HTTP error responses."""
    if isinstance(exc, NSERateLimitError):
        logger.warning("NSE rate-limit hit: %s", exc)
        return _err(str(exc), code="RATE_LIMITED", status=429)
    if isinstance(exc, NSEBlockedError):
        logger.error("NSE session blocked: %s", exc)
        return _err(str(exc), code="NSE_BLOCKED", status=503)
    if isinstance(exc, NSEDataError):
        logger.error("NSE data error: %s", exc)
        return _err(str(exc), code="DATA_ERROR", status=502)
    if isinstance(exc, NSEFetchError):
        logger.error("NSE fetch error: %s", exc)
        return _err(str(exc), code="FETCH_ERROR", status=503)
    logger.exception("Unexpected error in options API")
    return _err("Internal server error", code="INTERNAL_ERROR", status=500)


# ---------------------------------------------------------------------------
# GET /api/options/<symbol>
# ---------------------------------------------------------------------------

@options_bp.route("/<string:symbol>", methods=["GET"])
@jwt_required()
def option_chain(symbol: str):
    """
    Fetch the full option chain for a symbol.

    Query params:
      expiry  — pin to a specific NSE expiry date string
                (e.g. "25-Jul-2024"). Omit for nearest expiry.
      refresh — set to "1" or "true" to bypass cache

    Response includes:
      symbol, expiry, all_expiries, spot_price, timestamp,
      total_ce_oi, total_pe_oi, total_ce_volume, total_pe_volume,
      pcr, atm_strike, atm_ce_iv, atm_pe_iv, fetched_from_cache,
      strikes[{ strike, ce:{oi, oi_change, volume, iv, ltp, bid, ask}, pe:{…} }]

    Example:
      GET /api/options/NIFTY
      GET /api/options/NIFTY?expiry=25-Jul-2024
      GET /api/options/RELIANCE?refresh=1
    """
    expiry  = request.args.get("expiry") or None
    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")

    try:
        svc    = _get_service()
        result = svc.get_option_chain(symbol, expiry=expiry, force_refresh=refresh)
        return _ok(result.to_dict())
    except Exception as exc:
        return _map_exception(exc)


# ---------------------------------------------------------------------------
# GET /api/options/<symbol>/expiries
# ---------------------------------------------------------------------------

@options_bp.route("/<string:symbol>/expiries", methods=["GET"])
@jwt_required()
def expiries(symbol: str):
    """
    Return the list of all available expiry dates for symbol.

    Response:
      { "symbol": "NIFTY", "expiries": ["25-Jul-2024", "01-Aug-2024", …] }
    """
    try:
        exp_list = get_expiries(symbol)
        return _ok({"symbol": symbol.upper(), "expiries": exp_list})
    except Exception as exc:
        return _map_exception(exc)


# ---------------------------------------------------------------------------
# GET /api/options/<symbol>/nearest-expiry
# ---------------------------------------------------------------------------

@options_bp.route("/<string:symbol>/nearest-expiry", methods=["GET"])
@jwt_required()
def nearest_expiry(symbol: str):
    """
    Return only the nearest (current-week) expiry for symbol.

    Response:
      { "symbol": "NIFTY", "nearest_expiry": "25-Jul-2024" }
    """
    try:
        ne = get_nearest_expiry(symbol)
        return _ok({"symbol": symbol.upper(), "nearest_expiry": ne})
    except Exception as exc:
        return _map_exception(exc)


# ---------------------------------------------------------------------------
# GET /api/options/<symbol>/atm
# ---------------------------------------------------------------------------

@options_bp.route("/<string:symbol>/atm", methods=["GET"])
@jwt_required()
def atm_strike(symbol: str):
    """
    Return ATM strike and surrounding OI data for symbol.

    Query params:
      expiry  — pin to a specific expiry (default: nearest)
      depth   — number of strikes above/below ATM to include (default: 5)

    Response:
      {
        "symbol": "NIFTY",
        "spot_price": 22450.0,
        "atm_strike": 22450.0,
        "expiry": "25-Jul-2024",
        "atm_ce_iv": 12.5,
        "atm_pe_iv": 13.1,
        "nearby_strikes": [ { strike, ce, pe }, … ]   ← ATM ± depth
      }
    """
    expiry = request.args.get("expiry") or None
    depth  = max(1, min(int(request.args.get("depth", 5)), 20))

    try:
        result = get_option_chain(symbol, expiry=expiry)
        atm    = result.atm_strike
        nearby = [
            s.to_dict() for s in result.strikes
            if abs(result.strikes.index(s) - _atm_index(result.strikes, atm)) <= depth
        ]
        return _ok({
            "symbol":         result.symbol,
            "spot_price":     result.spot_price,
            "atm_strike":     atm,
            "expiry":         result.expiry,
            "atm_ce_iv":      result.atm_ce_iv,
            "atm_pe_iv":      result.atm_pe_iv,
            "nearby_strikes": nearby,
        })
    except Exception as exc:
        return _map_exception(exc)


def _atm_index(strikes, atm_strike: float) -> int:
    """Find the list index of the ATM strike."""
    return min(range(len(strikes)), key=lambda i: abs(strikes[i].strike - atm_strike))


# ---------------------------------------------------------------------------
# GET /api/options/market-status
# ---------------------------------------------------------------------------

@options_bp.route("/market-status", methods=["GET"])
@jwt_required()
def market_status():
    """
    Return whether NSE is currently in trading hours.

    Response:
      { "is_open": true, "note": "Mon–Fri 09:15–15:30 IST" }
    """
    svc = _get_service()
    return _ok({
        "is_open": svc.is_market_open(),
        "note":    "NSE trades Mon–Fri 09:15–15:30 IST",
    })


# ---------------------------------------------------------------------------
# GET /api/options/cache-stats
# ---------------------------------------------------------------------------

@options_bp.route("/cache-stats", methods=["GET"])
@jwt_required()
def cache_stats():
    """
    Return in-memory cache statistics.

    Response:
      { "entries": 12, "hits": 340, "misses": 45, "hit_rate": 0.883, "ttl_secs": 20 }
    """
    svc = _get_service()
    return _ok(svc.cache_stats())


# ---------------------------------------------------------------------------
# POST /api/options/<symbol>/invalidate
# ---------------------------------------------------------------------------

@options_bp.route("/<string:symbol>/invalidate", methods=["POST"])
@jwt_required()
def invalidate_cache(symbol: str):
    """
    Evict cached entries for symbol (all expiries).

    Useful when you know the data has changed and want to force a fresh fetch.
    """
    svc   = _get_service()
    count = svc.invalidate_cache(symbol)
    return _ok({"symbol": symbol.upper(), "evicted": count})


# ---------------------------------------------------------------------------
# GET /api/options/health
# ---------------------------------------------------------------------------

@options_bp.route("/health", methods=["GET"])
@jwt_required()
def health():
    """
    Service health and monitoring metrics.

    Response:
      {
        "status": "healthy|degraded|unhealthy",
        "market_open": bool,
        "last_successful_fetch": "ISO8601" | null,
        "session_age_secs": int | null,
        "cache": { "entries": int, "hits": int, "misses": int, "hit_rate": float, "ttl_secs": int },
        "fetcher": { "success_rate": float, "total_fetches": int,
                     "avg_latency_ms": float, "p95_latency_ms": float,
                     "retry_count": int },
        "validation": { "pass_rate": float, "total_validations": int,
                        "warnings_rate": float }
      }

    Status rules:
      healthy   — success_rate >= 0.95  AND  validation pass_rate >= 0.95
      degraded  — success_rate >= 0.70  OR   validation pass_rate >= 0.80
      unhealthy — otherwise
    """
    svc = _get_service()
    snap = monitor.full_snapshot()

    fetcher_stats    = snap["fetcher"]
    validation_stats = snap["validation"]
    session_stats    = snap["session"]
    cache_stats_live = svc.cache_stats()      # uses TTL cache (has "entries" key)

    success_rate  = fetcher_stats.get("success_rate")
    pass_rate     = validation_stats.get("pass_rate")

    # Determine health status
    if success_rate is None:
        status = "unknown"
    elif (
        (success_rate is None or success_rate >= 0.95)
        and (pass_rate is None or pass_rate >= 0.95)
    ):
        status = "healthy"
    elif (
        success_rate >= 0.70
        and (pass_rate is None or pass_rate >= 0.80)
    ):
        status = "degraded"
    else:
        status = "unhealthy"

    return _ok({
        "status":                status,
        "market_open":           svc.is_market_open(),
        "last_successful_fetch": fetcher_stats.get("last_success_ts"),
        "last_failure":          fetcher_stats.get("last_failure_ts"),
        "session_age_secs":      session_stats.get("session_age_secs"),
        "cache": {
            "entries":  cache_stats_live.get("entries", 0),
            "hits":     cache_stats_live.get("hits", 0),
            "misses":   cache_stats_live.get("misses", 0),
            "hit_rate": cache_stats_live.get("hit_rate", 0.0),
            "ttl_secs": cache_stats_live.get("ttl_secs", 0),
        },
        "fetcher": {
            "success_rate":    success_rate,
            "total_fetches":   fetcher_stats.get("total_fetches", 0),
            "fetch_failure":   fetcher_stats.get("fetch_failure", 0),
            "avg_latency_ms":  fetcher_stats.get("avg_latency_ms"),
            "p95_latency_ms":  fetcher_stats.get("p95_latency_ms"),
            "retry_count":     fetcher_stats.get("retry_count", 0),
        },
        "validation": {
            "pass_rate":          pass_rate,
            "total_validations":  validation_stats.get("total_validations", 0),
            "fail_count":         validation_stats.get("fail_count", 0),
            "warnings_rate":      validation_stats.get("warnings_rate"),
        },
    })
