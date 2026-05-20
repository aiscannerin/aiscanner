"""
Market Regime API Routes
=========================
Endpoints for classifying and querying market regime history.

Endpoints
---------
GET  /api/max-pain/regime/<symbol>
     Regime classification history for one symbol.

GET  /api/max-pain/regime/<symbol>/distribution
     Regime label distribution (count + share) for one symbol.

GET  /api/max-pain/regime/<symbol>/transitions
     Chronological list of regime change events.

POST /api/max-pain/regime/<symbol>/classify
     Trigger (re)classification for a symbol and store results.

GET  /api/max-pain/regime-summary
     Cross-symbol aggregate regime distribution.
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.regime_snapshot_service import (
    classify_and_store,
    get_regime_history,
    get_regime_distribution,
    get_regime_summary,
    get_regime_transitions,
    IDEAL_WINDOW,
)

logger = logging.getLogger(__name__)

regime_bp = Blueprint(
    "max_pain_regime", __name__, url_prefix="/api/max-pain"
)

VALID_WINDOWS = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _err(message: str, status: int = 500, code: str = "ERROR"):
    return jsonify({"success": False, "error": message, "code": code}), status


def _window(default: str = "7d") -> str:
    w = request.args.get("window", default)
    return w if w in VALID_WINDOWS else default


def _min_conf() -> float:
    try:
        return max(0.0, min(1.0, float(request.args.get("min_confidence", 0.0))))
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# GET /api/max-pain/regime/<symbol>
# ---------------------------------------------------------------------------

@regime_bp.route("/regime/<string:symbol>", methods=["GET"])
@jwt_required()
def regime_history(symbol: str):
    """
    Chronological regime classification history for one symbol.

    Query params:
      window         : lookback window (default: 7d)
      expiry         : optional expiry filter
      limit          : max rows (default: 200, max: 500)
      min_confidence : only rows with confidence >= this (default: 0.0)

    Response:
      {
        "symbol", "window", "expiry",
        "total": int,
        "history": [
          {
            "snapshot_id", "captured_at", "regime", "confidence",
            "secondary_regimes", "scores", "metrics", "warnings", "n_window"
          }, …
        ]
      }
    """
    try:
        sym    = symbol.upper().strip()
        expiry = request.args.get("expiry") or None
        limit  = max(1, min(int(request.args.get("limit", 200)), 500))

        history = get_regime_history(
            symbol         = sym,
            window         = _window(),
            expiry         = expiry,
            limit          = limit,
            min_confidence = _min_conf(),
        )

        return _ok({
            "symbol":  sym,
            "window":  _window(),
            "expiry":  expiry,
            "total":   len(history),
            "history": history,
        })

    except Exception as exc:
        logger.error("Regime history error for %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/regime/<symbol>/distribution
# ---------------------------------------------------------------------------

@regime_bp.route("/regime/<string:symbol>/distribution", methods=["GET"])
@jwt_required()
def regime_distribution(symbol: str):
    """
    Regime label distribution (count + share) for one symbol.

    Query params:
      window         : lookback window (default: 30d)
      min_confidence : only rows with confidence >= this (default: 0.0)

    Response:
      {
        "symbol", "window", "total",
        "regimes": { label: { "count": int, "share": float } },
        "most_common": str,
        "warnings": [str]
      }
    """
    try:
        sym = symbol.upper().strip()
        dist = get_regime_distribution(
            symbol         = sym,
            window         = _window("30d"),
            min_confidence = _min_conf(),
        )
        return _ok(dist)

    except Exception as exc:
        logger.error("Regime distribution error for %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/regime/<symbol>/transitions
# ---------------------------------------------------------------------------

@regime_bp.route("/regime/<string:symbol>/transitions", methods=["GET"])
@jwt_required()
def regime_transitions(symbol: str):
    """
    Chronological list of regime *change* events for one symbol.

    Only transitions above min_confidence are included.

    Query params:
      window         : lookback window (default: 7d)
      min_confidence : minimum confidence for a row to be considered (default: 0.30)

    Response:
      {
        "symbol", "window",
        "transitions": [
          {
            "from_regime": str,
            "to_regime":   str,
            "at":          str (ISO),
            "confidence":  float,
            "duration_bars": int
          }, …
        ]
      }
    """
    try:
        sym  = symbol.upper().strip()
        conf = max(0.0, min(1.0, float(request.args.get("min_confidence", 0.30))))

        transitions = get_regime_transitions(
            symbol         = sym,
            window         = _window(),
            min_confidence = conf,
        )

        return _ok({
            "symbol":      sym,
            "window":      _window(),
            "transitions": transitions,
        })

    except Exception as exc:
        logger.error("Regime transitions error for %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# POST /api/max-pain/regime/<symbol>/classify
# ---------------------------------------------------------------------------

@regime_bp.route("/regime/<string:symbol>/classify", methods=["POST"])
@jwt_required()
def trigger_classification(symbol: str):
    """
    Trigger (re)classification of stored snapshots for a symbol and persist
    the results to regime_snapshots.

    Request body (JSON, all optional):
      {
        "window":   "7d",
        "expiry":   null,
        "lookback": 15
      }

    Response:
      {
        "symbol":     str,
        "window":     str,
        "classified": int,
        "stored":     int
      }
    """
    try:
        body     = request.get_json(silent=True) or {}
        sym      = symbol.upper().strip()
        window   = body.get("window",   "7d")
        if window not in VALID_WINDOWS:
            window = "7d"
        expiry   = body.get("expiry")   or None
        lookback = int(body.get("lookback", IDEAL_WINDOW))
        lookback = max(3, min(lookback, 50))

        result = classify_and_store(
            symbol   = sym,
            window   = window,
            expiry   = expiry,
            lookback = lookback,
        )
        return _ok(result)

    except Exception as exc:
        logger.error("Regime classify error for %s: %s", symbol, exc, exc_info=True)
        return _err(str(exc))


# ---------------------------------------------------------------------------
# GET /api/max-pain/regime-summary
# ---------------------------------------------------------------------------

@regime_bp.route("/regime-summary", methods=["GET"])
@jwt_required()
def regime_summary():
    """
    Cross-symbol aggregate regime distribution.

    Query params:
      window         : lookback window (default: 30d)
      symbols        : comma-separated NSE symbols (default: top-10 FO universe)
      min_confidence : minimum confidence threshold (default: 0.0)

    Response:
      {
        "window":          str,
        "symbols_queried": int,
        "per_symbol":      { symbol: distribution },
        "aggregate":       { regime: { count, share } },
        "generated_at":    str (ISO)
      }
    """
    try:
        symbols_param = request.args.get("symbols", "")
        symbols = (
            [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
            or None
        )

        result = get_regime_summary(
            symbols        = symbols,
            window         = _window("30d"),
            min_confidence = _min_conf(),
        )
        return _ok(result)

    except Exception as exc:
        logger.error("Regime summary error: %s", exc, exc_info=True)
        return _err(str(exc))
