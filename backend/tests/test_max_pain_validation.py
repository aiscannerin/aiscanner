"""
Unit tests for max_pain_replay_service and max_pain_validation_service.

All tests are pure computation — no database, no network.
We mock ReplayPoint objects directly to test the statistics layer.
"""

import importlib.util
import math
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── Stub Flask/SQLAlchemy imports so modules can be loaded without an app ───

import types

def _pkg(name: str, **attrs):
    """Register a stub *package* (has __path__) so sub-imports work."""
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = []          # makes Python treat it as a package
        m.__package__ = name
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]

def _mod(name: str, **attrs):
    """Register a stub plain module."""
    if name not in sys.modules:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]

# Package stubs
_pkg("app")
_pkg("app.services")
_pkg("app.models")

# Minimal db stub (replay service only calls db.session.query(...).filter().order_by().all())
_fake_q = types.SimpleNamespace(
    filter=lambda *a, **kw: _fake_q,
    order_by=lambda *a, **kw: _fake_q,
    all=lambda: [],
)
_fake_db = types.SimpleNamespace(
    session=types.SimpleNamespace(query=lambda *a, **kw: _fake_q)
)
_mod("app.extensions", db=_fake_db)
_mod("app.models.max_pain_snapshot",
     MaxPainSnapshot=type("MaxPainSnapshot", (), {}))

# ── Load modules by path to bypass Flask app/__init__.py ───────────────────

def _load(short_name: str, rel_path: str, pkg_alias: str = None):
    """Load a .py file directly; register under short_name and pkg_alias."""
    path = os.path.join(os.path.dirname(__file__), "..", rel_path)
    spec = importlib.util.spec_from_file_location(short_name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[short_name] = mod
    if pkg_alias:
        sys.modules[pkg_alias] = mod
    spec.loader.exec_module(mod)
    return mod

_replay = _load(
    "max_pain_replay_service",
    "app/services/max_pain_replay_service.py",
    pkg_alias="app.services.max_pain_replay_service",
)

# regime_classifier is now imported by validation_service; load it first
_regime = _load(
    "regime_classifier",
    "app/services/regime_classifier.py",
    pkg_alias="app.services.regime_classifier",
)

_val = _load(
    "max_pain_validation_service",
    "app/services/max_pain_validation_service.py",
    pkg_alias="app.services.max_pain_validation_service",
)

# Re-export symbols we need
ReplayPoint       = _replay.ReplayPoint
HorizonOutcome    = _replay.HorizonOutcome
WallState         = _replay.WallState
HORIZONS          = _replay.HORIZONS
_build_outcome    = _replay._build_outcome
_find_forward     = _replay._find_forward
_days_to_expiry   = _replay._days_to_expiry
_wall_state_fn    = _replay._wall_state

_compute_horizon_stats = _val._compute_horizon_stats
_confidence_score      = _val._confidence_score
_binomial_p_value      = _val._binomial_p_value
_segment_regimes       = _val._segment_regimes
_signal_stats          = _val._signal_stats
_oi_wall_analysis      = _val._oi_wall_analysis
HorizonStats           = _val.HorizonStats
_MIN_SAMPLE_COMPUTE    = _val._MIN_SAMPLE_COMPUTE


import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_point(
    distance_pct: float = 3.0,
    direction: str = "bearish",
    pcr: float = 1.0,
    avg_iv: float = 15.0,
    days_to_expiry: int = 10,
    ce_migrated: bool = False,
    pe_migrated: bool = False,
    outcomes: dict = None,
) -> ReplayPoint:
    ts = datetime.now(timezone.utc).isoformat()
    return ReplayPoint(
        snapshot_id="test-id",
        symbol="TEST",
        expiry="25-Dec-2025",
        captured_at=ts,
        spot_price=100.0,
        max_pain=103.0 if direction == "bearish" else 97.0,
        distance_pct=distance_pct,
        direction=direction,
        pcr=pcr,
        pcr_bias="neutral",
        avg_iv=avg_iv,
        atm_ce_iv=avg_iv,
        atm_pe_iv=avg_iv,
        ce_wall_strike=105.0,
        ce_wall_oi=10000,
        pe_wall_strike=95.0,
        pe_wall_oi=8000,
        total_ce_oi=50000,
        total_pe_oi=55000,
        reversal_score=None,
        original_distance=3.0,
        days_to_expiry=days_to_expiry,
        wall_state=WallState(
            ce_migrated=ce_migrated, pe_migrated=pe_migrated,
            ce_direction="up" if ce_migrated else "stable",
            pe_direction="stable",
        ),
        outcomes=outcomes or {},
    )


def _outcome(horizon: str, hit: bool, conv_pct: float, raw_ret: float) -> HorizonOutcome:
    return HorizonOutcome(
        horizon=horizon,
        minutes=HORIZONS[horizon],
        future_spot=100.0,
        future_captured_at=datetime.now(timezone.utc).isoformat(),
        raw_return_pct=raw_ret,
        convergent_pct=conv_pct,
        hit=hit,
    )


def _points_with_outcomes(n: int, hit_rate: float, horizon: str = "1h") -> list:
    """Generate n points where ~hit_rate fraction are hits."""
    points = []
    hits   = int(n * hit_rate)
    for i in range(n):
        is_hit = i < hits
        conv   = 3.5 if is_hit else -2.0
        raw    = -0.8 if is_hit else 0.5
        pt = _make_point(outcomes={horizon: _outcome(horizon, is_hit, conv, raw)})
        points.append(pt)
    return points


# ===========================================================================
# TestBuildOutcome — convergence calculation
# ===========================================================================

class TestBuildOutcome:

    def test_convergence_bearish_hit(self):
        """Bearish: spot=103, max_pain=100. Future spot=101 → converged."""
        o = _build_outcome("1h", 60, 103.0, 100.0, 101.0,
                           datetime.now(timezone.utc))
        assert o.hit is True
        assert o.convergent_pct > 0

    def test_convergence_bearish_miss(self):
        """Bearish: spot=103, max_pain=100. Future spot=106 → diverged."""
        o = _build_outcome("1h", 60, 103.0, 100.0, 106.0,
                           datetime.now(timezone.utc))
        assert o.hit is False
        assert o.convergent_pct < 0

    def test_convergence_bullish_hit(self):
        """Bullish: spot=97, max_pain=100. Future spot=99 → converged."""
        o = _build_outcome("1h", 60, 97.0, 100.0, 99.0,
                           datetime.now(timezone.utc))
        assert o.hit is True
        assert o.convergent_pct > 0

    def test_convergence_bullish_miss(self):
        """Bullish: spot=97, max_pain=100. Future spot=94 → diverged."""
        o = _build_outcome("1h", 60, 97.0, 100.0, 94.0,
                           datetime.now(timezone.utc))
        assert o.hit is False
        assert o.convergent_pct < 0

    def test_convergence_pct_calculation(self):
        """spot=110, max_pain=100: original_dist=10. future=105: future_dist=5. conv=50%."""
        o = _build_outcome("1h", 60, 110.0, 100.0, 105.0,
                           datetime.now(timezone.utc))
        assert o.hit is True
        assert abs(o.convergent_pct - 50.0) < 0.01

    def test_no_future_spot(self):
        """Missing future data → all fields None, hit=None."""
        o = _build_outcome("1h", 60, 100.0, 100.0, None, None)
        assert o.hit is None
        assert o.convergent_pct is None
        assert o.raw_return_pct is None

    def test_zero_original_distance(self):
        """spot == max_pain → no signal, hit=False, convergent_pct=0."""
        o = _build_outcome("1h", 60, 100.0, 100.0, 101.0,
                           datetime.now(timezone.utc))
        assert o.hit is False
        assert o.convergent_pct == 0.0

    def test_raw_return_sign(self):
        """Raw return is unsigned directional — just (future-signal)/signal."""
        o = _build_outcome("1h", 60, 100.0, 95.0, 103.0,
                           datetime.now(timezone.utc))
        assert o.raw_return_pct is not None
        assert abs(o.raw_return_pct - 3.0) < 0.01


# ===========================================================================
# TestFindForward — binary search correctness
# ===========================================================================

class TestFindForward:

    def _make_times(self, n: int, start: datetime, interval_minutes: int):
        return [start + timedelta(minutes=i * interval_minutes) for i in range(n)]

    def test_exact_match_15m(self):
        """Snapshots every 5 min. Target +15m should find index 3."""
        start = datetime(2025, 1, 2, 9, 15, tzinfo=timezone.utc)
        times = self._make_times(20, start, 5)
        spots = [100.0 + i for i in range(20)]
        spot, ts = _find_forward(times, spots, 0, 15, 4)
        assert spot == spots[3]

    def test_within_tolerance(self):
        """Target time within tolerance window should be found."""
        start = datetime(2025, 1, 2, 9, 15, tzinfo=timezone.utc)
        times = self._make_times(20, start, 5)
        spots = [100.0 + i * 0.5 for i in range(20)]
        # 1h target = 12 intervals away; tolerance = ±8min = ±1.6 intervals
        spot, ts = _find_forward(times, spots, 0, 60, 8)
        assert spot is not None

    def test_out_of_range(self):
        """No snapshots within tolerance → returns (None, None)."""
        start = datetime(2025, 1, 2, 9, 15, tzinfo=timezone.utc)
        times = self._make_times(5, start, 5)   # only 25 minutes of data
        spots = [100.0] * 5
        spot, ts = _find_forward(times, spots, 0, 60, 4)
        assert spot is None
        assert ts is None

    def test_never_returns_same_index(self):
        """forward match must be strictly after from_idx."""
        start = datetime(2025, 1, 2, 9, 15, tzinfo=timezone.utc)
        times = self._make_times(3, start, 5)
        spots = [100.0, 101.0, 102.0]
        # 5 min target, but only look 1 step forward in 3-element list
        spot, _ = _find_forward(times, spots, 0, 5, 4)
        assert spot == spots[1]   # must be index 1, not 0

    def test_picks_closest(self):
        """When multiple snapshots are within tolerance, pick the closest."""
        start = datetime(2025, 1, 2, 9, 15, tzinfo=timezone.utc)
        # 5-min intervals, target = 15m, tolerance = 6min
        # t+13min and t+18min both within tolerance
        times = [
            start,
            start + timedelta(minutes=5),
            start + timedelta(minutes=13),   # 2 min before target
            start + timedelta(minutes=18),   # 3 min after target
        ]
        spots = [100.0, 101.0, 102.0, 103.0]
        spot, _ = _find_forward(times, spots, 0, 15, 6)
        assert spot == 102.0   # index 2 is closer to t+15


# ===========================================================================
# TestDaysToExpiry
# ===========================================================================

class TestDaysToExpiry:

    def test_future_expiry(self):
        from datetime import date
        # Use a far-future date
        exp = "01-Jan-2030"
        days = _days_to_expiry(exp)
        assert days > 0

    def test_past_expiry(self):
        exp = "01-Jan-2020"
        assert _days_to_expiry(exp) == 0

    def test_none_expiry(self):
        assert _days_to_expiry(None) == 0

    def test_invalid_format(self):
        assert _days_to_expiry("not-a-date") == 0


# ===========================================================================
# TestBinomialPValue
# ===========================================================================

class TestBinomialPValue:

    def test_perfect_hit_rate(self):
        """30 hits out of 30 trials: very significant."""
        p = _binomial_p_value(30, 30)
        assert p is not None
        assert p < 0.001

    def test_random_hit_rate(self):
        """15 hits out of 30: not significant (p ~ 1.0)."""
        p = _binomial_p_value(15, 30)
        assert p is not None
        assert p > 0.5

    def test_small_n(self):
        """n < 10: returns None."""
        assert _binomial_p_value(5, 8) is None

    def test_p_value_range(self):
        """p-value must be in [0, 1]."""
        for hits in [10, 20, 30, 50]:
            for n in [30, 50, 100]:
                if hits <= n:
                    p = _binomial_p_value(hits, n)
                    if p is not None:
                        assert 0.0 <= p <= 1.0

    def test_symmetric(self):
        """p(hits=20, n=30) == p(hits=10, n=30) (symmetry around 0.5)."""
        p1 = _binomial_p_value(20, 30)
        p2 = _binomial_p_value(10, 30)
        if p1 is not None and p2 is not None:
            assert abs(p1 - p2) < 0.001


# ===========================================================================
# TestConfidenceScore
# ===========================================================================

class TestConfidenceScore:

    def test_large_sample_significant(self):
        """n=100, hit_rate=0.7, p<0.01 → high confidence."""
        p = _binomial_p_value(70, 100)
        c = _confidence_score(100, 0.70, p)
        assert c >= 0.8

    def test_small_sample(self):
        """n=5, hit_rate=0.80, p=None → sample(0.1) + effect(0.3) + sig(0.0) = 0.4."""
        c = _confidence_score(5, 0.80, None)
        # Large effect size adds 0.3 even with tiny sample; no significance bonus.
        assert c <= 0.45  # capped well below 0.8 (the large-sample threshold)
        assert c >= 0.3   # but not zero — big effect size still contributes

    def test_random_hit_rate(self):
        """hit_rate=0.5 → no effect size, low confidence even with large n."""
        p = _binomial_p_value(50, 100)
        c = _confidence_score(100, 0.50, p)
        # Large n but no signal → should be low-moderate
        assert c <= 0.6

    def test_range(self):
        """Confidence score always in [0, 1]."""
        for n in [5, 15, 30, 100]:
            for hr in [0.3, 0.5, 0.7, 0.9]:
                c = _confidence_score(n, hr, None)
                assert 0.0 <= c <= 1.0


# ===========================================================================
# TestComputeHorizonStats
# ===========================================================================

class TestComputeHorizonStats:

    def test_all_hits(self):
        """100% hit rate → is_significant=True for large enough N."""
        points = _points_with_outcomes(50, 1.0, "1h")
        stats  = _compute_horizon_stats(points, "1h")
        assert stats.hit_rate == 1.0
        assert stats.hit_count == 50
        assert stats.miss_count == 0
        assert stats.is_significant is True

    def test_all_misses(self):
        """0% hit rate → also statistically significant (opposite direction)."""
        points = _points_with_outcomes(50, 0.0, "1h")
        stats  = _compute_horizon_stats(points, "1h")
        assert stats.hit_rate == 0.0
        assert stats.is_significant is True

    def test_random_outcomes(self):
        """50% hit rate → not significant."""
        points = _points_with_outcomes(60, 0.5, "1h")
        stats  = _compute_horizon_stats(points, "1h")
        assert stats.hit_rate == 0.5
        assert stats.is_significant is False

    def test_no_outcomes_returns_warning(self):
        """Points with no resolved outcomes → insufficient_data warning."""
        points = [_make_point(outcomes={}) for _ in range(10)]
        stats  = _compute_horizon_stats(points, "1h")
        assert stats.hit_rate is None
        assert any("insufficient_data" in w for w in stats.warnings)

    def test_small_sample_warning(self):
        """N < MIN_SAMPLE_WARN → warning present but stats computed."""
        points = _points_with_outcomes(10, 0.7, "1h")
        stats  = _compute_horizon_stats(points, "1h")
        assert stats.hit_rate is not None
        assert any("small_sample" in w for w in stats.warnings)

    def test_expectancy_formula(self):
        """
        50 points: 30 hits with avg_convergent=3.5%, 20 misses with avg_divergent=2.0%
        expectancy = 0.6*3.5 - 0.4*2.0 = 2.1 - 0.8 = 1.3%
        """
        points = []
        for i in range(30):
            points.append(_make_point(outcomes={
                "1h": _outcome("1h", True, 3.5, -0.8)
            }))
        for i in range(20):
            points.append(_make_point(outcomes={
                "1h": _outcome("1h", False, -2.0, 0.5)
            }))
        stats = _compute_horizon_stats(points, "1h")
        assert stats.expectancy_pct is not None
        assert abs(stats.expectancy_pct - 1.3) < 0.05

    def test_available_count(self):
        """available = only points that have a resolved outcome."""
        points = _points_with_outcomes(20, 0.6, "1h")
        # Add 5 points with no outcome
        for _ in range(5):
            points.append(_make_point(outcomes={}))
        stats = _compute_horizon_stats(points, "1h")
        assert stats.sample_size == 25
        assert stats.available   == 20


# ===========================================================================
# TestSegmentRegimes
# ===========================================================================

class TestSegmentRegimes:

    def test_expiry_week_segmentation(self):
        """Points with days_to_expiry <= 5 go into expiry_week bucket."""
        near   = [_make_point(days_to_expiry=3)  for _ in range(5)]
        far    = [_make_point(days_to_expiry=15) for _ in range(8)]
        all_pts = near + far
        buckets = _segment_regimes(all_pts)
        assert len(buckets["expiry_week"])     == 5
        assert len(buckets["non_expiry_week"]) == 8

    def test_iv_regime_segmentation(self):
        """High IV points go into high_iv bucket only."""
        high = [_make_point(avg_iv=25.0) for _ in range(4)]
        low  = [_make_point(avg_iv=10.0) for _ in range(6)]
        all_pts = high + low
        buckets = _segment_regimes(all_pts)
        assert len(buckets["high_iv"]) == 4
        assert len(buckets["low_iv"])  == 6

    def test_direction_segmentation(self):
        bull = [_make_point(direction="bullish") for _ in range(7)]
        bear = [_make_point(direction="bearish") for _ in range(5)]
        buckets = _segment_regimes(bull + bear)
        assert len(buckets["bullish_signal"]) == 7
        assert len(buckets["bearish_signal"]) == 5

    def test_non_exclusive(self):
        """A point can appear in multiple regime buckets."""
        # high IV + expiry_week + high distance
        pt = _make_point(avg_iv=25.0, days_to_expiry=3, distance_pct=5.0)
        buckets = _segment_regimes([pt])
        assert len(buckets["high_iv"])       == 1
        assert len(buckets["expiry_week"])   == 1
        assert len(buckets["high_distance"]) == 1

    def test_wall_migrating_segment(self):
        migrating = [_make_point(ce_migrated=True)  for _ in range(3)]
        stable    = [_make_point(ce_migrated=False) for _ in range(7)]
        buckets   = _segment_regimes(migrating + stable)
        assert len(buckets["wall_migrating"]) == 3
        assert len(buckets["wall_stable"])    == 7


# ===========================================================================
# TestSignalStats
# ===========================================================================

class TestSignalStats:

    def test_basic_counts(self):
        bull = [_make_point(direction="bullish") for _ in range(6)]
        bear = [_make_point(direction="bearish") for _ in range(4)]
        s = _signal_stats(bull + bear)
        assert s["count"]           == 10
        assert s["bullish_signals"] == 6
        assert s["bearish_signals"] == 4

    def test_empty(self):
        assert _signal_stats([]) == {}

    def test_distance_stats(self):
        pts = [_make_point(distance_pct=float(d)) for d in [1, 2, 3, 4, 5]]
        s = _signal_stats(pts)
        assert s["distance_pct"]["mean"] == 3.0
        assert s["distance_pct"]["min"]  == 1.0
        assert s["distance_pct"]["max"]  == 5.0


# ===========================================================================
# TestOIWallAnalysis
# ===========================================================================

class TestOIWallAnalysis:

    def test_migration_rate(self):
        pts = [_make_point(ce_migrated=True) for _ in range(4)] + \
              [_make_point(ce_migrated=False) for _ in range(6)]
        a = _oi_wall_analysis(pts)
        assert a.ce_migration_count == 4
        assert a.ce_migration_rate  == 0.4

    def test_zero_points(self):
        a = _oi_wall_analysis([])
        assert a.total_ticks          == 0
        assert a.ce_migration_rate    is None


# ===========================================================================
# Integration: end-to-end statistics consistency
# ===========================================================================

class TestStatisticsConsistency:

    def test_hit_count_equals_sum(self):
        """hit_count + miss_count must equal available."""
        points = _points_with_outcomes(40, 0.65, "4h")
        stats  = _compute_horizon_stats(points, "4h")
        assert stats.hit_count + stats.miss_count == stats.available

    def test_hit_rate_from_counts(self):
        """hit_rate = hit_count / available."""
        points = _points_with_outcomes(50, 0.72, "15m")
        stats  = _compute_horizon_stats(points, "15m")
        if stats.available > 0:
            expected = round(stats.hit_count / stats.available, 4)
            assert stats.hit_rate == expected

    def test_p_value_none_for_small_n(self):
        """p_value is None when available < 10."""
        points = _points_with_outcomes(7, 0.85, "1d")
        stats  = _compute_horizon_stats(points, "1d")
        assert stats.p_value is None

    def test_confidence_zero_when_insufficient(self):
        """confidence_score = 0.0 when no data resolves."""
        points = [_make_point(outcomes={}) for _ in range(20)]
        stats  = _compute_horizon_stats(points, "1h")
        assert stats.confidence_score == 0.0
