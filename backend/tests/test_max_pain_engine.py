"""
Unit tests for max_pain_engine.py
===================================
All tests use in-process mocked data — no NSE network calls, no database.

Test coverage
-------------
  TestCalculateMaxPain
    test_simple_symmetric_chain         — basic 3-strike chain, verify math
    test_known_asymmetric_chain         — manual payout verification
    test_max_pain_is_minimum_pain       — max pain has lowest total_pain in curve
    test_distance_metrics               — distance_from_spot / distance_pct
    test_pcr_calculation                — PCR = total PE OI / total CE OI
    test_pcr_zero_ce_oi                 — PCR = 0.0 when CE OI = 0 (no division error)
    test_zero_oi_chain                  — all OI = 0, pain curve is all zeros
    test_pain_curve_ordered_ascending   — pain_curve strikes ascend
    test_top_pain_strikes_length        — top_pain_strikes <= 5 entries
    test_top_pain_strikes_sorted        — lowest total_pain comes first

  TestGetOIWalls
    test_ce_wall_above_spot             — CE wall is highest CE OI above spot
    test_pe_wall_below_spot             — PE wall is highest PE OI below spot
    test_walls_fallback_no_above        — fallback when no strikes above spot
    test_walls_fallback_no_below        — fallback when no strikes below spot

  TestCalculatePainCurve
    test_pain_curve_length              — one point per valid strike
    test_pain_curve_skips_bad_strikes   — malformed (strike=0) rows skipped
    test_pain_curve_values_manual       — spot-check payout values by hand

  TestEdgeCases
    test_single_strike_raises           — only 1 strike → MaxPainError
    test_empty_strikes_raises           — empty list → MaxPainError
    test_none_oi_treated_as_zero        — None OI values don't crash
    test_dict_chain_accepted            — plain dict chain works (not only dataclass)
    test_all_same_pain                  — ties broken deterministically (first min)
    test_large_chain_perf               — 200-strike chain completes quickly
"""

import time
import pytest
from dataclasses import dataclass, field
from typing import List

# ── Import the engine directly by file path to avoid Flask app/__init__.py ──
import sys, os, importlib.util

_ENGINE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "max_pain_engine.py"
)
_spec = importlib.util.spec_from_file_location("max_pain_engine", _ENGINE_PATH)
_mod  = importlib.util.module_from_spec(_spec)
sys.modules["max_pain_engine"] = _mod
_spec.loader.exec_module(_mod)

MaxPainError       = _mod.MaxPainError
MaxPainResult      = _mod.MaxPainResult
OIWall             = _mod.OIWall
OIWalls            = _mod.OIWalls
PainPoint          = _mod.PainPoint
calculate_max_pain  = _mod.calculate_max_pain
calculate_pain_curve = _mod.calculate_pain_curve
get_oi_walls       = _mod.get_oi_walls


# ---------------------------------------------------------------------------
# Mock data builders
# ---------------------------------------------------------------------------

@dataclass
class MockLeg:
    oi: int = 0


@dataclass
class MockStrike:
    strike: float
    ce: MockLeg = field(default_factory=MockLeg)
    pe: MockLeg = field(default_factory=MockLeg)


@dataclass
class MockChain:
    strikes: List[MockStrike]
    spot_price: float
    symbol: str = "TEST"


def _chain(*rows, spot: float = 100.0) -> MockChain:
    """
    Quick builder: rows is a list of (strike, ce_oi, pe_oi) tuples.
    """
    strikes = [MockStrike(strike=s, ce=MockLeg(oi=c), pe=MockLeg(oi=p))
               for (s, c, p) in rows]
    return MockChain(strikes=strikes, spot_price=spot)


def _dict_chain(*rows, spot: float = 100.0) -> dict:
    """Plain dict equivalent of _chain — tests the dict code path."""
    return {
        "spot_price": spot,
        "symbol": "DICT",
        "strikes": [
            {"strike": s, "ce_oi": c, "pe_oi": p}
            for (s, c, p) in rows
        ],
    }


# ---------------------------------------------------------------------------
# Pain math helper — independent reference implementation
# ---------------------------------------------------------------------------

def _manual_pain(strikes, candidate):
    """
    Reference implementation — used to cross-check the engine.
    strikes: list of (strike_val, ce_oi, pe_oi)
    """
    ce = sum(max(0, candidate - s) * c for (s, c, p) in strikes if s < candidate)
    pe = sum(max(0, s - candidate) * p for (s, c, p) in strikes if s > candidate)
    return ce, pe, ce + pe


# ===========================================================================
# TestCalculateMaxPain
# ===========================================================================

class TestCalculateMaxPain:

    def test_simple_symmetric_chain(self):
        """
        3-strike chain. Verified by hand:

          Data: 90(CE=0,PE=1000)  100(CE=500,PE=500)  110(CE=1000,PE=0)

          CE_payout(S) = Σ (S-K)*CE_OI[K]  for K < S
          PE_payout(S) = Σ (K-S)*PE_OI[K]  for K > S

          candidate=90:
            CE = 0 (nothing left of 90)
            PE = (100-90)*PE_OI[100] + (110-90)*PE_OI[110]
               = 10*500 + 20*0 = 5000
            total = 5000

          candidate=100:
            CE = (100-90)*CE_OI[90] = 10*0 = 0
            PE = (110-100)*PE_OI[110] = 10*0 = 0
            total = 0  ← MINIMUM → max pain = 100

          candidate=110:
            CE = (110-90)*CE_OI[90] + (110-100)*CE_OI[100]
               = 20*0 + 10*500 = 5000
            PE = 0 (nothing right of 110)
            total = 5000
        """
        chain = _chain((90, 0, 1000), (100, 500, 500), (110, 1000, 0), spot=100.0)
        result = calculate_max_pain(chain)

        assert result.max_pain == 100.0   # minimum pain is at centre
        assert result.spot_price == 100.0
        assert isinstance(result, MaxPainResult)
        # Pain at 90 and 110 must both be 5000
        p90  = next(p for p in result.pain_curve if p.strike == 90.0)
        p110 = next(p for p in result.pain_curve if p.strike == 110.0)
        assert p90.total_pain  == 5000.0
        assert p110.total_pain == 5000.0

    def test_known_asymmetric_chain(self):
        """
        Manually verifiable 4-strike chain.

        Strikes and OI:
          100: CE=200, PE=0
          110: CE=300, PE=100
          120: CE=100, PE=400
          130: CE=0,   PE=500

        For candidate=110:
          CE_payout = (110-100)*200 = 2000
          PE_payout = (120-110)*400 + (130-110)*500 = 4000 + 10000 = 14000
          total = 16000

        For candidate=120:
          CE_payout = (120-100)*200 + (120-110)*300 = 4000 + 3000 = 7000
          PE_payout = (130-120)*500 = 5000
          total = 12000

        For candidate=130:
          CE_payout = (130-100)*200 + (130-110)*300 + (130-120)*100 = 6000+6000+1000=13000
          PE_payout = 0
          total = 13000

        For candidate=100:
          CE_payout = 0
          PE_payout = (110-100)*100 + (120-100)*400 + (130-100)*500
                    = 1000 + 8000 + 15000 = 24000
          total = 24000

        Min is 12000 at strike=120 → max pain = 120
        """
        chain = _chain(
            (100, 200, 0),
            (110, 300, 100),
            (120, 100, 400),
            (130, 0, 500),
            spot=115.0,
        )
        result = calculate_max_pain(chain)
        assert result.max_pain == 120.0

        # Verify pain curve contains the expected value at 120
        p120 = next(p for p in result.pain_curve if p.strike == 120.0)
        assert p120.ce_payout == 7000.0
        assert p120.pe_payout == 5000.0
        assert p120.total_pain == 12000.0

    def test_max_pain_is_minimum_pain(self):
        """The max pain strike must always have the lowest total_pain in the curve."""
        chain = _chain(
            (50,  100, 500),
            (75,  200, 400),
            (100, 300, 300),
            (125, 400, 200),
            (150, 500, 100),
            spot=100.0,
        )
        result = calculate_max_pain(chain)
        min_pain = min(p.total_pain for p in result.pain_curve)
        mp_point = next(p for p in result.pain_curve if p.strike == result.max_pain)
        assert mp_point.total_pain == min_pain

    def test_distance_metrics(self):
        chain = _chain((95, 100, 200), (100, 150, 150), (105, 200, 100), spot=102.0)
        result = calculate_max_pain(chain)
        expected_dist = abs(102.0 - result.max_pain)
        expected_pct  = round(expected_dist / 102.0 * 100, 4)
        assert result.distance_from_spot == round(expected_dist, 2)
        assert result.distance_pct == expected_pct

    def test_pcr_calculation(self):
        chain = _chain((90, 100, 300), (100, 200, 200), (110, 300, 100), spot=100.0)
        result = calculate_max_pain(chain)
        # total CE = 600, total PE = 600 → PCR = 1.0
        assert result.total_ce_oi == 600
        assert result.total_pe_oi == 600
        assert result.pcr == 1.0

    def test_pcr_zero_ce_oi(self):
        """PCR must be 0.0 when total CE OI is zero — no division error."""
        chain = _chain((90, 0, 100), (100, 0, 200), (110, 0, 50), spot=100.0)
        result = calculate_max_pain(chain)
        assert result.total_ce_oi == 0
        assert result.pcr == 0.0

    def test_zero_oi_chain(self):
        """A chain where all OI = 0 should produce a valid result (all pain = 0)."""
        chain = _chain((90, 0, 0), (100, 0, 0), (110, 0, 0), spot=100.0)
        result = calculate_max_pain(chain)
        # All pain = 0 — max pain lands at first min (deterministic)
        assert all(p.total_pain == 0.0 for p in result.pain_curve)
        assert result.pcr == 0.0

    def test_pain_curve_ordered_ascending(self):
        chain = _chain((110, 100, 50), (90, 50, 100), (100, 75, 75), spot=100.0)
        result = calculate_max_pain(chain)
        strikes = [p.strike for p in result.pain_curve]
        assert strikes == sorted(strikes)

    def test_top_pain_strikes_length(self):
        chain = _chain(
            (80, 100, 500), (85, 150, 450), (90, 200, 400),
            (95, 250, 350), (100, 300, 300), (105, 350, 250),
            (110, 400, 200), spot=100.0,
        )
        result = calculate_max_pain(chain)
        assert len(result.top_pain_strikes) <= 5

    def test_top_pain_strikes_sorted(self):
        """top_pain_strikes[0] must have the lowest total_pain."""
        chain = _chain(
            (90, 100, 300), (95, 150, 250), (100, 200, 200),
            (105, 250, 150), (110, 300, 100), spot=100.0,
        )
        result = calculate_max_pain(chain)
        pains = [p.total_pain for p in result.top_pain_strikes]
        assert pains == sorted(pains)
        assert result.top_pain_strikes[0].strike == result.max_pain


# ===========================================================================
# TestGetOIWalls
# ===========================================================================

class TestGetOIWalls:

    def test_ce_wall_above_spot(self):
        """CE wall is the strike above spot with the highest CE OI."""
        chain = _chain(
            (90,  50, 200),
            (100, 80, 100),
            (110, 300, 50),   # ← highest CE OI above spot=95
            (120, 200, 30),
            spot=95.0,
        )
        walls = get_oi_walls(chain)
        assert walls.ce_wall.strike == 110.0
        assert walls.ce_wall.oi == 300
        assert walls.ce_wall.side == "CE"

    def test_pe_wall_below_spot(self):
        """PE wall is the strike below spot with the highest PE OI."""
        chain = _chain(
            (80,  50,  50),
            (90,  50, 400),   # ← highest PE OI below spot=95
            (100, 80, 100),
            (110, 300, 50),
            spot=95.0,
        )
        walls = get_oi_walls(chain)
        assert walls.pe_wall.strike == 90.0
        assert walls.pe_wall.oi == 400
        assert walls.pe_wall.side == "PE"

    def test_walls_fallback_no_above(self):
        """When no strikes are above spot, fall back to highest CE OI in full chain."""
        chain = _chain(
            (80, 100, 200),
            (90, 300, 100),   # highest CE OI
            spot=100.0,       # spot above all strikes
        )
        walls = get_oi_walls(chain)
        assert walls.ce_wall.strike == 90.0
        assert walls.ce_wall.oi == 300

    def test_walls_fallback_no_below(self):
        """When no strikes are below spot, fall back to highest PE OI in full chain."""
        chain = _chain(
            (110, 100, 200),
            (120, 50,  500),  # highest PE OI
            spot=100.0,       # spot below all strikes
        )
        walls = get_oi_walls(chain)
        assert walls.pe_wall.strike == 120.0
        assert walls.pe_wall.oi == 500


# ===========================================================================
# TestCalculatePainCurve
# ===========================================================================

class TestCalculatePainCurve:

    def test_pain_curve_length(self):
        chain = _chain((90, 100, 200), (100, 150, 150), (110, 200, 100), spot=100.0)
        curve = calculate_pain_curve(chain)
        assert len(curve) == 3

    def test_pain_curve_skips_bad_strikes(self):
        """Rows with strike=0 or negative are silently skipped."""
        chain = MockChain(
            spot_price=100.0,
            strikes=[
                MockStrike(strike=0.0,  ce=MockLeg(100), pe=MockLeg(100)),  # invalid
                MockStrike(strike=-5.0, ce=MockLeg(100), pe=MockLeg(100)),  # invalid
                MockStrike(strike=90.0, ce=MockLeg(100), pe=MockLeg(200)),
                MockStrike(strike=100.0,ce=MockLeg(150), pe=MockLeg(150)),
            ],
        )
        curve = calculate_pain_curve(chain)
        assert len(curve) == 2
        assert all(p.strike > 0 for p in curve)

    def test_pain_curve_values_manual(self):
        """
        Two-strike chain — easy to verify by hand.

        Strikes: 90 (CE=0, PE=500), 110 (CE=500, PE=0). Spot=100.

        candidate=90: CE=0 (nothing left), PE=0 (nothing right with s>90 that hits)
          wait — 110 > 90, so PE_payout = (110-90)*0=0? No, PE OI is at strike 90
          Let me redo:
            Strike 90: ce_oi=0, pe_oi=500
            Strike 110: ce_oi=500, pe_oi=0

          candidate=90:
            CE_payout = 0 (no strike < 90)
            PE_payout = (110-90)*0 = 0  [pe_oi at 110 = 0]
            total = 0

          candidate=110:
            CE_payout = (110-90)*0 = 0  [ce_oi at 90 = 0]
            PE_payout = 0 (no strike > 110)
            total = 0

          Both = 0. That's a degenerate case.

        Use: 90 (CE=200, PE=0), 110 (CE=0, PE=300). Spot=100.
          candidate=90:  CE=0, PE=(110-90)*300=6000, total=6000
          candidate=110: CE=(110-90)*200=4000, PE=0,  total=4000
        """
        chain = _chain((90, 200, 0), (110, 0, 300), spot=100.0)
        curve = calculate_pain_curve(chain)
        assert len(curve) == 2

        p90  = next(p for p in curve if p.strike == 90.0)
        p110 = next(p for p in curve if p.strike == 110.0)

        assert p90.ce_payout  == 0.0
        assert p90.pe_payout  == 6000.0
        assert p90.total_pain == 6000.0

        assert p110.ce_payout  == 4000.0
        assert p110.pe_payout  == 0.0
        assert p110.total_pain == 4000.0


# ===========================================================================
# TestEdgeCases
# ===========================================================================

class TestEdgeCases:

    def test_single_strike_raises(self):
        chain = _chain((100, 100, 100), spot=100.0)
        with pytest.raises(MaxPainError, match="need at least 2"):
            calculate_max_pain(chain)

    def test_empty_strikes_raises(self):
        chain = MockChain(strikes=[], spot_price=100.0)
        with pytest.raises(MaxPainError, match="no strikes"):
            calculate_max_pain(chain)

    def test_none_oi_treated_as_zero(self):
        """None OI values must not cause TypeError or crash."""
        chain = MockChain(
            spot_price=100.0,
            strikes=[
                MockStrike(strike=90.0,  ce=MockLeg(oi=None), pe=MockLeg(oi=200)),
                MockStrike(strike=100.0, ce=MockLeg(oi=150),  pe=MockLeg(oi=None)),
                MockStrike(strike=110.0, ce=MockLeg(oi=200),  pe=MockLeg(oi=100)),
            ],
        )
        # Should not raise
        result = calculate_max_pain(chain)
        assert isinstance(result, MaxPainResult)

    def test_dict_chain_accepted(self):
        """Engine must accept plain dict chains (not only dataclasses)."""
        chain = _dict_chain(
            (90, 100, 300),
            (100, 200, 200),
            (110, 300, 100),
            spot=100.0,
        )
        result = calculate_max_pain(chain)
        assert isinstance(result, MaxPainResult)
        assert result.spot_price == 100.0
        assert result.max_pain > 0

    def test_all_same_pain(self):
        """When all strikes have equal pain, result must still be deterministic."""
        # All CE OI = 0 and PE OI = 0 → all pain = 0 → any strike is valid
        chain = _chain((90, 0, 0), (100, 0, 0), (110, 0, 0), spot=100.0)
        r1 = calculate_max_pain(chain)
        r2 = calculate_max_pain(chain)
        # Must return the same answer twice
        assert r1.max_pain == r2.max_pain

    def test_large_chain_perf(self):
        """200-strike chain must complete in under 2 seconds."""
        strikes = [(float(i * 50), i * 100, (200 - i) * 100) for i in range(1, 201)]
        chain = _chain(*strikes, spot=5000.0)
        t0 = time.monotonic()
        result = calculate_max_pain(chain)
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, f"Took {elapsed:.2f}s — too slow"
        assert isinstance(result, MaxPainResult)
        assert len(result.pain_curve) == 200


# ===========================================================================
# TestPainCurveEquivalence  — validate curve total matches compute_max_pain
# ===========================================================================

class TestPainCurveEquivalence:

    def test_curve_consistent_with_max_pain(self):
        """Pain curve returned by calculate_max_pain == calculate_pain_curve standalone."""
        chain = _chain(
            (100, 200, 500),
            (110, 300, 400),
            (120, 400, 300),
            (130, 500, 200),
            spot=115.0,
        )
        result = calculate_max_pain(chain)
        standalone_curve = calculate_pain_curve(chain)

        # Same number of points
        assert len(result.pain_curve) == len(standalone_curve)

        # Same values (order preserved)
        for a, b in zip(result.pain_curve, standalone_curve):
            assert a.strike     == b.strike
            assert a.ce_payout  == b.ce_payout
            assert a.pe_payout  == b.pe_payout
            assert a.total_pain == b.total_pain

    def test_max_pain_equals_min_of_curve(self):
        chain = _chain(
            (50, 100, 400), (75, 200, 300), (100, 300, 200),
            (125, 400, 100), (150, 500, 50), spot=90.0,
        )
        result = calculate_max_pain(chain)
        curve_min = min(result.pain_curve, key=lambda p: p.total_pain)
        assert result.max_pain == curve_min.strike
