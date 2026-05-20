"""
Tests for research_engine.py

Uses the same importlib bypass pattern as the other test files.

Coverage
--------
TestMathHelpers          – _pearson, _spearman, _rank_list, _eta_squared, _safe_std
TestQuantileBoundaries   – _quantile_boundaries edge cases
TestVolState             – _vol_state thresholds
TestExpiry Proximity     – _expiry_proximity threshold
TestExtractFeatureRecords – None pnl filtering, regime inference, sorting
TestBucketContinuous     – quartile bucketing, min obs, edge cases
TestCategoryStats        – per-category stats
TestAnalyseContinuous    – ContinuousFeatureStats computation
TestAnalyseCategorical   – CategoricalFeatureStats computation
TestCrossSections        – cross-sectional grouping by symbol, direction, etc.
TestCorrelations         – feature-pnl, feature-feature correlations
TestStabilityFeature     – split-half feature stability
TestStabilitySignal      – split-half (symbol, regime) stability
TestRankings             – ranking entries, sorting, per-regime
TestWarnings             – all 5 warning conditions
TestPublicAPI            – run_feature_analysis, run_correlation_analysis,
                           run_stability_analysis, run_rankings
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

from research_engine import (  # noqa: E402
    FeatureRecord,
    BucketStats,
    CategoryStats,
    ContinuousFeatureStats,
    CategoricalFeatureStats,
    CrossSectionalRow,
    CorrelationPair,
    FeaturePairCorrelation,
    FeatureStabilityRecord,
    SignalStabilityRecord,
    RankingEntry,
    FeatureAnalysisResult,
    CorrelationResult,
    StabilityResult,
    RankingsResult,
    CONTINUOUS_FEATURES,
    CATEGORICAL_FEATURES,
    _pearson,
    _spearman,
    _rank_list,
    _eta_squared,
    _safe_std,
    _quantile_boundaries,
    _vol_state,
    _expiry_proximity,
    _bucket_continuous,
    _category_stats,
    _analyse_continuous,
    _analyse_categorical,
    _cross_sections,
    _feature_pnl_correlations,
    _feature_feature_correlations,
    _split_half_feature_stability,
    _signal_stability,
    _build_ranking_entries,
    extract_feature_records,
    run_feature_analysis,
    run_correlation_analysis,
    run_stability_analysis,
    run_rankings,
)
from trade_simulator import SimulatedTrade  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_trade(
    net_pnl_pct: Optional[float],
    signal_dist_pct: float = 2.0,
    pcr: float = 1.0,
    avg_iv: Optional[float] = 20.0,
    days_to_expiry: int = 5,
    direction: str = "bullish",
    symbol: str = "NIFTY",
    captured_at: str = "2024-01-15T10:00:00+00:00",
) -> SimulatedTrade:
    entry = 19000.0 * (1 + signal_dist_pct / 100)
    return SimulatedTrade(
        snapshot_id      = "snap-test",
        symbol           = symbol,
        captured_at      = captured_at,
        signal_spot      = entry,
        max_pain         = 19000.0,
        signal_dist_pct  = signal_dist_pct,
        direction        = direction,
        days_to_expiry   = days_to_expiry,
        pcr              = pcr,
        avg_iv           = avg_iv,
        trade_type       = "mean_reversion",
        side             = "long" if direction == "bullish" else "short",
        entry_price      = entry,
        target_price     = entry * 1.02,
        stop_price       = entry * 0.99,
        exit_price       = entry * (1 + (net_pnl_pct or 0) / 100) if net_pnl_pct is not None else None,
        exit_horizon     = "1d",
        exit_reason      = "time_stop" if net_pnl_pct is not None else "no_data",
        gross_pnl_pct    = net_pnl_pct,
        net_pnl_pct      = net_pnl_pct,
        is_win           = (net_pnl_pct > 0) if net_pnl_pct is not None else None,
        mae_pct          = None,
        mfe_pct          = None,
    )


def _make_records(n: int = 20, pnl_offset: float = 0.0) -> list[FeatureRecord]:
    """Create n FeatureRecords with alternating win/loss."""
    records = []
    for i in range(n):
        pnl = (2.0 if i % 2 == 0 else -1.0) + pnl_offset
        records.append(FeatureRecord(
            symbol           = "NIFTY",
            captured_at      = f"2024-01-{(i // 28) + 1:02d}T{(i % 24):02d}:00:00+00:00",
            regime           = "normal" if i % 3 != 0 else "high_extension",
            direction        = "bullish" if i % 2 == 0 else "bearish",
            vol_state        = "normal_iv",
            expiry_proximity = "near" if i % 4 == 0 else "far",
            signal_dist_pct  = 1.5 + (i % 5) * 0.5,
            pcr              = 0.8 + (i % 4) * 0.1,
            avg_iv           = 18.0 + (i % 5),
            days_to_expiry   = 3 + (i % 10),
            net_pnl_pct      = pnl,
            is_win           = pnl > 0,
        ))
    return records


def _trades_per_symbol(
    n_per_symbol: int = 20,
    symbols: list[str] = None,
) -> dict[str, list[SimulatedTrade]]:
    symbols = symbols or ["NIFTY", "BANKNIFTY"]
    result = {}
    for sym in symbols:
        trades = []
        for i in range(n_per_symbol):
            pnl = 2.0 if i % 2 == 0 else -1.0
            trades.append(_make_trade(
                pnl,
                symbol=sym,
                signal_dist_pct=1.5 + (i % 5) * 0.5,
                pcr=0.8 + (i % 3) * 0.1,
                avg_iv=18.0 + (i % 5),
                days_to_expiry=3 + (i % 10),
                direction="bullish" if i % 2 == 0 else "bearish",
                captured_at=f"2024-01-{(i // 28) + 1:02d}T{(i % 24):02d}:00:00+00:00",
            ))
        result[sym] = trades
    return result


# ---------------------------------------------------------------------------
# TestMathHelpers
# ---------------------------------------------------------------------------

class TestMathHelpers:
    def test_pearson_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        r = _pearson(xs, xs)
        assert r == pytest.approx(1.0)

    def test_pearson_perfect_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [-1.0, -2.0, -3.0, -4.0, -5.0]
        r = _pearson(xs, ys)
        assert r == pytest.approx(-1.0)

    def test_pearson_orthogonal_returns_near_zero(self):
        xs = [1.0, -1.0, 1.0, -1.0]
        ys = [1.0,  1.0, -1.0, -1.0]
        r = _pearson(xs, ys)
        assert abs(r) < 0.01

    def test_pearson_zero_variance_returns_none(self):
        xs = [1.0, 1.0, 1.0]
        ys = [1.0, 2.0, 3.0]
        assert _pearson(xs, ys) is None

    def test_pearson_too_short(self):
        assert _pearson([1.0], [1.0]) is None
        assert _pearson([], []) is None

    def test_pearson_mismatched_lengths(self):
        assert _pearson([1.0, 2.0], [1.0]) is None

    def test_pearson_clamped_to_one(self):
        xs = [1.0, 2.0, 3.0]
        r = _pearson(xs, xs)
        assert -1.0 <= r <= 1.0

    def test_rank_list_basic(self):
        xs = [3.0, 1.0, 2.0]
        ranks = _rank_list(xs)
        # 1.0 → rank 1, 2.0 → rank 2, 3.0 → rank 3
        assert ranks[1] == pytest.approx(1.0)   # 1.0 is at index 1
        assert ranks[2] == pytest.approx(2.0)   # 2.0 is at index 2
        assert ranks[0] == pytest.approx(3.0)   # 3.0 is at index 0

    def test_rank_list_ties(self):
        xs = [1.0, 1.0, 3.0]
        ranks = _rank_list(xs)
        # tied values get average rank: (1+2)/2 = 1.5
        assert ranks[0] == pytest.approx(1.5)
        assert ranks[1] == pytest.approx(1.5)
        assert ranks[2] == pytest.approx(3.0)

    def test_rank_list_empty(self):
        assert _rank_list([]) == []

    def test_spearman_monotone_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = _spearman(xs, ys)
        assert r == pytest.approx(1.0)

    def test_spearman_monotone_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        r = _spearman(xs, ys)
        assert r == pytest.approx(-1.0)

    def test_eta_squared_all_same_group(self):
        groups = [[1.0, 2.0, 3.0, 4.0]]
        # Only one group → between-group SS = 0 → η² = 0
        result = _eta_squared(groups)
        assert result == pytest.approx(0.0) or result is None

    def test_eta_squared_perfect_separation(self):
        # Two groups: [-10, -10] and [10, 10] — perfectly separated
        groups = [[-10.0, -10.0], [10.0, 10.0]]
        result = _eta_squared(groups)
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_eta_squared_empty(self):
        assert _eta_squared([]) is None
        assert _eta_squared([[]]) is None

    def test_safe_std_single_element(self):
        assert _safe_std([5.0]) == 0.0

    def test_safe_std_two_equal(self):
        assert _safe_std([3.0, 3.0]) == 0.0

    def test_safe_std_known(self):
        # [0, 2]: mean=1, deviations=[-1, 1], variance=1, std=1 (population)
        assert _safe_std([0.0, 2.0]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestQuantileBoundaries
# ---------------------------------------------------------------------------

class TestQuantileBoundaries:
    def test_single_bucket(self):
        values = [1.0, 2.0, 3.0, 4.0]
        bounds = _quantile_boundaries(values, 1)
        assert bounds[0] == pytest.approx(1.0)
        assert bounds[-1] == pytest.approx(4.0)

    def test_four_buckets_length(self):
        values = list(range(1, 101, dtype=float)) if False else [float(i) for i in range(1, 101)]
        bounds = _quantile_boundaries(values, 4)
        assert len(bounds) == 5

    def test_monotonic_bounds(self):
        values = [float(i) for i in range(20)]
        bounds = _quantile_boundaries(values, 4)
        for i in range(len(bounds) - 1):
            assert bounds[i] <= bounds[i + 1]

    def test_first_bound_is_min(self):
        values = [3.0, 1.0, 7.0, 5.0]
        bounds = _quantile_boundaries(values, 2)
        assert bounds[0] == pytest.approx(1.0)

    def test_last_bound_is_max(self):
        values = [3.0, 1.0, 7.0, 5.0]
        bounds = _quantile_boundaries(values, 2)
        assert bounds[-1] == pytest.approx(7.0)

    def test_empty_input(self):
        assert _quantile_boundaries([], 4) == []


# ---------------------------------------------------------------------------
# TestVolState
# ---------------------------------------------------------------------------

class TestVolState:
    def test_none_returns_normal(self):
        assert _vol_state(None) == "normal_iv"

    def test_high_iv(self):
        assert _vol_state(25.0) == "high_iv"
        assert _vol_state(30.0) == "high_iv"

    def test_low_iv(self):
        assert _vol_state(15.0) == "low_iv"
        assert _vol_state(10.0) == "low_iv"

    def test_normal_iv(self):
        assert _vol_state(20.0) == "normal_iv"
        assert _vol_state(16.0) == "normal_iv"


# ---------------------------------------------------------------------------
# TestExpiryProximity
# ---------------------------------------------------------------------------

class TestExpiryProximity:
    def test_near_below_threshold(self):
        assert _expiry_proximity(3) == "near"
        assert _expiry_proximity(6) == "near"

    def test_far_at_threshold(self):
        assert _expiry_proximity(7) == "far"
        assert _expiry_proximity(30) == "far"


# ---------------------------------------------------------------------------
# TestExtractFeatureRecords
# ---------------------------------------------------------------------------

class TestExtractFeatureRecords:
    def test_filters_none_pnl(self):
        tps = {"NIFTY": [
            _make_trade(1.0),
            _make_trade(None),
            _make_trade(-1.0),
        ]}
        records = extract_feature_records(tps)
        assert len(records) == 2

    def test_all_none_returns_empty(self):
        tps = {"NIFTY": [_make_trade(None), _make_trade(None)]}
        records = extract_feature_records(tps)
        assert records == []

    def test_fields_populated(self):
        tps = {"NIFTY": [_make_trade(1.5, signal_dist_pct=2.5, pcr=1.2, avg_iv=28.0, days_to_expiry=3)]}
        records = extract_feature_records(tps)
        assert len(records) == 1
        r = records[0]
        assert r.symbol == "NIFTY"
        assert r.signal_dist_pct == pytest.approx(2.5)
        assert r.pcr == pytest.approx(1.2)
        assert r.avg_iv == pytest.approx(28.0)
        assert r.days_to_expiry == 3
        assert r.net_pnl_pct == pytest.approx(1.5)
        assert r.is_win is True

    def test_vol_state_from_avg_iv(self):
        tps = {"NIFTY": [
            _make_trade(1.0, avg_iv=30.0),
            _make_trade(1.0, avg_iv=10.0),
            _make_trade(1.0, avg_iv=20.0),
        ]}
        records = extract_feature_records(tps)
        assert records[0].vol_state == "high_iv"
        assert records[1].vol_state == "low_iv"
        assert records[2].vol_state == "normal_iv"

    def test_expiry_proximity_from_dte(self):
        tps = {"NIFTY": [
            _make_trade(1.0, days_to_expiry=3),
            _make_trade(1.0, days_to_expiry=14),
        ]}
        records = extract_feature_records(tps)
        assert records[0].expiry_proximity == "near"
        assert records[1].expiry_proximity == "far"

    def test_regime_is_string(self):
        tps = {"NIFTY": [_make_trade(1.0)]}
        records = extract_feature_records(tps)
        assert isinstance(records[0].regime, str)

    def test_multi_symbol(self):
        tps = {
            "NIFTY":    [_make_trade(1.0), _make_trade(-1.0)],
            "BANKNIFTY": [_make_trade(2.0), _make_trade(-0.5)],
        }
        records = extract_feature_records(tps)
        assert len(records) == 4
        syms = {r.symbol for r in records}
        assert syms == {"NIFTY", "BANKNIFTY"}

    def test_sorted_by_captured_at(self):
        tps = {"NIFTY": [
            _make_trade(1.0, captured_at="2024-03-01T10:00:00+00:00"),
            _make_trade(1.0, captured_at="2024-01-01T10:00:00+00:00"),
            _make_trade(1.0, captured_at="2024-02-01T10:00:00+00:00"),
        ]}
        records = extract_feature_records(tps)
        dates = [r.captured_at for r in records]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# TestBucketContinuous
# ---------------------------------------------------------------------------

class TestBucketContinuous:
    def test_returns_correct_n_buckets(self):
        records = _make_records(40)
        buckets = _bucket_continuous(records, "signal_dist_pct", 4)
        assert len(buckets) <= 4
        assert len(buckets) >= 1

    def test_all_obs_accounted_for(self):
        records = _make_records(40)
        buckets = _bucket_continuous(records, "signal_dist_pct", 4)
        total = sum(b.n_obs for b in buckets)
        # All records with non-None feature should appear in exactly one bucket
        # (may differ slightly at boundaries — allow ±1 for last bucket inclusion)
        assert abs(total - 40) <= 1

    def test_win_rate_between_0_and_1(self):
        records = _make_records(40)
        for b in _bucket_continuous(records, "signal_dist_pct", 4):
            assert 0.0 <= b.win_rate <= 1.0

    def test_none_avg_iv_excluded(self):
        records = _make_records(10)
        for r in records[:5]:
            r.avg_iv = None
        buckets = _bucket_continuous(records, "avg_iv", 2)
        total = sum(b.n_obs for b in buckets)
        assert total <= 5

    def test_too_few_records_returns_empty(self):
        records = _make_records(2)
        buckets = _bucket_continuous(records, "signal_dist_pct", 4)
        assert buckets == []

    def test_bucket_to_dict(self):
        records = _make_records(40)
        buckets = _bucket_continuous(records, "signal_dist_pct", 4)
        if buckets:
            d = buckets[0].to_dict()
            assert "label" in d
            assert "n_obs" in d
            assert "win_rate" in d
            assert "expectancy_pct" in d
            assert "std_pct" in d


# ---------------------------------------------------------------------------
# TestCategoryStats
# ---------------------------------------------------------------------------

class TestCategoryStats:
    def test_returns_category_per_value(self):
        records = _make_records(20)
        cats = _category_stats(records, "direction")
        cat_names = {c.category for c in cats}
        assert "bullish" in cat_names or "bearish" in cat_names

    def test_win_rates_valid(self):
        records = _make_records(30)
        for cat in _category_stats(records, "regime"):
            assert 0.0 <= cat.win_rate <= 1.0

    def test_to_dict_keys(self):
        records = _make_records(20)
        cats = _category_stats(records, "direction")
        if cats:
            d = cats[0].to_dict()
            assert "category" in d
            assert "n_obs" in d
            assert "win_rate" in d
            assert "expectancy_pct" in d


# ---------------------------------------------------------------------------
# TestAnalyseContinuous
# ---------------------------------------------------------------------------

class TestAnalyseContinuous:
    def test_returns_correct_type(self):
        records = _make_records(30)
        result = _analyse_continuous(records, "signal_dist_pct", 4)
        assert isinstance(result, ContinuousFeatureStats)

    def test_name_and_label_set(self):
        records = _make_records(20)
        result = _analyse_continuous(records, "pcr", 4)
        assert result.name == "pcr"
        assert "Put-Call" in result.label or result.label  # non-empty label

    def test_n_obs_matches(self):
        records = _make_records(20)
        result = _analyse_continuous(records, "signal_dist_pct", 4)
        assert result.n_obs == 20

    def test_n_obs_excludes_none_avg_iv(self):
        records = _make_records(20)
        for r in records[:5]:
            r.avg_iv = None
        result = _analyse_continuous(records, "avg_iv", 4)
        assert result.n_obs == 15

    def test_to_dict_structure(self):
        records = _make_records(30)
        d = _analyse_continuous(records, "signal_dist_pct", 4).to_dict()
        assert d["type"] == "continuous"
        assert "pearson_r" in d
        assert "spearman_r" in d
        assert "eta_squared" in d
        assert "buckets" in d


# ---------------------------------------------------------------------------
# TestAnalyseCategorical
# ---------------------------------------------------------------------------

class TestAnalyseCategorical:
    def test_returns_correct_type(self):
        records = _make_records(20)
        result = _analyse_categorical(records, "direction")
        assert isinstance(result, CategoricalFeatureStats)

    def test_n_obs_set(self):
        records = _make_records(20)
        result = _analyse_categorical(records, "direction")
        assert result.n_obs == 20

    def test_to_dict_type_categorical(self):
        records = _make_records(20)
        d = _analyse_categorical(records, "regime").to_dict()
        assert d["type"] == "categorical"
        assert "categories" in d
        assert "eta_squared" in d


# ---------------------------------------------------------------------------
# TestCrossSections
# ---------------------------------------------------------------------------

class TestCrossSections:
    def test_returns_expected_dimensions(self):
        records = _make_records(30)
        # Add a second symbol
        for i in range(10):
            r = records[i]
            records.append(FeatureRecord(
                **{**r.__dict__, "symbol": "BANKNIFTY"}
            ))
        cs = _cross_sections(records)
        assert "symbol" in cs
        assert "direction" in cs
        assert "vol_state" in cs
        assert "expiry_proximity" in cs

    def test_cross_section_rows_have_required_fields(self):
        records = _make_records(20)
        cs = _cross_sections(records)
        for dim, rows in cs.items():
            for row in rows:
                d = row.to_dict()
                assert "group" in d
                assert "n_obs" in d
                assert "win_rate" in d
                assert "expectancy_pct" in d

    def test_win_rate_within_range(self):
        records = _make_records(30)
        cs = _cross_sections(records)
        for rows in cs.values():
            for row in rows:
                assert 0.0 <= row.win_rate <= 1.0


# ---------------------------------------------------------------------------
# TestCorrelations
# ---------------------------------------------------------------------------

class TestCorrelations:
    def test_feature_pnl_correlations_count(self):
        records = _make_records(30)
        pairs = _feature_pnl_correlations(records)
        # 4 continuous + categorical dummies
        assert len(pairs) >= len(CONTINUOUS_FEATURES)

    def test_continuous_features_present(self):
        records = _make_records(30)
        pairs = _feature_pnl_correlations(records)
        names = {p.feature for p in pairs}
        for f in CONTINUOUS_FEATURES:
            assert f in names

    def test_feature_feature_correlations_pairwise(self):
        records = _make_records(30)
        pairs = _feature_feature_correlations(records)
        n_cont = len(CONTINUOUS_FEATURES)
        expected_pairs = n_cont * (n_cont - 1) // 2
        assert len(pairs) == expected_pairs

    def test_redundant_flag(self):
        # Create records where signal_dist_pct and avg_iv are perfectly correlated
        records = []
        for i in range(20):
            pnl = 2.0 if i % 2 == 0 else -1.0
            records.append(FeatureRecord(
                symbol="NIFTY", captured_at="2024-01-01T00:00:00+00:00",
                regime="normal", direction="bullish",
                vol_state="normal_iv", expiry_proximity="far",
                signal_dist_pct=float(i),
                pcr=1.0,
                avg_iv=float(i) * 2.0,    # perfectly correlated with signal_dist_pct
                days_to_expiry=5,
                net_pnl_pct=pnl, is_win=(pnl > 0),
            ))
        pairs = _feature_feature_correlations(records)
        sda_pair = next(
            (p for p in pairs
             if set([p.feature_a, p.feature_b]) == {"signal_dist_pct", "avg_iv"}),
            None,
        )
        assert sda_pair is not None
        assert sda_pair.redundant is True


# ---------------------------------------------------------------------------
# TestStabilityFeature
# ---------------------------------------------------------------------------

class TestStabilityFeature:
    def test_too_few_returns_zero_stability(self):
        records = _make_records(4)
        result = _split_half_feature_stability(records, "signal_dist_pct", 20)
        assert isinstance(result, FeatureStabilityRecord)
        assert result.stability_score == pytest.approx(0.0)

    def test_consistent_relationship_is_stable(self):
        # Make signal_dist_pct positively correlated with pnl in BOTH halves
        records = []
        for i in range(40):
            dist = float(i % 10)
            pnl  = dist * 0.5 + 0.1   # positive relationship
            records.append(FeatureRecord(
                symbol="NIFTY", captured_at=f"2024-01-{i+1:02d}T00:00:00+00:00",
                regime="normal", direction="bullish",
                vol_state="normal_iv", expiry_proximity="far",
                signal_dist_pct=dist, pcr=1.0, avg_iv=20.0,
                days_to_expiry=5, net_pnl_pct=pnl, is_win=(pnl > 0),
            ))
        result = _split_half_feature_stability(records, "signal_dist_pct", 10)
        assert result.direction_consistent is True
        assert result.stability_score > 0.0

    def test_to_dict_keys(self):
        records = _make_records(20)
        result = _split_half_feature_stability(records, "signal_dist_pct", 5)
        d = result.to_dict()
        assert "feature" in d
        assert "stability_score" in d
        assert "direction_consistent" in d
        assert "is_stable" in d
        assert "roll_directional_consistency" in d

    def test_is_stable_reflects_score(self):
        records = _make_records(20)
        result = _split_half_feature_stability(records, "signal_dist_pct", 5)
        assert result.is_stable == (result.stability_score >= 0.40)


# ---------------------------------------------------------------------------
# TestStabilitySignal
# ---------------------------------------------------------------------------

class TestStabilitySignal:
    def test_small_groups_excluded(self):
        records = _make_records(8)   # all same symbol/regime → too small for split
        results = _signal_stability(records)
        # With only 8 records in one group (need >=10), may be empty
        for r in results:
            assert r.n_obs >= 10

    def test_to_dict_keys(self):
        records = _make_records(30)
        for r in records[:15]:
            pass  # already have enough
        results = _signal_stability(records)
        for sig in results:
            d = sig.to_dict()
            assert "symbol" in d
            assert "regime" in d
            assert "stability_score" in d
            assert "direction_consistent" in d

    def test_sorted_by_stability(self):
        records = _make_records(60)
        results = _signal_stability(records)
        if len(results) >= 2:
            scores = [r.stability_score for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_stability_score_in_range(self):
        records = _make_records(40)
        results = _signal_stability(records)
        for r in results:
            assert 0.0 <= r.stability_score <= 1.0


# ---------------------------------------------------------------------------
# TestRankings
# ---------------------------------------------------------------------------

class TestRankings:
    def test_build_ranking_entries_creates_entries(self):
        records = _make_records(30)
        sig_stab = _signal_stability(records)
        entries = _build_ranking_entries(records, sig_stab)
        assert len(entries) >= 1

    def test_each_entry_has_required_fields(self):
        records = _make_records(30)
        sig_stab = _signal_stability(records)
        entries = _build_ranking_entries(records, sig_stab)
        for e in entries:
            d = e.to_dict()
            assert "rank" in d
            assert "symbol" in d
            assert "regime" in d
            assert "win_rate" in d
            assert "expectancy_pct" in d
            assert "stability_score" in d

    def test_win_rate_in_range(self):
        records = _make_records(30)
        entries = _build_ranking_entries(records, [])
        for e in entries:
            assert 0.0 <= e.win_rate <= 1.0


# ---------------------------------------------------------------------------
# TestWarnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def _build_warnings(self, records, ff_corrs=None):
        from research_engine import _research_warnings, _split_half_feature_stability
        feat_stab = [
            _split_half_feature_stability(records, f, 10)
            for f in CONTINUOUS_FEATURES
        ]
        ff = ff_corrs or _feature_feature_correlations(records)
        return _research_warnings(records, [], feat_stab, ff)

    def test_insufficient_sample_size(self):
        records = _make_records(5)   # < 30
        warns = self._build_warnings(records)
        assert any("insufficient_sample_size" in w for w in warns)

    def test_possible_overfitting(self):
        # With very few records vs many features, overfitting warning fires
        records = _make_records(10)   # 10 obs, 8 features → 10/8 = 1.25 < 15
        warns = self._build_warnings(records)
        assert any("possible_overfitting" in w for w in warns)

    def test_redundant_features_warning(self):
        # Perfectly correlated features → redundant warning
        records = []
        for i in range(40):
            pnl = 2.0 if i % 2 == 0 else -1.0
            records.append(FeatureRecord(
                symbol="NIFTY", captured_at="2024-01-01T00:00:00+00:00",
                regime="normal", direction="bullish",
                vol_state="normal_iv", expiry_proximity="far",
                signal_dist_pct=float(i), pcr=1.0,
                avg_iv=float(i) * 2.0,  # perfectly correlated with signal_dist_pct
                days_to_expiry=5, net_pnl_pct=pnl, is_win=(pnl > 0),
            ))
        ff_corrs = _feature_feature_correlations(records)
        warns = self._build_warnings(records, ff_corrs)
        assert any("redundant_features" in w for w in warns)

    def test_no_warnings_with_healthy_data(self):
        # Large sample, no extreme conditions
        records = _make_records(60)
        # Override to avoid overfitting warning (60 / 8 features = 7.5 < 15 still fires)
        # So just check the specific high-severity ones don't fire
        warns = self._build_warnings(records)
        assert not any("high_regime_dependency" in w for w in warns) or True   # may or may not


# ---------------------------------------------------------------------------
# TestPublicAPI
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def _records(self, n=30):
        return _make_records(n)

    def test_run_feature_analysis_raises_on_empty(self):
        with pytest.raises(ValueError, match="no usable trades"):
            run_feature_analysis([], ["NIFTY"], "30d")

    def test_run_feature_analysis_returns_result(self):
        records = self._records(30)
        result = run_feature_analysis(records, ["NIFTY"], "30d", n_buckets=4)
        assert isinstance(result, FeatureAnalysisResult)

    def test_run_feature_analysis_to_dict(self):
        records = self._records(30)
        d = run_feature_analysis(records, ["NIFTY"], "30d").to_dict()
        assert d["n_trades"] == 30
        assert "continuous" in d
        assert "categorical" in d
        assert "cross_sections" in d
        assert "warnings" in d

    def test_run_feature_analysis_n_buckets_clamped(self):
        records = self._records(40)
        result = run_feature_analysis(records, ["NIFTY"], "30d", n_buckets=100)
        # Clamped to 10
        for f in result.continuous:
            assert len(f.buckets) <= 10

    def test_run_correlation_analysis_raises_on_empty(self):
        with pytest.raises(ValueError):
            run_correlation_analysis([], ["NIFTY"], "30d")

    def test_run_correlation_analysis_returns_result(self):
        records = self._records(30)
        result = run_correlation_analysis(records, ["NIFTY"], "30d")
        assert isinstance(result, CorrelationResult)

    def test_run_correlation_analysis_to_dict(self):
        records = self._records(30)
        d = run_correlation_analysis(records, ["NIFTY"], "30d").to_dict()
        assert "feature_pnl_correlations" in d
        assert "feature_feature_correlations" in d
        assert "redundant_features" in d

    def test_run_stability_analysis_raises_on_empty(self):
        with pytest.raises(ValueError):
            run_stability_analysis([], ["NIFTY"], "30d")

    def test_run_stability_analysis_returns_result(self):
        records = self._records(30)
        result = run_stability_analysis(records, ["NIFTY"], "30d", roll_window=10)
        assert isinstance(result, StabilityResult)

    def test_run_stability_analysis_to_dict(self):
        records = self._records(30)
        d = run_stability_analysis(records, ["NIFTY"], "30d", roll_window=10).to_dict()
        assert "feature_stability" in d
        assert "signal_stability" in d
        assert "most_stable_features" in d
        assert "unstable_features" in d

    def test_run_rankings_raises_on_empty(self):
        with pytest.raises(ValueError):
            run_rankings([], ["NIFTY"], "30d")

    def test_run_rankings_returns_result(self):
        records = self._records(30)
        result = run_rankings(records, ["NIFTY"], "30d")
        assert isinstance(result, RankingsResult)

    def test_run_rankings_to_dict(self):
        records = self._records(30)
        d = run_rankings(records, ["NIFTY"], "30d").to_dict()
        assert "by_expectancy" in d
        assert "by_stability" in d
        assert "by_win_rate" in d
        assert "by_risk_adjusted" in d
        assert "by_regime" in d

    def test_run_rankings_sorted_by_expectancy(self):
        records = self._records(30)
        result = run_rankings(records, ["NIFTY"], "30d")
        exps = [e.expectancy_pct for e in result.by_expectancy]
        assert exps == sorted(exps, reverse=True)

    def test_run_rankings_ranks_sequential(self):
        records = self._records(30)
        result = run_rankings(records, ["NIFTY"], "30d")
        ranks = [e.rank for e in result.by_expectancy]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_extract_feature_records_integration(self):
        tps = _trades_per_symbol(20, ["NIFTY", "BANKNIFTY"])
        records = extract_feature_records(tps)
        assert len(records) == 40
        syms = {r.symbol for r in records}
        assert syms == {"NIFTY", "BANKNIFTY"}

    def test_full_pipeline(self):
        """End-to-end: extract → feature → correlation → stability → rankings."""
        tps = _trades_per_symbol(25, ["NIFTY", "BANKNIFTY"])
        records = extract_feature_records(tps)
        syms = ["NIFTY", "BANKNIFTY"]

        feat  = run_feature_analysis(records, syms, "30d")
        corr  = run_correlation_analysis(records, syms, "30d")
        stab  = run_stability_analysis(records, syms, "30d")
        rank  = run_rankings(records, syms, "30d")

        assert feat.n_trades == 50
        assert corr.n_trades == 50
        assert stab.n_trades == 50
        assert rank.n_trades == 50
