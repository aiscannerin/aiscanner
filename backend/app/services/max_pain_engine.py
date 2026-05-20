"""
Max Pain Calculation Engine
============================
Computes the max pain strike and related OI metrics from a normalised
OptionChainResult.

Mathematical definition
-----------------------
For every candidate strike S across the chain:

    CE_payout(S) = Σ  max(0, S − K) × CE_OI[K]   for all K < S
    PE_payout(S) = Σ  max(0, K − S) × PE_OI[K]   for all K > S
    total_pain(S) = CE_payout(S) + PE_payout(S)

The strike S* with the minimum total_pain is the max pain strike.

Public API
----------
    calculate_max_pain(chain)   -> MaxPainResult
    calculate_pain_curve(chain) -> list[PainPoint]
    get_oi_walls(chain)         -> OIWalls
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PainPoint:
    """Pain values for a single candidate strike."""
    strike:     float
    ce_payout:  float
    pe_payout:  float
    total_pain: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OIWall:
    """The single strongest OI concentration on one side of the market."""
    strike:    float
    oi:        int
    side:      str   # "CE" or "PE"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OIWalls:
    ce_wall: OIWall
    pe_wall: OIWall

    def to_dict(self) -> dict:
        return {"ce_wall": self.ce_wall.to_dict(), "pe_wall": self.pe_wall.to_dict()}


@dataclass
class MaxPainResult:
    """
    Complete max pain calculation result for one option chain snapshot.

    Fields
    ------
    max_pain          : strike with minimum total option-writer payout
    spot_price        : underlying spot price at fetch time
    distance_from_spot: absolute |spot - max_pain|
    distance_pct      : distance_from_spot / spot_price × 100 (%)
    total_ce_oi       : sum of CE OI across all strikes
    total_pe_oi       : sum of PE OI across all strikes
    pcr               : total_pe_oi / total_ce_oi (0.0 if CE OI is zero)
    pain_curve        : PainPoint list ordered by strike ascending
    top_pain_strikes  : top 5 lowest-pain candidate strikes (incl. max pain)
    ce_wall           : strike with highest CE OI above spot (resistance)
    pe_wall           : strike with highest PE OI below spot (support)
    """
    max_pain:           float
    spot_price:         float
    distance_from_spot: float
    distance_pct:       float
    total_ce_oi:        int
    total_pe_oi:        int
    pcr:                float
    pain_curve:         list[PainPoint]   = field(default_factory=list)
    top_pain_strikes:   list[PainPoint]   = field(default_factory=list)
    ce_wall:            Optional[OIWall]  = None
    pe_wall:            Optional[OIWall]  = None

    def to_dict(self) -> dict:
        return {
            "max_pain":           self.max_pain,
            "spot_price":         self.spot_price,
            "distance_from_spot": self.distance_from_spot,
            "distance_pct":       self.distance_pct,
            "total_ce_oi":        self.total_ce_oi,
            "total_pe_oi":        self.total_pe_oi,
            "pcr":                self.pcr,
            "pain_curve":         [p.to_dict() for p in self.pain_curve],
            "top_pain_strikes":   [p.to_dict() for p in self.top_pain_strikes],
            "ce_wall":            self.ce_wall.to_dict() if self.ce_wall else None,
            "pe_wall":            self.pe_wall.to_dict() if self.pe_wall else None,
        }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

class MaxPainError(ValueError):
    """Raised when the chain cannot support a max pain calculation."""


def _require_chain(chain) -> None:
    """Raise MaxPainError if chain has no usable strikes."""
    strikes = _get_strikes(chain)
    if not strikes:
        raise MaxPainError("Option chain has no strikes — cannot compute max pain.")
    if len(strikes) < 2:
        raise MaxPainError(
            f"Option chain has only {len(strikes)} strike — need at least 2."
        )


def _get_strikes(chain) -> list:
    """
    Normalise chain to a list of strike-like objects.
    Accepts OptionChainResult (dataclass) or a plain dict.
    """
    if hasattr(chain, "strikes"):
        return chain.strikes or []
    if isinstance(chain, dict):
        return chain.get("strikes") or []
    return []


def _get_spot(chain) -> float:
    """Extract spot price from chain (dataclass or dict)."""
    if hasattr(chain, "spot_price"):
        return float(chain.spot_price or 0)
    if isinstance(chain, dict):
        return float(chain.get("spot_price") or 0)
    return 0.0


def _safe_oi(leg, attr: str = "oi") -> int:
    """Read OI from a StrikeRow leg (dataclass) or a plain dict, returning 0 on failure."""
    try:
        if hasattr(leg, attr):
            v = getattr(leg, attr)
        elif isinstance(leg, dict):
            v = leg.get(attr, 0)
        else:
            return 0
        result = int(v) if v is not None else 0
        return max(0, result)   # OI must be non-negative
    except (TypeError, ValueError):
        return 0


def _strike_val(row) -> float:
    """Extract float strike from StrikeRow (dataclass) or dict."""
    try:
        if hasattr(row, "strike"):
            return float(row.strike)
        if isinstance(row, dict):
            return float(row.get("strike", 0))
    except (TypeError, ValueError):
        pass
    return 0.0


def _ce_oi(row) -> int:
    if hasattr(row, "ce"):
        return _safe_oi(row.ce, "oi")
    if isinstance(row, dict):
        return max(0, int(row.get("ce_oi", 0) or 0))
    return 0


def _pe_oi(row) -> int:
    if hasattr(row, "pe"):
        return _safe_oi(row.pe, "oi")
    if isinstance(row, dict):
        return max(0, int(row.get("pe_oi", 0) or 0))
    return 0


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def calculate_pain_curve(chain) -> list[PainPoint]:
    """
    Return the full pain curve: one PainPoint per valid strike, ordered ascending.

    Skips strikes with a zero or negative strike value (malformed rows).
    Treats missing or None OI as zero (defensive).
    """
    strikes = _get_strikes(chain)
    if not strikes:
        return []

    # Build arrays — skip malformed rows
    valid: list[tuple[float, int, int]] = []   # (strike, ce_oi, pe_oi)
    for row in strikes:
        s = _strike_val(row)
        if s <= 0:
            logger.debug("Skipping malformed strike row: %r", row)
            continue
        valid.append((s, _ce_oi(row), _pe_oi(row)))

    if not valid:
        return []

    valid.sort(key=lambda t: t[0])

    # For each candidate strike, compute payout
    points: list[PainPoint] = []
    for idx, (candidate, _, _) in enumerate(valid):
        ce_payout = sum(
            max(0.0, candidate - s) * c_oi
            for (s, c_oi, _) in valid
            if s < candidate
        )
        pe_payout = sum(
            max(0.0, s - candidate) * p_oi
            for (s, _, p_oi) in valid
            if s > candidate
        )
        points.append(PainPoint(
            strike=candidate,
            ce_payout=ce_payout,
            pe_payout=pe_payout,
            total_pain=ce_payout + pe_payout,
        ))

    return points


def get_oi_walls(chain) -> OIWalls:
    """
    Return the strongest CE wall (highest CE OI above spot) and
    PE wall (highest PE OI below spot).

    Falls back to highest OI across the full chain when no strikes
    exist on a given side of spot.
    """
    strikes = _get_strikes(chain)
    spot    = _get_spot(chain)

    valid = [(float(_strike_val(r)), _ce_oi(r), _pe_oi(r)) for r in strikes]
    valid = [(s, c, p) for (s, c, p) in valid if s > 0]

    above = [(s, c, p) for (s, c, p) in valid if s > spot]
    below = [(s, c, p) for (s, c, p) in valid if s < spot]

    # CE wall — resistance above spot
    if above:
        s, c, _ = max(above, key=lambda t: t[1])
        ce_wall = OIWall(strike=s, oi=c, side="CE")
    elif valid:
        s, c, _ = max(valid, key=lambda t: t[1])
        ce_wall = OIWall(strike=s, oi=c, side="CE")
    else:
        ce_wall = OIWall(strike=0.0, oi=0, side="CE")

    # PE wall — support below spot
    if below:
        s, _, p = max(below, key=lambda t: t[2])
        pe_wall = OIWall(strike=s, oi=p, side="PE")
    elif valid:
        s, _, p = max(valid, key=lambda t: t[2])
        pe_wall = OIWall(strike=s, oi=p, side="PE")
    else:
        pe_wall = OIWall(strike=0.0, oi=0, side="PE")

    return OIWalls(ce_wall=ce_wall, pe_wall=pe_wall)


def calculate_max_pain(chain) -> MaxPainResult:
    """
    Main entry point.  Accepts an OptionChainResult dataclass or an equivalent dict.

    Raises
    ------
    MaxPainError  if the chain is empty or has fewer than 2 valid strikes.
    """
    _require_chain(chain)

    spot       = _get_spot(chain)
    pain_curve = calculate_pain_curve(chain)

    if not pain_curve:
        raise MaxPainError("Pain curve is empty after filtering malformed strikes.")

    # Max pain = strike with minimum total pain
    min_point  = min(pain_curve, key=lambda p: p.total_pain)
    max_pain   = min_point.strike

    # Top 5 lowest-pain strikes (sorted by total_pain ascending)
    top5 = sorted(pain_curve, key=lambda p: p.total_pain)[:5]

    # OI totals
    strikes = _get_strikes(chain)
    total_ce = sum(_ce_oi(r) for r in strikes)
    total_pe = sum(_pe_oi(r) for r in strikes)

    # PCR — guarded against zero CE OI
    pcr = round(total_pe / total_ce, 4) if total_ce > 0 else 0.0

    # Distance metrics — guarded against zero spot
    if spot > 0:
        dist_abs = abs(spot - max_pain)
        dist_pct = round(dist_abs / spot * 100, 4)
    else:
        dist_abs = 0.0
        dist_pct = 0.0
        logger.warning("Spot price is zero — distance metrics will be zero.")

    # OI walls
    walls = get_oi_walls(chain)

    result = MaxPainResult(
        max_pain           = max_pain,
        spot_price         = spot,
        distance_from_spot = round(dist_abs, 2),
        distance_pct       = dist_pct,
        total_ce_oi        = total_ce,
        total_pe_oi        = total_pe,
        pcr                = pcr,
        pain_curve         = pain_curve,
        top_pain_strikes   = top5,
        ce_wall            = walls.ce_wall,
        pe_wall            = walls.pe_wall,
    )

    logger.info(
        "Max pain calculated: symbol=%s max_pain=%.2f spot=%.2f "
        "distance=%.2f%% pcr=%.3f strikes=%d",
        getattr(chain, "symbol", "?"),
        max_pain, spot, dist_pct, pcr, len(pain_curve),
    )

    return result
