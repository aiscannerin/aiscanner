"""
Max Pain Validation API Routes
================================
Replay and statistical validation of historical max pain signals.

Endpoints
---------
GET /api/max-pain/validation/summary
GET /api/max-pain/validation/symbol/<symbol>
GET /api/max-pain/validation/replay/<symbol>
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from typing import Optional

from app.services.max_pain_validation_service import (
    compute_symbol_validation,
    compute_summary_validation,
)
from app.services.max_pain_replay_service import load_replay

logger = logging.getLogger(__name__)

validation_bp = Blueprint(
    "max_pain_validation", __name__, url_prefix="/api/max-pain/validation"
)

VALID_WINDOWS = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}

_VALID_EXPIRY_PROXIMITY = {"near", "far"}
_VALID_VOL_STATE        = {"high_iv", "low_iv", "normal_iv"}


def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _err(message: str, status: int = 500, code: str = "ERROR"):
    return jsonify({"success": False, "error": message, "code": code}), status


def _window(default: str = "30d") -> str:
    w = request.args.get("window", default)
    return w if w in VALID_WINDOWS else default


def _min_distance() -> float:
    try:
        return max(0.0, float(request.args.get("min_distance_pct", 0.0)))
    except (ValueError, TypeError):
        return 0.0


def _regime_filter() -> Optional[str]:
    return request.args.get("regime_filter") or None


def _expiry_proximity() -> Optional[str]:
    v = request.args.get("expiry_proximity")
    return v if v in _VALID_EXPIRY_PROXIMITY else None


def _vol_state() -> Optional[str]:
    v = request.args.get("vol_state")
    return v if v in _VALID_VOL_STATE else None


# ---------------------------------------------------------------------------
# GET /api/max-pain/validation/summary
# ---------------------------------------------------------------------------

@validation_bp.route("/summary", methods=["GET"])
@jwt_required()
def summary():
    """
    Cross-symbol aggregate validation report.

    Pools replay signals from multiple symbols and computes aggregate
    hit rates, expectancy, and regime breakdowns.

    Query params:
      window          : 1h | 4h | 1d | 3d | 7d | 30d | 90d  (default: 30d)
      symbols         : comma-separated (default: top 10 FO universe)
      min_distance_pct: float — minimum signal distance threshold (default: 2.0)

    Response:
      {
        "window", "symbols_analysed", "total_signals",
        "per_symbol": { symbol: count },
        "horizons": {
          "15m": { hit_rate, expectancy_pct, confidence_score, … },
          "1h":  { … }, "4h": { … }, "1d": { … }
        },
        "regimes": {
          "expiry_week": { count, horizons: { … } },
          "high_iv":     { … }, …
        },
        "generated_at"
      }
    """
    try:
        symbols_param = request.args.get("symbols", "")
        symbols = (
            [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
            or None
        )
        min_dist = max(0.0, float(request.args.get("min_distance_pct", 2.0)))

        result = compute_summary_validation(
            symbols=symbols,
            window=_window(),
            min_distance_pct=min_dist,
        )
        return _ok(result)

    except Exception as exc:
        logger.error("Validation summary error: %s", exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/validation/symbol/<symbol>
# ---------------------------------------------------------------------------

@validation_bp.route("/symbol/<string:symbol>", methods=["GET"])
@jwt_required()
def symbol_validation(symbol: str):
    """
    Full statistical validation report for one symbol.

    Query params:
      window           : lookback window (default: 30d)
      expiry           : pin to specific expiry (default: all)
      min_distance_pct : minimum signal distance % (default: 0.0)
      regime_filter    : filter signals by regime label (e.g. expiry_week,
                         high_iv, expiry_pinning, pcr_aligned, …)
      expiry_proximity : "near" (DTE ≤ 5) | "far" (DTE > 5)
      vol_state        : "high_iv" | "low_iv" | "normal_iv"

    Response:
      {
        "symbol", "window", "expiry", "total_signals", "min_distance_pct",
        "signal_stats": {
          "count", "bullish_signals", "bearish_signals",
          "distance_pct": { mean, min, max, stdev, p25, p75 },
          "pcr": { mean, min, max },
          "avg_iv": { mean, min, max },
          "days_to_expiry": { mean, expiry_week_pct }
        },
        "horizons": {
          "15m": {
            "hit_rate", "hit_count", "miss_count", "available",
            "avg_convergent_pct", "avg_divergent_pct",
            "expectancy_pct", "p_value", "confidence_score",
            "is_significant", "warnings": [...]
          },
          "1h": { … }, "4h": { … }, "1d": { … }
        },
        "regimes": {
          "15m": {
            "expiry_week": { count, stats: { … } },
            "high_iv":     { … }, …
          },
          …
        },
        "oi_wall": {
          "ce_migration_rate", "pe_migration_rate",
          "wall_compression_count", "wall_expansion_count"
        },
        "generated_at"
      }
    """
    try:
        sym    = symbol.upper().strip()
        expiry = request.args.get("expiry") or None

        report = compute_symbol_validation(
            symbol           = sym,
            expiry           = expiry,
            window           = _window(),
            min_distance_pct = _min_distance(),
            regime_filter    = _regime_filter(),
            expiry_proximity = _expiry_proximity(),
            vol_state        = _vol_state(),
        )
        return _ok(report.to_dict())

    except Exception as exc:
        logger.error("Validation error for %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/validation/replay/<symbol>
# ---------------------------------------------------------------------------

@validation_bp.route("/replay/<string:symbol>", methods=["GET"])
@jwt_required()
def replay(symbol: str):
    """
    Chronological replay data: each signal point with attached forward outcomes.

    Use this endpoint to inspect individual signal instances and their
    actual forward returns — the raw data behind the statistics.

    Query params:
      window          : lookback window (default: 7d)
      expiry          : pin to specific expiry
      min_distance_pct: filter minimum distance % (default: 0.0)
      limit           : max points to return (default: 200, max: 500)
      offset          : skip first N points for pagination (default: 0)

    Response:
      {
        "symbol", "window", "expiry",
        "total":  int  (total matching points before limit/offset),
        "limit":  int,
        "offset": int,
        "points": [
          {
            "snapshot_id", "captured_at", "spot_price", "max_pain",
            "distance_pct", "direction", "pcr", "avg_iv",
            "days_to_expiry", "original_distance",
            "wall_state": { ce_migrated, pe_migrated, ce_direction, … },
            "outcomes": {
              "15m": { hit, convergent_pct, raw_return_pct, future_spot, … },
              "1h":  { … }, "4h": { … }, "1d": { … }
            }
          }, …
        ]
      }

    Note: "hit" = spot moved closer to the signal's max_pain level,
    not simply that it moved in the expected direction. convergent_pct > 0
    means convergence; < 0 means divergence.
    """
    try:
        sym      = symbol.upper().strip()
        expiry   = request.args.get("expiry") or None
        min_dist = _min_distance()
        limit    = max(1, min(int(request.args.get("limit",  200)), 500))
        offset   = max(0,     int(request.args.get("offset",   0)))

        points = load_replay(
            symbol=sym,
            expiry=expiry,
            window=_window("7d"),
            min_distance_pct=min_dist,
        )
        total      = len(points)
        page       = points[offset: offset + limit]

        return _ok({
            "symbol":  sym,
            "window":  _window("7d"),
            "expiry":  expiry,
            "total":   total,
            "limit":   limit,
            "offset":  offset,
            "points":  [p.to_dict() for p in page],
        })

    except Exception as exc:
        logger.error("Replay error for %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))
