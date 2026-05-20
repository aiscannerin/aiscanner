"""
Unit tests for regime_classifier.py

All tests are pure computation — no database, no network, no Flask.
We build synthetic snapshot objects using a minimal dataclass and verify
that each scorer and the top-level classifier behave correctly.

Coverage
--------
TestHelpers              — _linear_regression, _acf1, _log_returns, _linear_clamp
TestScorerTrending       — direction, R², t-stat, n < MIN_WINDOW
TestScorerRangeBound     — low R², negative ACF, tight range
TestScorerVolExpansion   — rising IV, flat IV, None-heavy IV series
TestScorerVolCompression — falling IV
TestScorerExpiryPinning  — DTE, distance, PCR interaction
TestScorerExhaustion     — high distance + decelerating slope
TestScorerMomentum       — growing distance + PCR alignment
TestClassifySnapshot     — primary regime assignment, secondary regimes, warnings
TestClassifySequence     — rolling window grows correctly, full sequence
TestInferStaticRegime    — single-point static classification
TestFilterIntegration    — _apply_filters in validation service
"""

import importlib.util
import math
import sys
import os
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── Stub Flask / SQLAlchemy so no app bootstrap is needed ───────────────────

def _pkg(name: str, **attrs):
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = []
        m.__package__ = name
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]

def _mod(name: str, **attrs):
    if name not in sys.modules:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]

_pkg("app")
_pkg("app.services")
_pkg("app.models")

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
_mod("app.models.regime_snapshot",
     RegimeSnapshot=type("RegimeSnapshot", (), {}))

# ── Load classifier directly ─────────────────────────────────────────────────

def _load(short_name: str, rel_path: str, alias: str = None):
    path = os.path.join(os.path.dirname(__file__), "..", rel_path)
    spec = importlib.util.spec_from_file_location(short_name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[short_name] = mod
    if alias:
        sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod

_clf = _load(
    "regime_classifier",
    "app/services/regime_classifier.py",
    alias="app.services.regime_classifier",
)

# Re-export
RegimeClassification = _clf.RegimeClassification
classify_snapshot    = _clf.classify_snapshot
classify_sequence    = _clf.classify_sequence
infer_static_regime  = _clf.infer_static_regime
MIN_WINDOW           = _clf.MIN_WINDOW
IDEAL_WINDOW         = _clf.IDEAL_WINDOW
SECONDARY_THRESHOLD  = _clf.SECONDARY_THRESHOLD

_linear_regression     = _clf._linear_regression
_acf1                  = _clf._acf1
_log_returns           = _clf._log_returns
_linear_clamp          = _clf._linear_clamp
_score_trending        = _clf._score_trending
_score_range_bound     = _clf._score_range_bound
_score_vol_expansion   = _clf._score_vol_expansion
_score_vol_compression = _clf._score_vol_compression
_score_expiry_pinning  = _clf._score_expiry_pinning
_score_exhaustion      = _clf._score_exhaustion
_score_momentum_continuation = _clf._score_momentum_continuation


# ── Synthetic snapshot builder ───────────────────────────────────────────────

import uuid as _uuid_mod

@dataclass
class _Snap:
    """Minimal duck-typed MaxPainSnapshot for testing."""
    spot_price:   float
    max_pain:     float
    distance_pct: float
    pcr:          float
    avg_iv:       Optional[float]
    direction:    str
    expiry:       Optional[str]  = None
    symbol:       str            = "TEST"
    id:           object         = field(default_factory=_uuid_mod.uuid4)
    captured_at:  datetime       = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def _snap(
    spot:    float = 22000.0,
    mp:      float = 22000.0,
    dist:    float = 0.0,
    pcr:     float = 1.0,
    iv:      Optional[float] = 15.0,
    dte_days: int  = 10,
) -> _Snap:
    direction = "bearish" if spot > mp else "bullish"
    dist      = dist if dist else abs(spot - mp) / spot * 100
    # Build expiry string from dte_days
    exp_dt = datetime.now(timezone.utc) + timedelta(days=dte_days)
    expiry = exp_dt.strftime("%d-%b-%Y")
    return _Snap(
        spot_price=spot, max_pain=mp, distance_pct=dist,
        pcr=pcr, avg_iv=iv, direction=direction, expiry=expiry,
    )


def _window_of(snaps: list[_Snap]) -> list[_Snap]:
    return snaps


# ── Tests: Pure helpers ──────────────────────────────────────────────────────

class TestHelpers:

    def test_linear_regression_perfect_line(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0, 3.0, 5.0, 7.0]   # y = 2x + 1
        slope, intercept, r_sq = _linear_regression(xs, ys)
        assert abs(slope - 2.0) < 1e-9
        assert abs(intercept - 1.0) < 1e-9
        assert abs(r_sq - 1.0) < 1e-9

    def test_linear_regression_flat_line(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [5.0, 5.0, 5.0, 5.0]
        slope, intercept, r_sq = _linear_regression(xs, ys)
        assert abs(slope) < 1e-9
        # R² is 1.0 for a perfect flat fit (all residuals zero)
        assert r_sq == 1.0

    def test_linear_regression_r_sq_range(self):
        import random
        random.seed(42)
        xs = list(range(20))
        # Noisy data
        ys = [x + random.uniform(-5, 5) for x in xs]
        _, _, r_sq = _linear_regression(xs, ys)
        assert 0.0 <= r_sq <= 1.0

    def test_acf1_random_walk(self):
        """White noise should have ACF ≈ 0."""
        import random
        random.seed(1)
        series = [random.gauss(0, 1) for _ in range(200)]
        acf = _acf1(series)
        assert abs(acf) < 0.20   # allow ±0.20 sampling noise

    def test_acf1_trending_returns(self):
        """Uniformly positive returns → strongly positive ACF."""
        # All returns = +0.01 → perfect autocorrelation
        series = [0.01] * 30
        acf = _acf1(series)
        # Variance is 0 → function returns 0.0 (special case)
        assert acf == 0.0

    def test_acf1_mean_reverting(self):
        """Alternating signs → negative ACF."""
        series = [1.0, -1.0] * 20
        acf = _acf1(series)
        assert acf < -0.5

    def test_log_returns_basic(self):
        prices = [100.0, 110.0, 99.0]
        rets   = _log_returns(prices)
        assert len(rets) == 2
        assert abs(rets[0] - math.log(110 / 100)) < 1e-9
        assert abs(rets[1] - math.log(99 / 110))  < 1e-9

    def test_log_returns_skips_non_positive(self):
        prices = [100.0, 0.0, 110.0]
        rets   = _log_returns(prices)
        # 0.0 is not positive → the pair (0, 110) is skipped, (100, 0) skipped
        assert len(rets) == 0

    def test_linear_clamp_midpoint(self):
        assert abs(_linear_clamp(5.0, 0.0, 10.0) - 0.5) < 1e-9

    def test_linear_clamp_bounds(self):
        assert _linear_clamp(-5.0, 0.0, 10.0) == 0.0
        assert _linear_clamp(15.0, 0.0, 10.0) == 1.0

    def test_linear_clamp_degenerate(self):
        # x_hi <= x_lo → always 0.0
        assert _linear_clamp(5.0, 5.0, 5.0) == 0.0


# ── Tests: Trending scorer ───────────────────────────────────────────────────

class TestScorerTrending:

    def test_strong_uptrend_scores_high(self):
        """20 bars of steady 0.1% per-bar rise → high trending score."""
        prices = [22000.0 * (1 + 0.001 * i) for i in range(20)]
        score, metrics = _score_trending(prices)
        assert score > 0.60, f"expected > 0.60, got {score}"
        assert "r_squared" in metrics
        assert metrics["r_squared"] > 0.90

    def test_symmetric_oscillation_scores_low(self):
        """Perfectly alternating prices: +50, -50, … have zero drift and zero R²."""
        # Prices: 22050, 21950, 22050, 21950, … (no net drift, no linear trend)
        prices = [22000.0 + (-1) ** i * 50 for i in range(20)]
        score, metrics = _score_trending(prices)
        # OLS slope ≈ 0 (symmetric), t-stat ≈ 0 (mean log return ≈ 0)
        assert score < 0.30, f"expected < 0.30 (no trend), got {score}"
        assert metrics["r_squared"] < 0.10

    def test_insufficient_window_returns_zero(self):
        prices = [22000.0, 22100.0, 22200.0]   # only 3 bars < MIN_WINDOW
        score, metrics = _score_trending(prices)
        assert score == 0.0
        assert "reason" in metrics

    def test_score_in_range(self):
        prices = [22000.0 + i * 50 for i in range(15)]
        score, _ = _score_trending(prices)
        assert 0.0 <= score <= 1.0

    def test_downtrend_also_scores_high(self):
        """Trending is direction-agnostic (uses |drift|)."""
        prices = [22000.0 * (1 - 0.001 * i) for i in range(20)]
        score_up, _ = _score_trending([22000.0 * (1 + 0.001 * i) for i in range(20)])
        score_dn, _ = _score_trending(prices)
        # Both should score roughly the same (symmetric)
        assert abs(score_up - score_dn) < 0.05


# ── Tests: Range-bound scorer ─────────────────────────────────────────────────

class TestScorerRangeBound:

    def test_tight_oscillation_scores_high(self):
        """Prices oscillating ±0.1% around mean → high range_bound score."""
        import math
        prices = [22000.0 + 20 * math.sin(i) for i in range(20)]
        score, metrics = _score_range_bound(prices)
        assert score > 0.55, f"expected > 0.55, got {score}"

    def test_strong_trend_scores_low(self):
        """Linearly rising prices → range_bound score should be low."""
        prices = [22000.0 + i * 100 for i in range(20)]
        score, _ = _score_range_bound(prices)
        assert score < 0.55, f"expected < 0.55, got {score}"

    def test_insufficient_window_returns_zero(self):
        score, metrics = _score_range_bound([22000.0, 22100.0])
        assert score == 0.0

    def test_score_in_range(self):
        prices = [22000.0 + 10 * (i % 5) for i in range(15)]
        score, _ = _score_range_bound(prices)
        assert 0.0 <= score <= 1.0


# ── Tests: Vol expansion / compression ───────────────────────────────────────

class TestScorerVolExpansion:

    def test_rising_iv_scores_high(self):
        ivs = [12.0 + i * 0.5 for i in range(16)]   # 12 → 19.5
        score, metrics = _score_vol_expansion(ivs)
        assert score > 0.50, f"expected > 0.50, got {score}"
        assert metrics["iv_change_pct"] > 0

    def test_flat_iv_scores_low(self):
        ivs = [15.0] * 15
        score, _ = _score_vol_expansion(ivs)
        assert score < 0.20

    def test_falling_iv_scores_zero_expansion(self):
        ivs = [20.0 - i * 0.5 for i in range(15)]
        score, _ = _score_vol_expansion(ivs)
        assert score < 0.20

    def test_none_heavy_series_returns_zero(self):
        ivs = [None, None, None, 15.0, None]
        score, metrics = _score_vol_expansion(ivs)
        assert score == 0.0
        assert "reason" in metrics


class TestScorerVolCompression:

    def test_falling_iv_scores_high(self):
        ivs = [20.0 - i * 0.5 for i in range(16)]   # 20 → 12.5
        score, metrics = _score_vol_compression(ivs)
        assert score > 0.50
        assert metrics["iv_drop_pct"] > 0

    def test_rising_iv_scores_zero_compression(self):
        ivs = [12.0 + i * 0.5 for i in range(16)]
        score, _ = _score_vol_compression(ivs)
        assert score < 0.20

    def test_compression_and_expansion_anti_correlated(self):
        """For strongly directional IV, exp and comp scores should differ."""
        ivs_up   = [12.0 + i * 0.5 for i in range(16)]
        ivs_down = [20.0 - i * 0.5 for i in range(16)]
        s_up_exp, _ = _score_vol_expansion(ivs_up)
        s_dn_cmp, _ = _score_vol_compression(ivs_down)
        s_up_cmp, _ = _score_vol_compression(ivs_up)
        s_dn_exp, _ = _score_vol_expansion(ivs_down)
        assert s_up_exp > s_up_cmp    # expansion score > compression for rising IV
        assert s_dn_cmp > s_dn_exp    # compression score > expansion for falling IV


# ── Tests: Expiry pinning ─────────────────────────────────────────────────────

class TestScorerExpiryPinning:

    def test_classic_pinning_scores_high(self):
        """DTE=1, dist=0.3%, PCR=1.0 → strong pin."""
        score, metrics = _score_expiry_pinning(dte=1, dist_pct=0.3, pcr=1.0)
        assert score > 0.70, f"expected > 0.70, got {score}"

    def test_far_expiry_scores_zero(self):
        score, _ = _score_expiry_pinning(dte=15, dist_pct=0.3, pcr=1.0)
        assert score == 0.0

    def test_high_distance_lowers_score(self):
        score_near, _ = _score_expiry_pinning(dte=1, dist_pct=0.3, pcr=1.0)
        score_far,  _ = _score_expiry_pinning(dte=1, dist_pct=2.5, pcr=1.0)
        assert score_near > score_far

    def test_pcr_imbalance_lowers_score(self):
        score_balanced,  _ = _score_expiry_pinning(dte=2, dist_pct=0.5, pcr=1.0)
        score_imbalanced, _ = _score_expiry_pinning(dte=2, dist_pct=0.5, pcr=2.5)
        assert score_balanced > score_imbalanced

    def test_score_in_range(self):
        score, _ = _score_expiry_pinning(dte=3, dist_pct=1.0, pcr=1.1)
        assert 0.0 <= score <= 1.0


# ── Tests: Exhaustion scorer ─────────────────────────────────────────────────

class TestScorerExhaustion:

    def test_large_decelerating_dist_scores_high(self):
        """Distance at a high level AND actively declining → clear exhaustion.

        OLS slope must be negative for decel_score to be high, so the series
        must start high and decline — not start low then peak.
        """
        dists = [5.2, 5.0, 4.9, 4.7, 4.5, 4.3, 4.1, 4.0]   # clearly declining
        score, metrics = _score_exhaustion(
            dists=dists, current_dist=4.0,
            current_pcr=1.4, direction="bearish",
        )
        # dist_score ≈ 0.43, decel_score ≈ 0.85 (clearly negative slope), pcr_div ≈ 0.86
        assert score > 0.55, f"expected > 0.55, got {score}"

    def test_low_distance_scores_zero(self):
        dists = [0.5] * 8
        score, _ = _score_exhaustion(
            dists=dists, current_dist=0.5,
            current_pcr=1.0, direction="bullish",
        )
        assert score < 0.30

    def test_growing_distance_scores_low_exhaustion(self):
        """If distance is still growing, not exhaustion."""
        dists = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
        score, _ = _score_exhaustion(
            dists=dists, current_dist=5.0,
            current_pcr=0.7, direction="bearish",
        )
        # Deceleration component will be low → overall score moderate
        assert score < 0.70   # exhaustion not dominant when dist still growing

    def test_pcr_divergence_boosts_score(self):
        """Bearish direction (spot above max_pain) but high PCR (put-heavy) → exhaustion."""
        dists = [4.0] * 8
        score_div, _ = _score_exhaustion(
            dists=dists, current_dist=4.0,
            current_pcr=1.8, direction="bearish",   # PCR high = put-heavy → divergent
        )
        score_aln, _ = _score_exhaustion(
            dists=dists, current_dist=4.0,
            current_pcr=0.7, direction="bearish",   # PCR low = call-heavy → aligned
        )
        assert score_div > score_aln


# ── Tests: Momentum continuation scorer ──────────────────────────────────────

class TestScorerMomentum:

    def test_growing_aligned_dist_scores_high(self):
        """Distance growing + PCR bullish for bullish signal → momentum."""
        dists = [1.5, 1.8, 2.1, 2.5, 2.9, 3.2, 3.6, 4.0]
        score, metrics = _score_momentum_continuation(
            dists=dists, current_dist=4.0,
            current_pcr=1.4, direction="bullish",   # high PCR confirms bullish
        )
        assert score > 0.40, f"expected > 0.40, got {score}"

    def test_low_distance_scores_low_momentum(self):
        dists = [0.5] * 8
        score, _ = _score_momentum_continuation(
            dists=dists, current_dist=0.5,
            current_pcr=1.0, direction="bullish",
        )
        assert score < 0.30

    def test_exhaustion_and_momentum_anti_correlated(self):
        """When momentum is high (growing dist, aligned PCR), exhaustion should be low."""
        dists_growing  = [1.5 + i * 0.3 for i in range(8)]
        dists_flattening = [4.0] * 8

        s_mom_grow, _ = _score_momentum_continuation(
            dists_growing, current_dist=3.6, current_pcr=1.4, direction="bullish"
        )
        s_exh_grow, _ = _score_exhaustion(
            dists_growing, current_dist=3.6, current_pcr=0.8, direction="bullish"
        )
        # Growing distance → momentum > exhaustion
        assert s_mom_grow > s_exh_grow


# ── Tests: classify_snapshot ─────────────────────────────────────────────────

class TestClassifySnapshot:

    def test_expiry_pinning_dominates_near_expiry(self):
        """DTE=1, spot==max_pain → expiry_pinning should be primary."""
        window = [_snap(spot=22000, mp=22000, dist=0.0, pcr=1.0, iv=12.0, dte_days=1)]
        result = classify_snapshot(window[-1], window)
        assert result.regime == "expiry_pinning", (
            f"Expected expiry_pinning, got {result.regime} "
            f"(scores: {result.scores})"
        )

    def test_returns_regime_classification(self):
        window = self._make_window(n=15)
        result = classify_snapshot(window[-1], window)
        assert isinstance(result, RegimeClassification)
        assert result.regime in [
            "trending", "range_bound", "volatility_expansion",
            "volatility_compression", "expiry_pinning",
            "exhaustion", "momentum_continuation",
        ]

    def test_confidence_in_range(self):
        window = self._make_window(n=15)
        result = classify_snapshot(window[-1], window)
        assert 0.0 <= result.confidence <= 1.0

    def test_scores_all_present(self):
        window = self._make_window(n=10)
        result = classify_snapshot(window[-1], window)
        expected = {
            "trending", "range_bound", "volatility_expansion",
            "volatility_compression", "expiry_pinning",
            "exhaustion", "momentum_continuation",
        }
        assert set(result.scores.keys()) == expected

    def test_small_window_generates_warning(self):
        window = [_snap()]  # only 1 snap < MIN_WINDOW
        result = classify_snapshot(window[-1], window)
        assert any("small_window" in w for w in result.warnings)

    def test_secondary_regimes_listed(self):
        """A snapshot near expiry and at high distance may have secondary regimes."""
        window = self._make_window(n=IDEAL_WINDOW, dist=4.0, pcr=0.7, dte=2)
        result = classify_snapshot(window[-1], window)
        # secondary_regimes should be a list (may be empty or not)
        assert isinstance(result.secondary_regimes, list)

    def test_n_window_matches_input(self):
        window = self._make_window(n=12)
        result = classify_snapshot(window[-1], window)
        assert result.n_window == 12

    def _make_window(self, n=10, spot=22000, mp=22000,
                     pcr=1.0, iv=15.0, dte=10, dist=None):
        snaps = []
        for _ in range(n):
            d = dist if dist is not None else abs(spot - mp) / spot * 100
            snaps.append(_snap(spot=spot, mp=mp, dist=d, pcr=pcr, iv=iv, dte_days=dte))
        return snaps


# ── Tests: classify_sequence ─────────────────────────────────────────────────

class TestClassifySequence:

    def test_output_length_matches_input(self):
        snaps = [_snap() for _ in range(20)]
        results = classify_sequence(snaps, lookback=IDEAL_WINDOW)
        assert len(results) == 20

    def test_first_snap_uses_window_of_one(self):
        snaps = [_snap() for _ in range(5)]
        results = classify_sequence(snaps, lookback=IDEAL_WINDOW)
        assert results[0].n_window == 1
        assert results[4].n_window == 5

    def test_window_caps_at_lookback(self):
        snaps  = [_snap() for _ in range(30)]
        lb     = 10
        results = classify_sequence(snaps, lookback=lb)
        # After the lookback is reached, window should stay at lb
        for r in results[lb:]:
            assert r.n_window == lb

    def test_all_results_are_regime_classifications(self):
        snaps   = [_snap() for _ in range(10)]
        results = classify_sequence(snaps)
        for r in results:
            assert isinstance(r, RegimeClassification)

    def test_trending_sequence_detected(self):
        """15 bars of clear uptrend → later bars should score 'trending' high."""
        snaps = [
            _snap(spot=22000 + i * 50, mp=22000, dte_days=20)
            for i in range(20)
        ]
        results = classify_sequence(snaps, lookback=IDEAL_WINDOW)
        # Later results have full window context
        last = results[-1]
        trending_score = last.scores.get("trending", 0.0)
        assert trending_score > 0.50, (
            f"Expected trending_score > 0.50, got {trending_score}. "
            f"Primary: {last.regime}, all scores: {last.scores}"
        )


# ── Tests: infer_static_regime ────────────────────────────────────────────────

class TestInferStaticRegime:

    def test_expiry_pinning_label(self):
        regime = infer_static_regime(
            distance_pct=0.8, days_to_expiry=2,
            pcr=1.0, avg_iv=12.0, direction="bullish"
        )
        assert regime == "expiry_pinning"

    def test_high_extension_label(self):
        regime = infer_static_regime(
            distance_pct=5.0, days_to_expiry=10,
            pcr=1.0, avg_iv=15.0, direction="bullish"
        )
        assert regime == "high_extension"

    def test_moderate_extension_label(self):
        regime = infer_static_regime(
            distance_pct=2.5, days_to_expiry=10,
            pcr=1.0, avg_iv=15.0, direction="bearish"
        )
        assert regime == "moderate_extension"

    def test_pcr_divergent_bearish(self):
        """Bearish direction but high PCR (put-heavy) = divergent."""
        regime = infer_static_regime(
            distance_pct=1.0, days_to_expiry=10,
            pcr=1.5, avg_iv=15.0, direction="bearish"
        )
        assert regime == "pcr_divergent"

    def test_pcr_aligned_bullish(self):
        """Bullish direction and high PCR = aligned."""
        regime = infer_static_regime(
            distance_pct=1.0, days_to_expiry=10,
            pcr=1.4, avg_iv=15.0, direction="bullish"
        )
        assert regime == "pcr_aligned"

    def test_normal_catch_all(self):
        regime = infer_static_regime(
            distance_pct=1.0, days_to_expiry=10,
            pcr=1.0, avg_iv=15.0, direction="bullish"
        )
        assert regime == "normal"

    def test_pinning_takes_priority_over_extension(self):
        """DTE=1 and dist=0.8 → pinning even though distance is small."""
        regime = infer_static_regime(
            distance_pct=0.8, days_to_expiry=1,
            pcr=1.0, avg_iv=10.0, direction="bullish"
        )
        assert regime == "expiry_pinning"


# ── Tests: filter integration (validation service _apply_filters) ─────────────

# Load the validation service with stubs in place

_mod("app.services.max_pain_scanner_service",
     DEFAULT_FO_UNIVERSE=["NIFTY", "BANKNIFTY"])

# Replay service needs a stub too
_mod("app.services.max_pain_replay_service",
     ReplayPoint=object, load_replay=lambda **kw: [],
     HORIZONS={"15m": 15, "1h": 60, "4h": 240, "1d": 390})

_val = _load(
    "max_pain_validation_service",
    "app/services/max_pain_validation_service.py",
    alias="app.services.max_pain_validation_service",
)

_apply_filters = _val._apply_filters


@dataclass
class _FakePoint:
    """Minimal duck-typed ReplayPoint for filter testing."""
    distance_pct:    float
    days_to_expiry:  int
    avg_iv:          Optional[float]
    pcr:             float
    direction:       str

    @dataclass
    class _WS:
        ce_migrated: bool = False
        pe_migrated: bool = False
        wall_compressed: bool = False
    wall_state: object = field(default_factory=_WS)


class TestFilterIntegration:

    def _pts(self, n=20, dist=2.0, dte=10, iv=15.0, pcr=1.0, direction="bullish"):
        return [
            _FakePoint(
                distance_pct=dist, days_to_expiry=dte,
                avg_iv=iv, pcr=pcr, direction=direction,
            )
            for _ in range(n)
        ]

    def test_no_filters_returns_all(self):
        pts = self._pts(20)
        filtered, warnings = _apply_filters(pts, None, None, None)
        assert len(filtered) == 20
        assert warnings == []

    def test_expiry_proximity_near(self):
        pts_near = self._pts(10, dte=3)
        pts_far  = self._pts(10, dte=10)
        pts      = pts_near + pts_far
        filtered, _ = _apply_filters(pts, None, "near", None)
        assert len(filtered) == 10
        assert all(p.days_to_expiry <= 5 for p in filtered)

    def test_expiry_proximity_far(self):
        pts_near = self._pts(5, dte=3)
        pts_far  = self._pts(15, dte=10)
        pts      = pts_near + pts_far
        filtered, _ = _apply_filters(pts, None, "far", None)
        assert len(filtered) == 15

    def test_vol_state_high_iv(self):
        pts_high = self._pts(8,  iv=22.0)
        pts_low  = self._pts(12, iv=10.0)
        pts      = pts_high + pts_low
        filtered, _ = _apply_filters(pts, None, None, "high_iv")
        assert len(filtered) == 8
        assert all((p.avg_iv or 0) >= 20.0 for p in filtered)

    def test_regime_filter_high_distance(self):
        pts_hi  = self._pts(6,  dist=5.0)
        pts_lo  = self._pts(14, dist=1.0)
        pts     = pts_hi + pts_lo
        filtered, _ = _apply_filters(pts, "high_distance", None, None)
        assert len(filtered) == 6

    def test_unknown_regime_filter_warning(self):
        pts = self._pts(10)
        filtered, warnings = _apply_filters(pts, "nonexistent_regime", None, None)
        assert len(filtered) == 10   # unchanged
        assert any("unknown_regime_filter" in w for w in warnings)

    def test_small_result_warning(self):
        """Filtering down to < 30 pts should emit a small_filtered_sample warning."""
        pts_near = self._pts(5, dte=3)
        pts_far  = self._pts(25, dte=10)
        pts = pts_near + pts_far
        _, warnings = _apply_filters(pts, None, "near", None)
        assert any("small_filtered_sample" in w for w in warnings)

    def test_combined_filters(self):
        """expiry_proximity=near AND vol_state=high_iv → intersected."""
        pts = [
            _FakePoint(distance_pct=2.0, days_to_expiry=3,  avg_iv=22.0, pcr=1.0, direction="bullish"),
            _FakePoint(distance_pct=2.0, days_to_expiry=3,  avg_iv=10.0, pcr=1.0, direction="bullish"),
            _FakePoint(distance_pct=2.0, days_to_expiry=10, avg_iv=22.0, pcr=1.0, direction="bullish"),
            _FakePoint(distance_pct=2.0, days_to_expiry=10, avg_iv=10.0, pcr=1.0, direction="bullish"),
        ]
        filtered, _ = _apply_filters(pts, None, "near", "high_iv")
        assert len(filtered) == 1
        assert filtered[0].days_to_expiry == 3
        assert filtered[0].avg_iv == 22.0
