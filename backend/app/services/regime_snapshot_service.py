"""
Regime Snapshot Service
=======================
Stores and retrieves RegimeClassification results produced by
regime_classifier.classify_sequence().

This layer handles:
  - Fetching MaxPainSnapshot sequences from the DB.
  - Running the classifier over them.
  - Upserting results into regime_snapshots (keyed on symbol + captured_at).
  - Returning formatted history and summary data for the API layer.

Public API
----------
    classify_and_store(symbol, window, expiry, lookback)
        -> dict  {"classified": int, "stored": int, "window": str}

    get_regime_history(symbol, window, expiry, limit)
        -> list[dict]

    get_regime_distribution(symbol, window)
        -> dict  {regime: count, …}

    get_regime_summary(symbols, window)
        -> dict  {symbol: distribution, …}

    get_regime_transitions(symbol, window, min_confidence)
        -> list[dict]  chronological list of regime changes
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.extensions import db
from app.models.max_pain_snapshot import MaxPainSnapshot
from app.models.regime_snapshot import RegimeSnapshot
from app.services.regime_classifier import (
    RegimeClassification,
    classify_sequence,
    IDEAL_WINDOW,
    _ALL_REGIMES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Window map (shared with replay service)
# ---------------------------------------------------------------------------

_WINDOW_MAP: dict[str, timedelta] = {
    "1h":  timedelta(hours=1),
    "4h":  timedelta(hours=4),
    "1d":  timedelta(days=1),
    "3d":  timedelta(days=3),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _window_delta(window: str) -> timedelta:
    return _WINDOW_MAP.get(window, timedelta(days=7))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_snapshots(
    symbol: str,
    start: datetime,
    end: datetime,
    expiry: Optional[str] = None,
) -> list[MaxPainSnapshot]:
    """Return ascending time-ordered snapshots for the given window."""
    q = (
        db.session.query(MaxPainSnapshot)
        .filter(MaxPainSnapshot.symbol == symbol.upper())
        .filter(MaxPainSnapshot.captured_at >= start)
        .filter(MaxPainSnapshot.captured_at <= end)
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)
    return q.order_by(MaxPainSnapshot.captured_at.asc()).all()


def _upsert_classification(
    clf: RegimeClassification,
    expiry: Optional[str],
    lookback: int,
) -> RegimeSnapshot:
    """
    Insert or update the RegimeSnapshot for (symbol, captured_at).

    We use (symbol, captured_at) as the natural upsert key rather than
    adding a DB-level unique constraint, to keep migrations simpler.
    Existing rows are updated in-place; new rows are added.
    """
    existing = (
        db.session.query(RegimeSnapshot)
        .filter(RegimeSnapshot.symbol == clf.symbol)
        .filter(RegimeSnapshot.captured_at == datetime.fromisoformat(clf.captured_at))
        .first()
    )

    if existing:
        row = existing
    else:
        row = RegimeSnapshot(symbol=clf.symbol)
        db.session.add(row)

    # Resolve snapshot UUID — look up by symbol + captured_at
    snap_uuid = None
    try:
        import uuid as _uuid
        snap_uuid = _uuid.UUID(clf.snapshot_id)
    except (ValueError, AttributeError):
        pass

    row.snapshot_id       = snap_uuid
    row.expiry            = expiry
    row.captured_at       = datetime.fromisoformat(clf.captured_at)
    row.regime            = clf.regime
    row.confidence        = clf.confidence
    row.secondary_regimes = clf.secondary_regimes
    row.scores            = clf.scores
    row.metrics           = clf.metrics
    row.warnings          = clf.warnings
    row.n_window          = clf.n_window
    row.lookback          = lookback

    return row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_and_store(
    symbol:   str,
    window:   str  = "7d",
    expiry:   Optional[str] = None,
    lookback: int  = IDEAL_WINDOW,
) -> dict:
    """
    Fetch recent snapshots, classify the sequence, and store results.

    Args:
        symbol:   NSE symbol.
        window:   Lookback window ("1d" | "7d" | "30d" | …).
        expiry:   Optional expiry filter.
        lookback: Rolling window size passed to classify_sequence().

    Returns:
        Summary dict: {"classified": int, "stored": int, "window": str, …}
    """
    now   = datetime.now(timezone.utc)
    start = now - _window_delta(window)
    end   = now

    snaps = _fetch_snapshots(symbol.upper(), start, end, expiry)
    if not snaps:
        logger.info("classify_and_store: no snapshots for %s window=%s", symbol, window)
        return {"classified": 0, "stored": 0, "window": window, "symbol": symbol}

    classifications = classify_sequence(snaps, lookback=lookback)

    stored = 0
    for clf in classifications:
        try:
            _upsert_classification(clf, expiry, lookback)
            stored += 1
        except Exception as exc:
            logger.warning(
                "Failed to store regime for %s @ %s: %s",
                symbol, clf.captured_at, exc,
            )

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("classify_and_store commit failed for %s: %s", symbol, exc)
        raise

    logger.info(
        "classify_and_store: symbol=%s window=%s classified=%d stored=%d",
        symbol, window, len(classifications), stored,
    )
    return {
        "symbol":     symbol.upper(),
        "window":     window,
        "classified": len(classifications),
        "stored":     stored,
    }


def get_regime_history(
    symbol:         str,
    window:         str           = "7d",
    expiry:         Optional[str] = None,
    limit:          int           = 200,
    min_confidence: float         = 0.0,
) -> list[dict]:
    """
    Return chronological regime classifications for a symbol.

    Args:
        symbol:         NSE symbol.
        window:         Lookback window.
        expiry:         Optional expiry filter.
        limit:          Maximum rows to return.
        min_confidence: Only return rows with confidence >= this value.

    Returns:
        List of dicts (newest-first), each containing the RegimeSnapshot fields.
    """
    now   = datetime.now(timezone.utc)
    start = now - _window_delta(window)

    q = (
        db.session.query(RegimeSnapshot)
        .filter(RegimeSnapshot.symbol == symbol.upper())
        .filter(RegimeSnapshot.captured_at >= start)
        .filter(RegimeSnapshot.confidence  >= min_confidence)
    )
    if expiry:
        q = q.filter(RegimeSnapshot.expiry == expiry)

    rows = (
        q.order_by(RegimeSnapshot.captured_at.desc())
         .limit(limit)
         .all()
    )
    return [r.to_dict() for r in rows]


def get_regime_distribution(
    symbol:         str,
    window:         str   = "30d",
    min_confidence: float = 0.0,
) -> dict:
    """
    Aggregate regime label counts for a symbol.

    Returns a dict mapping each regime label to its count and share,
    plus a warning if the sample is small.

    {
        "symbol":     str,
        "window":     str,
        "total":      int,
        "regimes":    {label: {"count": int, "share": float}},
        "most_common": str,
        "warnings":   [str]
    }
    """
    now   = datetime.now(timezone.utc)
    start = now - _window_delta(window)

    rows: list[RegimeSnapshot] = (
        db.session.query(RegimeSnapshot)
        .filter(RegimeSnapshot.symbol     == symbol.upper())
        .filter(RegimeSnapshot.captured_at >= start)
        .filter(RegimeSnapshot.confidence  >= min_confidence)
        .all()
    )

    total = len(rows)
    counts: dict[str, int] = {r: 0 for r in _ALL_REGIMES}
    counts["unknown"] = 0

    for row in rows:
        label = row.regime if row.regime in counts else "unknown"
        counts[label] += 1

    # Remove zero-count entries
    counts = {k: v for k, v in counts.items() if v > 0}

    most_common = max(counts, key=counts.get) if counts else "unknown"
    warnings    = []
    if total < 30:
        warnings.append(
            f"small_sample: only {total} classified snapshots in window '{window}' "
            f"— distribution may not be representative"
        )

    return {
        "symbol":      symbol.upper(),
        "window":      window,
        "total":       total,
        "regimes":     {
            k: {"count": v, "share": round(v / total, 4) if total else 0.0}
            for k, v in sorted(counts.items(), key=lambda x: -x[1])
        },
        "most_common": most_common,
        "warnings":    warnings,
    }


def get_regime_summary(
    symbols:        Optional[list[str]] = None,
    window:         str                 = "30d",
    min_confidence: float               = 0.0,
) -> dict:
    """
    Cross-symbol regime distribution summary.

    Args:
        symbols:        List of NSE symbols. Defaults to top-10 FO universe.
        window:         Lookback window.
        min_confidence: Minimum confidence threshold.

    Returns:
        {
            "window":          str,
            "symbols_queried": int,
            "per_symbol":      {symbol: distribution_dict},
            "aggregate":       {regime: {count, share}},
            "generated_at":    str (ISO),
        }
    """
    from app.services.max_pain_scanner_service import DEFAULT_FO_UNIVERSE

    target = symbols or DEFAULT_FO_UNIVERSE[:10]

    per_symbol: dict[str, dict] = {}
    aggregate:  dict[str, int]  = {}

    for sym in target:
        try:
            dist = get_regime_distribution(sym, window, min_confidence)
            per_symbol[sym] = dist
            for regime, info in dist.get("regimes", {}).items():
                aggregate[regime] = aggregate.get(regime, 0) + info["count"]
        except Exception as exc:
            logger.warning("Regime summary error for %s: %s", sym, exc)
            per_symbol[sym] = {"error": str(exc)}

    agg_total = sum(aggregate.values())
    agg_shares = {
        k: {"count": v, "share": round(v / agg_total, 4) if agg_total else 0.0}
        for k, v in sorted(aggregate.items(), key=lambda x: -x[1])
    }

    return {
        "window":          window,
        "symbols_queried": len(target),
        "per_symbol":      per_symbol,
        "aggregate":       agg_shares,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
    }


def get_regime_transitions(
    symbol:         str,
    window:         str   = "7d",
    min_confidence: float = 0.30,
) -> list[dict]:
    """
    Return the chronological sequence of regime *changes* for a symbol.

    Only rows where the regime differs from the immediately prior row
    (above min_confidence) are returned. Useful for spotting regime shifts.

    Returns:
        [
          {
            "from_regime": str,
            "to_regime":   str,
            "at":          str (ISO datetime),
            "confidence":  float,
            "duration_bars": int,  # bars in the previous regime
          }, …
        ]
    """
    now   = datetime.now(timezone.utc)
    start = now - _window_delta(window)

    rows: list[RegimeSnapshot] = (
        db.session.query(RegimeSnapshot)
        .filter(RegimeSnapshot.symbol     == symbol.upper())
        .filter(RegimeSnapshot.captured_at >= start)
        .filter(RegimeSnapshot.confidence  >= min_confidence)
        .order_by(RegimeSnapshot.captured_at.asc())
        .all()
    )

    if not rows:
        return []

    transitions: list[dict] = []
    prev_regime  = rows[0].regime
    streak_start = 0

    for i, row in enumerate(rows[1:], start=1):
        if row.regime != prev_regime:
            transitions.append({
                "from_regime":   prev_regime,
                "to_regime":     row.regime,
                "at":            row.captured_at.isoformat(),
                "confidence":    row.confidence,
                "duration_bars": i - streak_start,
            })
            prev_regime  = row.regime
            streak_start = i

    return transitions
