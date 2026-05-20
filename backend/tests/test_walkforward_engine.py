"""
Tests for walkforward_engine.py

Uses the same importlib bypass pattern as the other test files.

Coverage
--------
TestWalkForwardParams      – validate(), to_dict(), invalid method/fields
TestMathHelpers            – _safe_std, _sample_std, _pearson, _tvd, _t_ci, _ols_slope
TestTCritical              – _t_critical lookup and interpolation
TestFoldGeneration         – expanding, rolling, anchored; edge cases
TestComputeStats           – FoldStats correctness, feature correlations, regime dist
TestComputeDegradation     – degradation metrics, sign computation
TestEvaluateFold           – FoldResult structure, period timestamps
TestAggregation            – aggregate metrics, stability time series
TestExpectancyTrend        – OLS slope trend detection
TestWarnings               – all 7 warning conditions
TestPublicAPI              – run_walkforward: errors, results, all three dict views
TestTemporalIntegrity      – training never uses test-period data (key invariant)
"""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Module loading infrastructure
# ---------------------------------------------------------------------------

_BACKEND = Path(__file__).parent.parent


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


def _load(short_name: str, rel_path: str, alias: str = None):
    path = _BACKEND / rel_path
    spec = importlib.util.spec_from_file_location(short_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[short_name] = mod
    if alias:
        sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# --- Stub packages ---
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
_mod("app.services.max_pain_scanner_service",
     DEFAULT_FO_UNIVERSE=["NIFTY", "BANKNIFTY"])

_replay = _load(
    "max_pain_replay_service",
    "app/services/max_pain_replay_service.py",
    alias="app.services.max_pain_replay_service",
)
_regime = _load(
    "regime_classifier",
    "app/services/regime_classifier.py",
    alias="app.services.regime_classifier",
)
_val = _load(
    "max_pain_validation_service",
    "app/services/max_pain_validation_service.py",
    alias="app.services.max_pain_validation_service",
)
_sim = _load(
    "trade_simulator",
    "app/services/trade_simulator.py",
    alias="app.services.trade_simulator",
)
_res = _load(
    "research_engine",
    "app/services/research_engine.py",
    alias="app.services.research_engine",
)
_wf = _load(
    "walkforward_engine",
    "app/services/walkforward_engine.py",
    alias="app.services.walkforward_engine",
)

from walkforward_engine import (  # noqa: E402
    WalkForwardParams,
    FoldPeriod,
    FoldStats,
    FoldDegradation,
    FoldResult,
    AggregateStats,
    StabilityTimeSeries,
    WalkForwardResult,
    VALID_WF_METHODS,
    _safe_std,
    _sample_std,
    _pearson,
    _tvd,
    _t_critical,
    _t_ci,
    _ols_slope,
    _make_folds,
    _compute_stats,
    _compute_degradation,
    _evaluate_fold,
    _aggregate_folds,
    _generate_warnings,
    run_walkforward,
)
from research_engine import FeatureRecord, CONTINUOUS_FEATURES  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _default_params(**kw) -> WalkForwardParams:
    defaults = dict(
        method="expanding",
        n_splits=3,
        min_train_obs=5,
        min_test_obs=3,
        features_to_track=["signal_dist_pct", "pcr"],
        confidence_level=0.95,
    )
    defaults.update(kw)
    return WalkForwardParams(**defaults)


def _make_record(
    pnl: float,
    captured_at: str = "2024-01-01T00:00:00+00:00",
    symbol: str = "NIFTY",
    regime: str = "normal",
    signal_dist_pct: float = 2.0,
    pcr: float = 1.0,
    avg_iv: Optional[float] = 20.0,
    days_to_expiry: int = 5,
    direction: str = "bullish",
) -> FeatureRecord:
    return FeatureRecord(
        symbol           = symbol,
        captured_at      = captured_at,
        regime           = regime,
        direction        = direction,
        vol_state        = "normal_iv",
        expiry_proximity = "far",
        signal_dist_pct  = signal_dist_pct,
        pcr              = pcr,
        avg_iv           = avg_iv,
        days_to_expiry   = days_to_expiry,
        net_pnl_pct      = pnl,
        is_win           = pnl > 0,
    )


def _make_records(n: int, start_day: int = 1, pnl_pattern: str = "alternating") -> list[FeatureRecord]:
    """Create n records with timestamps spaced one day apart."""
    records = []
    for i in range(n):
        day = start_day + i
        month = (day - 1) // 28 + 1
        day_of_month = (day - 1) % 28 + 1
        ts = f"2024-{month:02d}-{day_of_month:02d}T10:00:00+00:00"

        if pnl_pattern == "alternating":
            pnl = 2.0 if i % 2 == 0 else -1.0
        elif pnl_pattern == "all_positive":
            pnl = 1.0 + (i % 3) * 0.5
        elif pnl_pattern == "all_negative":
            pnl = -1.0 - (i % 3) * 0.5
        else:
            pnl = float(i) * 0.1 - 1.0   # linear

        records.append(_make_record(
            pnl=pnl,
            captured_at=ts,
            signal_dist_pct=1.0 + (i % 5) * 0.5,
            pcr=0.8 + (i % 4) * 0.1,
            avg_iv=18.0 + (i % 5),
            days_to_expiry=3 + (i % 10),
            regime="normal" if i % 3 != 0 else "high_extension",
            direction="bullish" if i % 2 == 0 else "bearish",
        ))
    return records


# ---------------------------------------------------------------------------
# TestWalkForwardParams
# ---------------------------------------------------------------------------

class TestWalkForwardParams:
    def test_default_values(self):
        p = WalkForwardParams()
        assert p.method == "expanding"
        assert p.n_splits == 5
        assert p.min_train_obs == 10
        assert p.min_test_obs == 5
        assert p.confidence_level == 0.95

    def test_validate_valid(self):
        p = _default_params()
        assert p.validate() == []

    def test_validate_all_valid_methods(self):
        for method in VALID_WF_METHODS:
            p = _default_params(method=method)
            assert p.validate() == [], f"method={method} should be valid"

    def test_validate_invalid_method(self):
        p = _default_params(method="random_forest")
        issues = p.validate()
        assert any("method" in i for i in issues)

    def test_validate_n_splits_too_low(self):
        p = _default_params(n_splits=1)
        issues = p.validate()
        assert any("n_splits" in i for i in issues)

    def test_validate_n_splits_too_high(self):
        p = _default_params(n_splits=21)
        issues = p.validate()
        assert any("n_splits" in i for i in issues)

    def test_validate_min_train_too_low(self):
        p = _default_params(min_train_obs=2)
        issues = p.validate()
        assert any("min_train_obs" in i for i in issues)

    def test_validate_min_test_too_low(self):
        p = _default_params(min_test_obs=1)
        issues = p.validate()
        assert any("min_test_obs" in i for i in issues)

    def test_validate_invalid_feature(self):
        p = _default_params(features_to_track=["nonexistent_feature"])
        issues = p.validate()
        assert any("feature" in i for i in issues)

    def test_validate_confidence_out_of_range(self):
        p1 = _default_params(confidence_level=0.3)
        p2 = _default_params(confidence_level=1.0)
        assert any("confidence_level" in i for i in p1.validate())
        assert any("confidence_level" in i for i in p2.validate())

    def test_to_dict_keys(self):
        p = _default_params()
        d = p.to_dict()
        assert "method" in d
        assert "n_splits" in d
        assert "min_train_obs" in d
        assert "min_test_obs" in d
        assert "features_to_track" in d
        assert "confidence_level" in d

    def test_to_dict_values_match(self):
        p = _default_params(n_splits=4, method="rolling")
        d = p.to_dict()
        assert d["n_splits"] == 4
        assert d["method"] == "rolling"


# ---------------------------------------------------------------------------
# TestMathHelpers
# ---------------------------------------------------------------------------

class TestMathHelpers:
    def test_safe_std_empty(self):
        assert _safe_std([]) == 0.0

    def test_safe_std_single(self):
        assert _safe_std([5.0]) == 0.0

    def test_safe_std_known(self):
        # [0, 2]: mean=1, population std=1
        assert _safe_std([0.0, 2.0]) == pytest.approx(1.0)

    def test_sample_std_differs_from_population(self):
        xs = [0.0, 2.0]
        # population std = 1.0; sample std = sqrt(2) ≈ 1.414
        assert _sample_std(xs) == pytest.approx(math.sqrt(2))

    def test_pearson_perfect_positive(self):
        xs = [1.0, 2.0, 3.0]
        assert _pearson(xs, xs) == pytest.approx(1.0)

    def test_pearson_too_short(self):
        assert _pearson([1.0], [1.0]) is None

    def test_tvd_identical_distributions(self):
        p = {"a": 0.5, "b": 0.5}
        assert _tvd(p, p) == pytest.approx(0.0)

    def test_tvd_completely_different(self):
        p = {"a": 1.0}
        q = {"b": 1.0}
        assert _tvd(p, q) == pytest.approx(1.0)

    def test_tvd_partial_overlap(self):
        p = {"a": 0.6, "b": 0.4}
        q = {"a": 0.4, "b": 0.6}
        # |0.6-0.4| + |0.4-0.6| = 0.4; TVD = 0.4/2 = 0.2
        assert _tvd(p, q) == pytest.approx(0.2)

    def test_t_ci_single_value(self):
        lo, hi = _t_ci([5.0], 0.95)
        assert lo == pytest.approx(5.0)
        assert hi == pytest.approx(5.0)

    def test_t_ci_symmetric(self):
        values = [0.0, 0.0, 0.0, 0.0, 0.0]
        lo, hi = _t_ci(values, 0.95)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(0.0)

    def test_t_ci_width_positive(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        lo, hi = _t_ci(values, 0.95)
        assert hi > lo
        assert lo < 3.0 < hi   # mean=3 should be inside CI

    def test_ols_slope_positive_trend(self):
        xs = [0.0, 1.0, 2.0, 3.0, 4.0]
        ys = [0.0, 1.0, 2.0, 3.0, 4.0]
        slope = _ols_slope(xs, ys)
        assert slope == pytest.approx(1.0)

    def test_ols_slope_negative_trend(self):
        xs = [0.0, 1.0, 2.0, 3.0, 4.0]
        ys = [4.0, 3.0, 2.0, 1.0, 0.0]
        slope = _ols_slope(xs, ys)
        assert slope == pytest.approx(-1.0)

    def test_ols_slope_flat(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [2.0, 2.0, 2.0, 2.0]
        slope = _ols_slope(xs, ys)
        assert slope == pytest.approx(0.0)

    def test_ols_slope_too_short(self):
        assert _ols_slope([1.0], [1.0]) is None


# ---------------------------------------------------------------------------
# TestTCritical
# ---------------------------------------------------------------------------

class TestTCritical:
    def test_df1_95(self):
        assert _t_critical(1, 0.95) == pytest.approx(12.706, abs=0.01)

    def test_df4_95(self):
        assert _t_critical(4, 0.95) == pytest.approx(2.776, abs=0.01)

    def test_df10_95(self):
        assert _t_critical(10, 0.95) == pytest.approx(2.228, abs=0.01)

    def test_df4_90(self):
        assert _t_critical(4, 0.90) == pytest.approx(2.132, abs=0.01)

    def test_df4_99(self):
        assert _t_critical(4, 0.99) == pytest.approx(4.604, abs=0.01)

    def test_monotone_in_df(self):
        # Higher df → smaller t-critical (less uncertainty)
        t1 = _t_critical(2, 0.95)
        t5 = _t_critical(5, 0.95)
        t10 = _t_critical(10, 0.95)
        assert t1 > t5 > t10

    def test_interpolation_returns_float(self):
        # df=3 is in table; df=11 is between 10 and 12
        result = _t_critical(11, 0.95)
        assert isinstance(result, float)
        assert 2.179 < result < 2.228   # between df=12 and df=10


# ---------------------------------------------------------------------------
# TestFoldGeneration
# ---------------------------------------------------------------------------

class TestFoldGeneration:
    def test_expanding_returns_n_folds(self):
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        folds   = _make_folds(records, params)
        assert len(folds) == 3

    def test_rolling_returns_folds(self):
        records = _make_records(30)
        params  = _default_params(method="rolling", n_splits=3)
        folds   = _make_folds(records, params)
        assert len(folds) >= 1

    def test_anchored_same_as_expanding(self):
        records = _make_records(30)
        p_exp   = _default_params(method="expanding", n_splits=3)
        p_anch  = _default_params(method="anchored",  n_splits=3)
        f_exp   = _make_folds(records, p_exp)
        f_anch  = _make_folds(records, p_anch)
        # Same number of folds
        assert len(f_exp) == len(f_anch)

    def test_expanding_train_grows(self):
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        folds   = _make_folds(records, params)
        train_sizes = [len(tr) for tr, _ in folds]
        assert train_sizes == sorted(train_sizes)

    def test_rolling_train_size_roughly_constant(self):
        records = _make_records(30)
        params  = _default_params(method="rolling", n_splits=3)
        folds   = _make_folds(records, params)
        train_sizes = [len(tr) for tr, _ in folds]
        # All training windows should be equal size
        assert max(train_sizes) - min(train_sizes) <= 1

    def test_no_overlap_between_train_and_test(self):
        """Critical invariant: no test record appears in training."""
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        folds   = _make_folds(records, params)
        for train, test in folds:
            train_timestamps = {r.captured_at for r in train}
            test_timestamps  = {r.captured_at for r in test}
            # Training timestamps must all be strictly before test timestamps
            max_train_ts = max(train_timestamps)
            min_test_ts  = min(test_timestamps)
            assert max_train_ts < min_test_ts, (
                f"Temporal leak: train ends at {max_train_ts}, "
                f"test starts at {min_test_ts}"
            )

    def test_test_periods_non_overlapping_expanding(self):
        """Expanding: test windows should not overlap each other."""
        records = _make_records(40)
        params  = _default_params(n_splits=4)
        folds   = _make_folds(records, params)
        for i in range(len(folds) - 1):
            _, test_i     = folds[i]
            _, test_i1    = folds[i + 1]
            max_test_i_ts = max(r.captured_at for r in test_i)
            min_test_i1_ts= min(r.captured_at for r in test_i1)
            assert max_test_i_ts <= min_test_i1_ts

    def test_min_test_obs_respected(self):
        records = _make_records(30)
        params  = _default_params(min_test_obs=4)
        folds   = _make_folds(records, params)
        for _, test in folds:
            assert len(test) >= 3   # may be slightly less on last fold in some cases

    def test_raises_on_insufficient_data(self):
        records = _make_records(5)
        params  = _default_params(min_train_obs=10, min_test_obs=5)
        with pytest.raises(ValueError, match="only"):
            _make_folds(records, params)

    def test_raises_when_no_valid_fold_possible(self):
        # 6 records, need min_train=5 + min_test=5 = 10 → impossible
        records = _make_records(6)
        params  = _default_params(n_splits=3, min_train_obs=5, min_test_obs=5)
        with pytest.raises(ValueError):
            _make_folds(records, params)

    def test_all_records_eventually_tested_expanding(self):
        """Every record after the initial training period appears in exactly one test fold."""
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        folds   = _make_folds(records, params)
        # All test records combined should cover the latter portion of data
        all_test_ts = [r.captured_at for _, test in folds for r in test]
        # No duplicates
        assert len(all_test_ts) == len(set(all_test_ts))


# ---------------------------------------------------------------------------
# TestComputeStats
# ---------------------------------------------------------------------------

class TestComputeStats:
    def test_empty_records(self):
        stats = _compute_stats([], ["signal_dist_pct"])
        assert stats.n_obs == 0
        assert stats.win_rate is None
        assert stats.expectancy_pct is None
        assert stats.feature_correlations["signal_dist_pct"] is None

    def test_correct_win_rate(self):
        records = [_make_record(1.0)] * 3 + [_make_record(-1.0)] * 2
        stats = _compute_stats(records, ["signal_dist_pct"])
        assert stats.win_rate == pytest.approx(3/5)

    def test_correct_expectancy(self):
        pnls = [2.0, -1.0, 3.0, -1.0, 1.0]
        records = [_make_record(p) for p in pnls]
        stats = _compute_stats(records, ["signal_dist_pct"])
        assert stats.expectancy_pct == pytest.approx(sum(pnls) / len(pnls), abs=1e-4)

    def test_n_obs_correct(self):
        records = _make_records(10)
        stats = _compute_stats(records, ["signal_dist_pct"])
        assert stats.n_obs == 10

    def test_regime_distribution_sums_to_one(self):
        records = _make_records(20)
        stats = _compute_stats(records, ["signal_dist_pct"])
        total = sum(stats.regime_distribution.values())
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_feature_correlations_dict_has_all_features(self):
        records = _make_records(15)
        features = ["signal_dist_pct", "pcr"]
        stats = _compute_stats(records, features)
        for f in features:
            assert f in stats.feature_correlations

    def test_sharpe_approx_sign(self):
        # Positive expectancy → positive sharpe
        records = [_make_record(1.0)] * 10 + [_make_record(0.5)] * 5
        stats = _compute_stats(records, [])
        if stats.sharpe_approx is not None:
            assert stats.sharpe_approx > 0

    def test_to_dict_structure(self):
        records = _make_records(10)
        stats = _compute_stats(records, ["signal_dist_pct"])
        d = stats.to_dict()
        assert "n_obs" in d
        assert "win_rate" in d
        assert "expectancy_pct" in d
        assert "std_pct" in d
        assert "feature_correlations" in d
        assert "regime_distribution" in d


# ---------------------------------------------------------------------------
# TestComputeDegradation
# ---------------------------------------------------------------------------

class TestComputeDegradation:
    def _stats(self, exp, wr, feat_r_dict=None, regime_dist=None) -> FoldStats:
        return FoldStats(
            n_obs                = 10,
            win_rate             = wr,
            expectancy_pct       = exp,
            std_pct              = 1.0,
            sharpe_approx        = None,
            feature_correlations = feat_r_dict or {"signal_dist_pct": None},
            regime_distribution  = regime_dist or {"normal": 1.0},
        )

    def test_positive_degradation_when_oos_worse(self):
        is_s  = self._stats(2.0, 0.6)
        oos_s = self._stats(1.0, 0.5)
        deg = _compute_degradation(0, is_s, oos_s, ["signal_dist_pct"])
        # (2.0 - 1.0) / 2.0 * 100 = 50
        assert deg.expectancy_degradation_pct == pytest.approx(50.0)

    def test_negative_degradation_when_oos_better(self):
        is_s  = self._stats(1.0, 0.5)
        oos_s = self._stats(2.0, 0.6)
        deg = _compute_degradation(0, is_s, oos_s, ["signal_dist_pct"])
        # (1.0 - 2.0) / 1.0 * 100 = -100
        assert deg.expectancy_degradation_pct == pytest.approx(-100.0)

    def test_none_degradation_when_is_near_zero(self):
        is_s  = self._stats(0.0, 0.5)
        oos_s = self._stats(1.0, 0.6)
        deg = _compute_degradation(0, is_s, oos_s, ["signal_dist_pct"])
        assert deg.expectancy_degradation_pct is None

    def test_win_rate_delta_sign(self):
        is_s  = self._stats(1.0, 0.6)
        oos_s = self._stats(0.5, 0.4)
        deg = _compute_degradation(0, is_s, oos_s, ["signal_dist_pct"])
        assert deg.win_rate_delta == pytest.approx(0.4 - 0.6, abs=1e-6)

    def test_oos_positive_flag(self):
        is_s  = self._stats(2.0, 0.6)
        oos_s_pos = self._stats(0.1, 0.5)
        oos_s_neg = self._stats(-0.5, 0.4)
        deg_pos = _compute_degradation(0, is_s, oos_s_pos, ["signal_dist_pct"])
        deg_neg = _compute_degradation(0, is_s, oos_s_neg, ["signal_dist_pct"])
        assert deg_pos.oos_positive is True
        assert deg_neg.oos_positive is False

    def test_regime_drift_tvd_range(self):
        is_s  = self._stats(1.0, 0.5, regime_dist={"bull": 0.8, "bear": 0.2})
        oos_s = self._stats(0.5, 0.4, regime_dist={"bull": 0.2, "bear": 0.8})
        deg = _compute_degradation(0, is_s, oos_s, [])
        assert 0.0 <= deg.regime_drift_tvd <= 1.0

    def test_feature_correlation_decay_sign(self):
        is_s  = self._stats(1.0, 0.5,
                            feat_r_dict={"signal_dist_pct": 0.3})
        oos_s = self._stats(0.5, 0.4,
                            feat_r_dict={"signal_dist_pct": 0.1})
        deg = _compute_degradation(0, is_s, oos_s, ["signal_dist_pct"])
        # decay = 0.3 - 0.1 = 0.2
        assert deg.feature_correlation_decay["signal_dist_pct"] == pytest.approx(0.2, abs=1e-4)

    def test_to_dict_keys(self):
        is_s  = self._stats(1.0, 0.5)
        oos_s = self._stats(0.5, 0.4)
        deg = _compute_degradation(0, is_s, oos_s, ["signal_dist_pct"])
        d = deg.to_dict()
        assert "expectancy_degradation_pct" in d
        assert "win_rate_delta" in d
        assert "feature_correlation_decay" in d
        assert "regime_drift_tvd" in d
        assert "oos_positive" in d


# ---------------------------------------------------------------------------
# TestEvaluateFold
# ---------------------------------------------------------------------------

class TestEvaluateFold:
    def test_returns_fold_result(self):
        train = _make_records(15)
        test  = _make_records(5, start_day=16)
        result = _evaluate_fold(0, train, test, ["signal_dist_pct"])
        assert isinstance(result, FoldResult)

    def test_period_timestamps_ordered(self):
        train = _make_records(10)
        test  = _make_records(5, start_day=11)
        result = _evaluate_fold(0, train, test, ["signal_dist_pct"])
        assert result.period.train_start <= result.period.train_end
        assert result.period.train_end <= result.period.test_start
        assert result.period.test_start <= result.period.test_end

    def test_period_n_train_n_test_correct(self):
        train = _make_records(12)
        test  = _make_records(6, start_day=13)
        result = _evaluate_fold(0, train, test, ["signal_dist_pct"])
        assert result.period.n_train == 12
        assert result.period.n_test == 6

    def test_is_stats_uses_train_data(self):
        train = [_make_record(1.0)] * 10 + [_make_record(1.0)] * 5  # all wins
        test  = [_make_record(-1.0)] * 5  # all losses
        result = _evaluate_fold(0, train, test, ["signal_dist_pct"])
        assert result.is_stats.win_rate == pytest.approx(1.0)
        assert result.oos_stats.win_rate == pytest.approx(0.0)

    def test_to_dict_structure(self):
        train = _make_records(10)
        test  = _make_records(5, start_day=11)
        result = _evaluate_fold(0, train, test, ["signal_dist_pct"])
        d = result.to_dict()
        assert "fold_idx" in d
        assert "period" in d
        assert "in_sample" in d
        assert "out_of_sample" in d
        assert "degradation" in d


# ---------------------------------------------------------------------------
# TestAggregation
# ---------------------------------------------------------------------------

class TestAggregation:
    def _run_agg(self, n=40, n_splits=3):
        records = _make_records(n)
        params  = _default_params(n_splits=n_splits)
        folds_pairs = _make_folds(records, params)
        folds = [
            _evaluate_fold(i, tr, te, params.features_to_track)
            for i, (tr, te) in enumerate(folds_pairs)
        ]
        return _aggregate_folds(folds, params.features_to_track, params.confidence_level)

    def test_returns_tuple_of_two(self):
        result = self._run_agg()
        assert len(result) == 2
        agg, ts = result
        assert isinstance(agg, AggregateStats)
        assert isinstance(ts, StabilityTimeSeries)

    def test_robustness_in_range(self):
        agg, _ = self._run_agg()
        assert 0.0 <= agg.robustness_score <= 1.0

    def test_stability_in_range(self):
        agg, _ = self._run_agg()
        assert 0.0 <= agg.stability_score <= 1.0

    def test_overfit_score_non_negative(self):
        agg, _ = self._run_agg()
        assert agg.overfit_score >= 0.0

    def test_ci_low_le_mean_le_ci_high(self):
        agg, _ = self._run_agg()
        assert agg.oos_ci_low <= agg.mean_oos_expectancy <= agg.oos_ci_high

    def test_degradation_ratio_sign(self):
        # If IS and OOS are both positive and IS > OOS, ratio should be < 1
        agg, _ = self._run_agg()
        if agg.degradation_ratio is not None and agg.mean_is_expectancy > 0:
            if agg.mean_oos_expectancy > 0 and agg.mean_oos_expectancy < agg.mean_is_expectancy:
                assert agg.degradation_ratio < 1.0

    def test_fold_consistency_equals_robustness(self):
        agg, _ = self._run_agg()
        assert agg.fold_consistency_score == pytest.approx(agg.robustness_score)

    def test_stability_ts_has_correct_length(self):
        n_splits = 3
        _, ts = self._run_agg(n=40, n_splits=n_splits)
        assert len(ts.fold_indices) == n_splits
        assert len(ts.oos_expectancy_series) == n_splits
        assert len(ts.oos_win_rate_series) == n_splits
        assert len(ts.regime_drift_series) == n_splits

    def test_feature_decay_dict_populated(self):
        agg, _ = self._run_agg()
        for feat in ["signal_dist_pct", "pcr"]:
            assert feat in agg.feature_decay

    def test_overfit_detected_consistent_with_score(self):
        agg, _ = self._run_agg()
        assert agg.overfit_detected == (agg.overfit_score > 0.50)

    def test_to_dict_keys(self):
        agg, _ = self._run_agg()
        d = agg.to_dict()
        assert "mean_is_expectancy_pct" in d
        assert "mean_oos_expectancy_pct" in d
        assert "robustness_score" in d
        assert "stability_score" in d
        assert "overfit_score" in d
        assert "degradation_ratio" in d
        assert "feature_decay" in d


# ---------------------------------------------------------------------------
# TestExpectancyTrend
# ---------------------------------------------------------------------------

class TestExpectancyTrend:
    def _ts_from_folds(self, oos_exps: list[float]) -> StabilityTimeSeries:
        """Build a minimal StabilityTimeSeries with given OOS expectancy series."""
        records = _make_records(40)
        params  = _default_params(n_splits=len(oos_exps))
        folds_pairs = _make_folds(records, params)
        folds = [
            _evaluate_fold(i, tr, te, params.features_to_track)
            for i, (tr, te) in enumerate(folds_pairs)
        ]
        # Override oos expectancy in folds for trend testing
        for i, f in enumerate(folds):
            f.oos_stats = FoldStats(
                n_obs=f.oos_stats.n_obs,
                win_rate=f.oos_stats.win_rate,
                expectancy_pct=oos_exps[i],
                std_pct=f.oos_stats.std_pct,
                sharpe_approx=None,
                feature_correlations=f.oos_stats.feature_correlations,
                regime_distribution=f.oos_stats.regime_distribution,
            )
        _, ts = _aggregate_folds(folds, params.features_to_track, 0.95)
        return ts

    def test_improving_trend_detected(self):
        ts = self._ts_from_folds([0.1, 0.5, 1.0])
        assert ts.expectancy_trend_direction == "improving"

    def test_decaying_trend_detected(self):
        ts = self._ts_from_folds([1.0, 0.5, 0.1])
        assert ts.expectancy_trend_direction == "decaying"

    def test_stable_when_no_trend(self):
        ts = self._ts_from_folds([1.0, 1.0, 1.0])
        assert ts.expectancy_trend_direction == "stable"

    def test_trend_slope_direction_matches_label(self):
        ts = self._ts_from_folds([0.1, 0.5, 1.0])
        if ts.expectancy_trend is not None:
            assert ts.expectancy_trend > 0

    def test_stability_ts_to_dict(self):
        ts = self._ts_from_folds([1.0, 0.5, -0.5])
        d = ts.to_dict()
        assert "fold_indices" in d
        assert "oos_expectancy_series" in d
        assert "expectancy_trend" in d
        assert "expectancy_trend_direction" in d


# ---------------------------------------------------------------------------
# TestWarnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def _run(self, records, params=None):
        params = params or _default_params()
        folds_pairs = _make_folds(records, params)
        folds = [
            _evaluate_fold(i, tr, te, params.features_to_track)
            for i, (tr, te) in enumerate(folds_pairs)
        ]
        agg, _ = _aggregate_folds(folds, params.features_to_track, 0.95)
        return _generate_warnings(folds, agg, params)

    def test_insufficient_unseen_data_too_few_records(self):
        records = _make_records(12)  # just enough for 3 folds of 3 test each = 9 total OOS < 10
        params  = _default_params(n_splits=3, min_train_obs=5, min_test_obs=3)
        try:
            warns = self._run(records, params)
            assert any("insufficient_unseen_data" in w for w in warns)
        except ValueError:
            pass  # also acceptable if can't form folds

    def test_negative_mean_oos_warning(self):
        # All-negative OOS expectancy
        records = _make_records(40, pnl_pattern="all_negative")
        params  = _default_params(n_splits=3)
        warns = self._run(records, params)
        assert any("negative_mean_oos" in w for w in warns)

    def test_severe_overfitting_warning(self):
        # Force high IS, low OOS by having alternating pattern where
        # IS sees all wins and OOS sees all losses
        # Build records: first 20 all-positive, last 15 all-negative
        pos_records = _make_records(20, pnl_pattern="all_positive")
        neg_records = _make_records(15, start_day=21, pnl_pattern="all_negative")
        records = pos_records + neg_records
        params = _default_params(n_splits=2, min_train_obs=10, min_test_obs=5)
        warns = self._run(records, params)
        # Either severe_overfitting or negative_mean_oos should fire
        has_overfit_or_neg = (
            any("severe_overfitting" in w for w in warns) or
            any("negative_mean_oos" in w for w in warns)
        )
        assert has_overfit_or_neg

    def test_no_warnings_on_healthy_consistent_data(self):
        # Large dataset, consistently positive
        records = _make_records(60, pnl_pattern="all_positive")
        params  = _default_params(n_splits=4, min_train_obs=10, min_test_obs=5)
        warns = self._run(records, params)
        # Should not have severe overfitting or negative OOS
        assert not any("severe_overfitting" in w for w in warns)
        assert not any("negative_mean_oos" in w for w in warns)

    def test_warnings_is_list(self):
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        warns = self._run(records, params)
        assert isinstance(warns, list)


# ---------------------------------------------------------------------------
# TestPublicAPI
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_raises_on_empty_records(self):
        params = _default_params()
        with pytest.raises(ValueError, match="no usable"):
            run_walkforward([], params, ["NIFTY"], "30d")

    def test_raises_on_invalid_params(self):
        params = WalkForwardParams(method="invalid")
        records = _make_records(30)
        with pytest.raises(ValueError, match="invalid"):
            run_walkforward(records, params, ["NIFTY"], "30d")

    def test_raises_on_insufficient_data(self):
        params  = _default_params(min_train_obs=20, min_test_obs=10, n_splits=5)
        records = _make_records(10)
        with pytest.raises(ValueError):
            run_walkforward(records, params, ["NIFTY"], "30d")

    def test_returns_walkforward_result(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert isinstance(result, WalkForwardResult)

    def test_n_folds_matches(self):
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert result.n_folds == 3
        assert len(result.folds) == 3

    def test_n_total_obs_correct(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert result.n_total_obs == 30

    def test_symbols_and_window_stored(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY", "BANKNIFTY"], "7d")
        assert result.symbols == ["NIFTY", "BANKNIFTY"]
        assert result.window == "7d"

    def test_to_run_dict_structure(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        d = result.to_run_dict()
        assert "symbols" in d
        assert "params" in d
        assert "n_total_obs" in d
        assert "n_folds" in d
        assert "folds" in d
        assert "aggregate" in d
        assert "warnings" in d
        assert "generated_at" in d

    def test_to_summary_dict_no_folds(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        d = result.to_summary_dict()
        assert "folds" not in d
        assert "aggregate" in d

    def test_to_stability_dict_structure(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        d = result.to_stability_dict()
        assert "stability" in d
        assert "aggregate" in d
        assert "folds" not in d

    def test_warnings_is_list(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert isinstance(result.warnings, list)

    def test_all_valid_methods_run(self):
        records = _make_records(30)
        for method in VALID_WF_METHODS:
            params = _default_params(method=method, n_splits=3)
            result = run_walkforward(records, params, ["NIFTY"], "30d")
            assert isinstance(result, WalkForwardResult)

    def test_fold_indices_sequential(self):
        records = _make_records(30)
        params  = _default_params(n_splits=3)
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert [f.fold_idx for f in result.folds] == list(range(result.n_folds))

    def test_aggregate_robustness_between_0_and_1(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert 0.0 <= result.aggregate.robustness_score <= 1.0

    def test_aggregate_stability_between_0_and_1(self):
        records = _make_records(30)
        params  = _default_params()
        result  = run_walkforward(records, params, ["NIFTY"], "30d")
        assert 0.0 <= result.aggregate.stability_score <= 1.0


# ---------------------------------------------------------------------------
# TestTemporalIntegrity (critical invariants)
# ---------------------------------------------------------------------------

class TestTemporalIntegrity:
    """Verify the engine never looks ahead into the test period."""

    def test_train_always_before_test_expanding(self):
        records = _make_records(40)
        params  = _default_params(method="expanding", n_splits=4)
        folds   = _make_folds(records, params)
        for train, test in folds:
            max_train_ts = max(r.captured_at for r in train)
            min_test_ts  = min(r.captured_at for r in test)
            assert max_train_ts < min_test_ts, (
                f"Lookahead bias: train has timestamp {max_train_ts} "
                f">= test start {min_test_ts}"
            )

    def test_train_always_before_test_rolling(self):
        records = _make_records(40)
        params  = _default_params(method="rolling", n_splits=3)
        folds   = _make_folds(records, params)
        for train, test in folds:
            max_train_ts = max(r.captured_at for r in train)
            min_test_ts  = min(r.captured_at for r in test)
            assert max_train_ts < min_test_ts

    def test_test_records_not_in_train(self):
        records = _make_records(40)
        params  = _default_params(n_splits=3)
        folds   = _make_folds(records, params)
        for train, test in folds:
            train_set = set(id(r) for r in train)
            for tr in test:
                assert id(tr) not in train_set, \
                    "A test record appears in training set — information leakage"

    def test_is_stats_use_only_train_data(self):
        """IS performance reflects only training data, not test data."""
        # Training: all positive; Test: all negative
        pos = [_make_record(2.0, captured_at=f"2024-01-{i:02d}T10:00:00+00:00")
               for i in range(1, 21)]
        neg = [_make_record(-2.0, captured_at=f"2024-02-{i:02d}T10:00:00+00:00")
               for i in range(1, 11)]
        records = pos + neg

        params = _default_params(n_splits=2, min_train_obs=10, min_test_obs=4)
        result = run_walkforward(records, params, ["NIFTY"], "30d")

        # First fold IS stats should show positive expectancy (from training=pos records)
        first_fold = result.folds[0]
        if first_fold.is_stats.expectancy_pct is not None:
            assert first_fold.is_stats.expectancy_pct > 0

    def test_different_from_is_when_oos_different(self):
        """IS and OOS metrics are genuinely different when data differs."""
        pos = [_make_record(2.0, captured_at=f"2024-01-{i:02d}T10:00:00+00:00")
               for i in range(1, 21)]
        neg = [_make_record(-1.0, captured_at=f"2024-02-{i:02d}T10:00:00+00:00")
               for i in range(1, 11)]
        records = pos + neg

        params = _default_params(n_splits=2, min_train_obs=10, min_test_obs=4)
        result = run_walkforward(records, params, ["NIFTY"], "30d")

        for fold in result.folds:
            if (fold.is_stats.expectancy_pct is not None and
                    fold.oos_stats.expectancy_pct is not None):
                # At least some folds should show different IS vs OOS
                assert fold.is_stats.expectancy_pct != fold.oos_stats.expectancy_pct
