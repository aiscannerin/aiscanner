"""
Tests for monte_carlo_engine.py

Uses the same importlib bypass pattern as the other test files.

Coverage
--------
TestMonteCarloParams         – validate() and to_dict()
TestPercentile               – _percentile interpolation, edge cases
TestExpectedShortfall        – CVaR / ES computation
TestSinglePath               – path simulation: ruin, max DD, recovery durations
TestResampleBootstrap        – IID with replacement
TestResampleRandomOrder      – shuffle-based resampling
TestResampleBlockBootstrap   – block-based resampling
TestResampleRegimeShuffle    – within-regime shuffle
TestVolShock                 – mean preserved, std scaled
TestSlippageExpansion        – per-trade cost deduction
TestDrawdownClustering       – losses before wins ordering
TestConsecutiveLosses        – N worst at front
TestCorrelatedDownside       – losses amplified, wins unchanged
TestDominantRegimePnls       – dominant regime filter
TestExtractPnlRegimes        – filter no_data, correct lengths
TestRunMonteCarlo            – full run: structure, ruin/no-ruin
TestRunStressTests           – all 8 scenarios, delta computation
TestWarnings                 – all 6 warning conditions
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

# Load in dependency order
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
_mc = _load(
    "monte_carlo_engine",
    "app/services/monte_carlo_engine.py",
    alias="app.services.monte_carlo_engine",
)

# Import public symbols
from monte_carlo_engine import (  # noqa: E402
    MonteCarloParams,
    MonteCarloSummary,
    SinglePathResult,
    StressScenarioResult,
    VALID_MC_METHODS,
    _percentile,
    _percentiles,
    _expected_shortfall,
    _run_single_path,
    _resample_bootstrap,
    _resample_random_order,
    _resample_block_bootstrap,
    _resample_regime_shuffle,
    _apply_vol_shock,
    _apply_slippage_expansion,
    _apply_drawdown_clustering,
    _apply_consecutive_losses,
    _apply_correlated_downside,
    _dominant_regime_pnls,
    extract_pnl_regimes,
    run_monte_carlo,
    run_stress_tests,
    _generate_mc_warnings,
    _aggregate_paths,
)
from trade_simulator import SimulatedTrade  # noqa: E402

import random


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _default_params(**kw) -> MonteCarloParams:
    defaults = dict(
        n_simulations=200,
        method="bootstrap",
        position_size_pct=2.0,
        initial_capital=100_000.0,
        ruin_threshold_pct=50.0,
        block_size=5,
        seed=42,
    )
    defaults.update(kw)
    return MonteCarloParams(**defaults)


def _make_trade(
    net_pnl_pct: Optional[float],
    direction: str = "bullish",
    symbol: str = "NIFTY",
    signal_dist_pct: float = 2.0,
    days_to_expiry: int = 5,
    pcr: float = 1.0,
    avg_iv: float = 20.0,
) -> SimulatedTrade:
    """Create a minimal SimulatedTrade for MC testing."""
    entry = 19000.0 * (1 + signal_dist_pct / 100)
    return SimulatedTrade(
        snapshot_id="test-snap",
        symbol=symbol,
        captured_at="2024-01-15T10:00:00+00:00",
        signal_spot=entry,
        max_pain=19000.0,
        signal_dist_pct=signal_dist_pct,
        direction=direction,
        days_to_expiry=days_to_expiry,
        pcr=pcr,
        avg_iv=avg_iv,
        trade_type="mean_reversion",
        side="long" if direction == "bullish" else "short",
        entry_price=entry,
        target_price=entry * 1.02,
        stop_price=entry * 0.99,
        exit_price=entry * (1 + (net_pnl_pct or 0) / 100) if net_pnl_pct is not None else None,
        exit_horizon="1d",
        exit_reason="time_stop" if net_pnl_pct is not None else "no_data",
        gross_pnl_pct=net_pnl_pct,
        net_pnl_pct=net_pnl_pct,
        is_win=(net_pnl_pct > 0) if net_pnl_pct is not None else None,
        mae_pct=None,
        mfe_pct=None,
    )


def _make_trades(pnls: list[Optional[float]]) -> list[SimulatedTrade]:
    return [_make_trade(p) for p in pnls]


def _rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


# ---------------------------------------------------------------------------
# TestMonteCarloParams
# ---------------------------------------------------------------------------

class TestMonteCarloParams:
    def test_default_values(self):
        p = MonteCarloParams()
        assert p.n_simulations == 1_000
        assert p.method == "bootstrap"
        assert p.position_size_pct == 2.0
        assert p.initial_capital == 1_000_000.0
        assert p.ruin_threshold_pct == 50.0
        assert p.block_size == 5
        assert p.seed is None

    def test_validate_valid(self):
        p = _default_params()
        assert p.validate() == []

    def test_validate_invalid_method(self):
        p = _default_params(method="invalid_method")
        issues = p.validate()
        assert any("method" in i for i in issues)

    def test_validate_zero_simulations(self):
        p = _default_params(n_simulations=0)
        issues = p.validate()
        assert any("n_simulations" in i for i in issues)

    def test_validate_too_many_simulations(self):
        p = _default_params(n_simulations=10_001)
        issues = p.validate()
        assert any("n_simulations" in i for i in issues)

    def test_validate_negative_position_size(self):
        p = _default_params(position_size_pct=-1.0)
        issues = p.validate()
        assert any("position_size_pct" in i for i in issues)

    def test_validate_zero_capital(self):
        p = _default_params(initial_capital=0.0)
        issues = p.validate()
        assert any("initial_capital" in i for i in issues)

    def test_validate_ruin_threshold_out_of_range(self):
        p1 = _default_params(ruin_threshold_pct=0.5)
        p2 = _default_params(ruin_threshold_pct=100.0)
        assert any("ruin_threshold_pct" in i for i in p1.validate())
        assert any("ruin_threshold_pct" in i for i in p2.validate())

    def test_validate_block_size_too_small(self):
        p = _default_params(block_size=1)
        issues = p.validate()
        assert any("block_size" in i for i in issues)

    def test_validate_all_valid_methods(self):
        for method in VALID_MC_METHODS:
            p = _default_params(method=method)
            assert p.validate() == [], f"method={method} should be valid"

    def test_to_dict_keys(self):
        p = _default_params(seed=7)
        d = p.to_dict()
        assert "n_simulations" in d
        assert "method" in d
        assert "position_size_pct" in d
        assert "initial_capital" in d
        assert "ruin_threshold_pct" in d
        assert "block_size" in d
        assert d["seed"] == 7

    def test_to_dict_values_match(self):
        p = _default_params(n_simulations=500, method="random_order", seed=99)
        d = p.to_dict()
        assert d["n_simulations"] == 500
        assert d["method"] == "random_order"
        assert d["seed"] == 99


# ---------------------------------------------------------------------------
# TestPercentile
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty_returns_zero(self):
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        assert _percentile([7.0], 0) == 7.0
        assert _percentile([7.0], 50) == 7.0
        assert _percentile([7.0], 100) == 7.0

    def test_two_elements_median(self):
        result = _percentile([0.0, 10.0], 50)
        assert result == pytest.approx(5.0)

    def test_p0_is_minimum(self):
        sv = sorted([3.0, 1.0, 7.0, 5.0])
        assert _percentile(sv, 0) == pytest.approx(1.0)

    def test_p100_is_maximum(self):
        sv = sorted([3.0, 1.0, 7.0, 5.0])
        assert _percentile(sv, 100) == pytest.approx(7.0)

    def test_interpolation_midpoint(self):
        # [0, 10] at p50 => 5.0
        sv = [0.0, 10.0]
        assert _percentile(sv, 50) == pytest.approx(5.0)

    def test_monotonic_with_level(self):
        sv = sorted([1.0, 2.0, 3.0, 4.0, 5.0])
        prev = _percentile(sv, 0)
        for lv in [10, 25, 50, 75, 90, 100]:
            cur = _percentile(sv, lv)
            assert cur >= prev
            prev = cur

    def test_percentiles_batch(self):
        sv = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _percentiles(sv, [0, 50, 100])
        assert result[0] == pytest.approx(1.0)
        assert result[100] == pytest.approx(5.0)
        assert result[50] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# TestExpectedShortfall
# ---------------------------------------------------------------------------

class TestExpectedShortfall:
    def test_empty_returns_zero(self):
        assert _expected_shortfall([]) == 0.0

    def test_single_element(self):
        assert _expected_shortfall([-5.0]) == pytest.approx(-5.0)

    def test_worst_5_percent(self):
        # 100 returns: worst 5 are [-100, -90, -80, -70, -60], mean = -80
        returns = list(range(-100, 0)) + [1.0] * 0
        # Actually: -100 through -1 is 100 items; worst 5% = 5 items: -100,-99,-98,-97,-96
        returns = [float(x) for x in range(-100, 0)]
        es = _expected_shortfall(returns, 5.0)
        # 5% of 100 = 5 items = ceil(5) = 5: -100,-99,-98,-97,-96, mean=-98
        assert es == pytest.approx((-100 + -99 + -98 + -97 + -96) / 5)

    def test_all_positive_es_is_smallest(self):
        returns = [1.0, 2.0, 3.0, 4.0, 5.0]
        es = _expected_shortfall(returns, 20.0)
        # worst 20% of 5 = ceil(1) = 1: [1.0]
        assert es == pytest.approx(1.0)

    def test_symmetric_distribution(self):
        returns = [-10.0, -5.0, 0.0, 5.0, 10.0]
        es = _expected_shortfall(returns, 20.0)
        # worst 20% of 5 = ceil(1) = 1: [-10.0]
        assert es == pytest.approx(-10.0)

    def test_threshold_100_percent(self):
        returns = [-3.0, -1.0, 2.0, 5.0]
        es = _expected_shortfall(returns, 100.0)
        # all 4 items
        assert es == pytest.approx(sum(returns) / 4)


# ---------------------------------------------------------------------------
# TestSinglePath
# ---------------------------------------------------------------------------

class TestSinglePath:
    def test_no_trades_returns_initial_capital(self):
        result = _run_single_path([], 100_000, 2.0, 50.0)
        assert result.final_equity == pytest.approx(100_000.0)
        assert result.total_return_pct == pytest.approx(0.0)
        assert result.max_drawdown_pct == pytest.approx(0.0)
        assert result.ruined is False
        assert result.recovery_durations == []

    def test_all_winning_no_ruin(self):
        pnls = [1.0] * 20   # 20 winning trades
        result = _run_single_path(pnls, 100_000, 2.0, 50.0)
        assert result.ruined is False
        assert result.total_return_pct > 0
        assert result.max_drawdown_pct == 0.0

    def test_massive_loss_triggers_ruin(self):
        # single trade loses 100% → equity → 0 < ruin_level
        pnls = [-100.0]
        result = _run_single_path(pnls, 100_000, 100.0, 50.0)
        assert result.ruined is True

    def test_ruin_halts_path(self):
        # Two trades, first causes ruin, second would recover
        # position_size=100%, pnl=-60% → equity=40000 < ruin_level(50000) → ruin
        pnls = [-60.0, 100.0]
        result = _run_single_path(pnls, 100_000, 100.0, 50.0)
        assert result.ruined is True
        # final equity should reflect only the first trade
        assert result.final_equity < 100_000.0

    def test_max_drawdown_computed(self):
        # Go up then down: ensure max DD captured
        pnls = [10.0, 10.0, -20.0]   # rises then falls
        result = _run_single_path(pnls, 100_000, 10.0, 80.0)
        assert result.max_drawdown_pct > 0.0

    def test_recovery_duration_recorded(self):
        # We need a drawdown that fully recovers
        # With size_pct=100: trade 1: +10% → equity=110000 (peak)
        # trade 2: -5% → equity=104500 (DD from 110000)
        # trade 3: +5.5% → equity ~115950 > 110000 → recovers
        pnls = [10.0, -5.0, 5.5]
        result = _run_single_path(pnls, 100_000, 100.0, 80.0)
        # Recovery duration: index 2 - peak_idx (which was 0 after trade 0)
        # After trade 0 (i=0): peak=110000, peak_idx=0
        # After trade 1 (i=1): in_dd=True
        # After trade 2 (i=2): equity recovers → recovery_dur = 2 - 0 = 2
        assert len(result.recovery_durations) >= 1
        assert result.recovery_durations[0] == 2

    def test_compounding_formula(self):
        # Single trade: equity += equity * (pos/100) * (pnl/100)
        # equity = 100000, pos=10, pnl=5 → delta = 100000*0.1*0.05 = 500
        pnls = [5.0]
        result = _run_single_path(pnls, 100_000, 10.0, 50.0)
        assert result.final_equity == pytest.approx(100_000 + 100_000 * 0.10 * 0.05)

    def test_return_pct_formula(self):
        pnls = [5.0]
        result = _run_single_path(pnls, 100_000, 10.0, 50.0)
        expected_return = (result.final_equity - 100_000) / 100_000 * 100.0
        assert result.total_return_pct == pytest.approx(expected_return, abs=1e-3)


# ---------------------------------------------------------------------------
# TestResampleBootstrap
# ---------------------------------------------------------------------------

class TestResampleBootstrap:
    def test_same_length(self):
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _resample_bootstrap(pnls, _rng(0))
        assert len(result) == len(pnls)

    def test_values_from_original(self):
        pnls = [1.0, 2.0, 3.0]
        result = _resample_bootstrap(pnls, _rng(0))
        for v in result:
            assert v in pnls

    def test_reproducible_with_seed(self):
        pnls = list(range(20, dtype=float)) if False else [float(i) for i in range(20)]
        r1 = _resample_bootstrap(pnls, random.Random(42))
        r2 = _resample_bootstrap(pnls, random.Random(42))
        assert r1 == r2

    def test_empty_input(self):
        assert _resample_bootstrap([], _rng(0)) == []

    def test_different_seeds_may_differ(self):
        pnls = [float(i) for i in range(20)]
        r1 = _resample_bootstrap(pnls, random.Random(1))
        r2 = _resample_bootstrap(pnls, random.Random(2))
        # With 20 items, extremely unlikely to be identical
        assert r1 != r2


# ---------------------------------------------------------------------------
# TestResampleRandomOrder
# ---------------------------------------------------------------------------

class TestResampleRandomOrder:
    def test_same_elements(self):
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _resample_random_order(pnls, _rng(99))
        assert sorted(result) == sorted(pnls)

    def test_same_length(self):
        pnls = [1.0, 2.0, 3.0]
        assert len(_resample_random_order(pnls, _rng(0))) == 3

    def test_does_not_mutate_original(self):
        pnls = [1.0, 2.0, 3.0]
        original = list(pnls)
        _resample_random_order(pnls, _rng(0))
        assert pnls == original

    def test_reproducible_with_seed(self):
        pnls = [float(i) for i in range(20)]
        r1 = _resample_random_order(pnls, random.Random(7))
        r2 = _resample_random_order(pnls, random.Random(7))
        assert r1 == r2


# ---------------------------------------------------------------------------
# TestResampleBlockBootstrap
# ---------------------------------------------------------------------------

class TestResampleBlockBootstrap:
    def test_same_length(self):
        pnls = [float(i) for i in range(10)]
        result = _resample_block_bootstrap(pnls, 3, _rng(0))
        assert len(result) == 10

    def test_values_from_original(self):
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _resample_block_bootstrap(pnls, 2, _rng(0))
        for v in result:
            assert v in pnls

    def test_empty_input(self):
        assert _resample_block_bootstrap([], 3, _rng(0)) == []

    def test_block_size_larger_than_n(self):
        pnls = [1.0, 2.0]
        result = _resample_block_bootstrap(pnls, 10, _rng(0))
        assert len(result) == 2
        for v in result:
            assert v in pnls


# ---------------------------------------------------------------------------
# TestResampleRegimeShuffle
# ---------------------------------------------------------------------------

class TestResampleRegimeShuffle:
    def test_same_elements(self):
        pnls = [1.0, 2.0, 3.0, 4.0]
        regimes = ["bull", "bear", "bull", "bear"]
        result = _resample_regime_shuffle(pnls, regimes, _rng(0))
        assert sorted(result) == sorted(pnls)

    def test_regime_composition_preserved(self):
        # bull trades: [1.0, 3.0]; bear trades: [2.0, 4.0]
        # After shuffle: positions 0,2 (bull) contain bull values; positions 1,3 (bear) contain bear values
        pnls = [1.0, 2.0, 3.0, 4.0]
        regimes = ["bull", "bear", "bull", "bear"]
        result = _resample_regime_shuffle(pnls, regimes, _rng(0))
        bull_results = [result[i] for i, r in enumerate(regimes) if r == "bull"]
        bear_results = [result[i] for i, r in enumerate(regimes) if r == "bear"]
        assert sorted(bull_results) == sorted([1.0, 3.0])
        assert sorted(bear_results) == sorted([2.0, 4.0])

    def test_mismatched_lengths_falls_back(self):
        pnls = [1.0, 2.0, 3.0]
        regimes = ["bull", "bear"]   # wrong length
        result = _resample_regime_shuffle(pnls, regimes, _rng(0))
        assert len(result) == 3
        assert sorted(result) == sorted(pnls)

    def test_empty_regimes_falls_back(self):
        pnls = [1.0, 2.0, 3.0]
        result = _resample_regime_shuffle(pnls, [], _rng(0))
        assert len(result) == 3


# ---------------------------------------------------------------------------
# TestVolShock
# ---------------------------------------------------------------------------

class TestVolShock:
    def test_mean_preserved(self):
        pnls = [1.0, -2.0, 3.0, -4.0, 5.0]
        original_mean = sum(pnls) / len(pnls)
        result = _apply_vol_shock(pnls, 2.0)
        result_mean = sum(result) / len(result)
        assert result_mean == pytest.approx(original_mean, abs=1e-10)

    def test_std_scales(self):
        pnls = [1.0, -1.0, 2.0, -2.0]
        import statistics as _stats
        orig_std = _stats.pstdev(pnls)
        result = _apply_vol_shock(pnls, 2.0)
        new_std = _stats.pstdev(result)
        assert new_std == pytest.approx(orig_std * 2.0, rel=1e-6)

    def test_factor_one_unchanged(self):
        pnls = [1.0, -2.0, 3.0]
        assert _apply_vol_shock(pnls, 1.0) == pytest.approx(pnls)

    def test_empty_input(self):
        assert _apply_vol_shock([], 2.0) == []

    def test_larger_deviations(self):
        pnls = [0.0, 10.0, -10.0]
        result = _apply_vol_shock(pnls, 3.0)
        # mean = 0; result = [0, 30, -30]
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(30.0)
        assert result[2] == pytest.approx(-30.0)


# ---------------------------------------------------------------------------
# TestSlippageExpansion
# ---------------------------------------------------------------------------

class TestSlippageExpansion:
    def test_each_trade_reduced(self):
        pnls = [1.0, 2.0, 3.0]
        result = _apply_slippage_expansion(pnls, 0.1)
        assert result == pytest.approx([0.9, 1.9, 2.9])

    def test_empty_input(self):
        assert _apply_slippage_expansion([], 0.5) == []

    def test_negative_pnls_made_worse(self):
        pnls = [-1.0, -2.0]
        result = _apply_slippage_expansion(pnls, 0.5)
        assert result == pytest.approx([-1.5, -2.5])

    def test_zero_cost_unchanged(self):
        pnls = [1.0, -1.0, 2.0]
        assert _apply_slippage_expansion(pnls, 0.0) == pytest.approx(pnls)


# ---------------------------------------------------------------------------
# TestDrawdownClustering
# ---------------------------------------------------------------------------

class TestDrawdownClustering:
    def test_losses_before_wins(self):
        pnls = [5.0, -3.0, 2.0, -1.0, 4.0]
        result = _apply_drawdown_clustering(pnls)
        # First part should be all <= 0, second all > 0
        losses = [p for p in result if p <= 0]
        gains = [p for p in result if p > 0]
        n_losses = len([p for p in pnls if p <= 0])
        n_gains = len([p for p in pnls if p > 0])
        assert result[:n_losses] == sorted(losses)     # worst-first
        assert result[n_losses:] == sorted(gains, reverse=True)   # best-first

    def test_all_losses(self):
        pnls = [-3.0, -1.0, -2.0]
        result = _apply_drawdown_clustering(pnls)
        assert result == sorted(pnls)   # worst first

    def test_all_wins(self):
        pnls = [1.0, 3.0, 2.0]
        result = _apply_drawdown_clustering(pnls)
        assert result == sorted(pnls, reverse=True)   # best first

    def test_same_elements(self):
        pnls = [5.0, -3.0, 2.0, -1.0]
        result = _apply_drawdown_clustering(pnls)
        assert sorted(result) == sorted(pnls)


# ---------------------------------------------------------------------------
# TestConsecutiveLosses
# ---------------------------------------------------------------------------

class TestConsecutiveLosses:
    def test_worst_n_at_front(self):
        pnls = [5.0, -3.0, 2.0, -1.0, -4.0, 3.0]
        n_worst = 3
        result = _apply_consecutive_losses(pnls, n_worst, _rng(0))
        # Front 3 should be the 3 worst: -4, -3, -1
        front = result[:n_worst]
        assert sorted(front) == sorted([-4.0, -3.0, -1.0])

    def test_same_elements(self):
        pnls = [1.0, -2.0, 3.0, -4.0]
        result = _apply_consecutive_losses(pnls, 2, _rng(0))
        assert sorted(result) == sorted(pnls)

    def test_n_larger_than_trades(self):
        pnls = [-1.0, -2.0]
        result = _apply_consecutive_losses(pnls, 100, _rng(0))
        assert sorted(result) == sorted(pnls)

    def test_correct_length(self):
        pnls = [float(i) for i in range(10)]
        result = _apply_consecutive_losses(pnls, 3, _rng(0))
        assert len(result) == 10


# ---------------------------------------------------------------------------
# TestCorrelatedDownside
# ---------------------------------------------------------------------------

class TestCorrelatedDownside:
    def test_losses_amplified(self):
        pnls = [-2.0, -4.0, 3.0]
        result = _apply_correlated_downside(pnls, 1.5)
        assert result[0] == pytest.approx(-3.0)
        assert result[1] == pytest.approx(-6.0)
        assert result[2] == pytest.approx(3.0)   # unchanged

    def test_wins_unchanged(self):
        pnls = [1.0, 2.0, 3.0]
        result = _apply_correlated_downside(pnls, 2.0)
        assert result == pytest.approx(pnls)

    def test_empty_input(self):
        assert _apply_correlated_downside([], 1.5) == []

    def test_factor_one_unchanged(self):
        pnls = [-1.0, 2.0, -3.0]
        result = _apply_correlated_downside(pnls, 1.0)
        assert result == pytest.approx(pnls)


# ---------------------------------------------------------------------------
# TestDominantRegimePnls
# ---------------------------------------------------------------------------

class TestDominantRegimePnls:
    def test_returns_dominant_regime_only(self):
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0]
        regimes = ["bull", "bull", "bull", "bear", "bear"]
        result = _dominant_regime_pnls(pnls, regimes)
        assert result == [1.0, 2.0, 3.0]

    def test_empty_regimes_returns_all(self):
        pnls = [1.0, 2.0]
        result = _dominant_regime_pnls(pnls, [])
        assert result == pnls

    def test_mismatched_length_returns_all(self):
        pnls = [1.0, 2.0, 3.0]
        regimes = ["bull", "bear"]
        result = _dominant_regime_pnls(pnls, regimes)
        assert result == pnls

    def test_single_regime(self):
        pnls = [1.0, 2.0, 3.0]
        regimes = ["bull", "bull", "bull"]
        result = _dominant_regime_pnls(pnls, regimes)
        assert result == pnls


# ---------------------------------------------------------------------------
# TestExtractPnlRegimes
# ---------------------------------------------------------------------------

class TestExtractPnlRegimes:
    def test_filters_none_pnl(self):
        trades = _make_trades([1.0, None, -2.0, None, 3.0])
        pnls, regimes = extract_pnl_regimes(trades)
        assert len(pnls) == 3
        assert len(regimes) == 3

    def test_all_none_returns_empty(self):
        trades = _make_trades([None, None])
        pnls, regimes = extract_pnl_regimes(trades)
        assert pnls == []
        assert regimes == []

    def test_pnl_values_correct(self):
        trades = _make_trades([1.5, -2.5, 3.0])
        pnls, _ = extract_pnl_regimes(trades)
        assert pnls == pytest.approx([1.5, -2.5, 3.0])

    def test_regime_list_same_length_as_pnls(self):
        trades = _make_trades([1.0, 2.0, 3.0])
        pnls, regimes = extract_pnl_regimes(trades)
        assert len(pnls) == len(regimes)

    def test_regime_labels_are_strings(self):
        trades = _make_trades([1.0, -1.0])
        _, regimes = extract_pnl_regimes(trades)
        for r in regimes:
            assert isinstance(r, str)


# ---------------------------------------------------------------------------
# TestRunMonteCarlo
# ---------------------------------------------------------------------------

class TestRunMonteCarlo:
    def _good_trades(self, n=20):
        """20 trades: alternating +2/-1, clearly positive expectancy."""
        pnls = [2.0 if i % 2 == 0 else -1.0 for i in range(n)]
        return _make_trades(pnls)

    def test_raises_insufficient_data(self):
        trades = _make_trades([1.0, 2.0])   # only 2, need >= 5
        params = _default_params()
        with pytest.raises(ValueError, match="usable trades"):
            run_monte_carlo(trades, params, "NIFTY", "30d")

    def test_returns_monte_carlo_summary(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=100)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert isinstance(result, MonteCarloSummary)

    def test_symbol_and_window_in_result(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=100)
        result = run_monte_carlo(trades, params, "BANKNIFTY", "7d")
        assert result.symbol == "BANKNIFTY"
        assert result.window == "7d"

    def test_n_sims_matches(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=150)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert result.n_sims == 150

    def test_n_trades_excludes_no_data(self):
        trades = _make_trades([1.0, None, -1.0, None, 2.0, -1.0, 0.5, 1.5, -0.5, 2.0])
        params = _default_params(n_simulations=50)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert result.n_trades == 8   # 10 - 2 None

    def test_percentile_ordering(self):
        trades = self._good_trades(30)
        params = _default_params(n_simulations=200, seed=1)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert result.return_p5 <= result.return_p25 <= result.return_p50
        assert result.return_p50 <= result.return_p75 <= result.return_p95
        assert result.max_dd_p5 <= result.max_dd_p25 <= result.max_dd_p50
        assert result.max_dd_p50 <= result.max_dd_p75 <= result.max_dd_p95

    def test_survival_plus_ruin_equals_one(self):
        trades = self._good_trades(20)
        params = _default_params(n_simulations=200, seed=2)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert result.probability_of_ruin + result.survival_probability == pytest.approx(1.0, abs=1e-6)

    def test_capital_at_risk_non_negative(self):
        trades = self._good_trades(20)
        params = _default_params(n_simulations=100, seed=3)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert result.capital_at_risk_pct >= 0.0

    def test_to_dict_has_required_keys(self):
        trades = self._good_trades(20)
        params = _default_params(n_simulations=100)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        d = result.to_dict()
        assert "symbol" in d
        assert "distribution" in d
        assert "returns" in d["distribution"]
        assert "max_drawdowns" in d["distribution"]
        assert "tail_risk" in d
        assert "ruin" in d
        assert "recovery" in d
        assert "extremes" in d
        assert "warnings" in d

    def test_high_ruin_scenario(self):
        # Trades all losing: should produce ruin
        pnls = [-5.0] * 30
        trades = _make_trades(pnls)
        params = _default_params(
            n_simulations=100, position_size_pct=50.0, ruin_threshold_pct=30.0, seed=0
        )
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert result.probability_of_ruin > 0.9

    def test_reproducible_with_seed(self):
        trades = self._good_trades(20)
        params1 = _default_params(n_simulations=100, seed=77)
        params2 = _default_params(n_simulations=100, seed=77)
        r1 = run_monte_carlo(trades, params1, "NIFTY", "30d")
        r2 = run_monte_carlo(trades, params2, "NIFTY", "30d")
        assert r1.return_p50 == pytest.approx(r2.return_p50)
        assert r1.probability_of_ruin == pytest.approx(r2.probability_of_ruin)

    def test_all_mc_methods_run(self):
        trades = self._good_trades(20)
        for method in VALID_MC_METHODS:
            params = _default_params(n_simulations=50, method=method, seed=0)
            result = run_monte_carlo(trades, params, "NIFTY", "30d")
            assert isinstance(result, MonteCarloSummary)


# ---------------------------------------------------------------------------
# TestRunStressTests
# ---------------------------------------------------------------------------

class TestRunStressTests:
    def _good_trades(self, n=30):
        pnls = [2.0 if i % 2 == 0 else -1.0 for i in range(n)]
        # Mix in some different regimes via signal_dist_pct and direction
        trades = []
        for i, p in enumerate(pnls):
            trades.append(_make_trade(
                p,
                direction="bullish" if i % 3 != 0 else "bearish",
                signal_dist_pct=2.0 + (i % 3),
            ))
        return trades

    def test_returns_list(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        assert isinstance(results, list)

    def test_returns_8_scenarios(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        assert len(results) == 8

    def test_scenario_names_unique(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        names = [r.scenario for r in results]
        assert len(set(names)) == 8

    def test_expected_scenario_names(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        names = {r.scenario for r in results}
        expected = {
            "consecutive_losses", "vol_shock_1_5x", "vol_shock_2x",
            "slippage_3x", "drawdown_clustering", "correlated_downside",
            "liquidity_deterioration", "regime_concentration",
        }
        assert names == expected

    def test_each_result_is_stress_scenario_result(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        for r in results:
            assert isinstance(r, StressScenarioResult)

    def test_to_dict_structure(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        for r in results:
            d = r.to_dict()
            assert "scenario" in d
            assert "baseline" in d
            assert "stressed" in d
            assert "delta" in d
            assert "warnings" in d

    def test_baseline_same_across_scenarios(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=50, seed=0)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        # All scenarios share the same baseline
        baselines = [(r.baseline_win_rate, r.baseline_expectancy_pct) for r in results]
        assert all(b == baselines[0] for b in baselines)

    def test_empty_trades_returns_empty(self):
        trades = []
        params = _default_params(n_simulations=50)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        assert results == []

    def test_vol_shock_2x_worse_than_1_5x(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=100, seed=0)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        r15 = next(r for r in results if r.scenario == "vol_shock_1_5x")
        r2x = next(r for r in results if r.scenario == "vol_shock_2x")
        # Both stressed max DD should be >= baseline; 2x should be worse than 1.5x
        if r15.stressed_max_dd_p50 is not None and r2x.stressed_max_dd_p50 is not None:
            assert r2x.stressed_max_dd_p50 >= r15.stressed_max_dd_p50

    def test_slippage_reduces_expectancy(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=100, seed=0)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        r = next(r for r in results if r.scenario == "slippage_3x")
        if r.stressed_expectancy_pct is not None and r.baseline_expectancy_pct is not None:
            assert r.stressed_expectancy_pct < r.baseline_expectancy_pct

    def test_liquidity_worse_than_slippage_3x(self):
        trades = self._good_trades()
        params = _default_params(n_simulations=100, seed=0)
        results = run_stress_tests(trades, params, "NIFTY", "30d")
        slip = next(r for r in results if r.scenario == "slippage_3x")
        liq = next(r for r in results if r.scenario == "liquidity_deterioration")
        # liquidity adds 0.9% vs slippage_3x adds 0.2%, so liquidity is harsher
        if (
            slip.stressed_expectancy_pct is not None
            and liq.stressed_expectancy_pct is not None
        ):
            assert liq.stressed_expectancy_pct < slip.stressed_expectancy_pct


# ---------------------------------------------------------------------------
# TestWarnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def _make_summary(self, **kw) -> MonteCarloSummary:
        defaults = dict(
            symbol="NIFTY", window="30d", method="bootstrap", n_sims=500, n_trades=20,
            return_p5=-2.0, return_p25=1.0, return_p50=5.0, return_p75=10.0, return_p95=20.0,
            max_dd_p5=1.0, max_dd_p25=5.0, max_dd_p50=10.0, max_dd_p75=20.0, max_dd_p95=25.0,
            var_pct=-2.0, expected_shortfall_pct=-5.0, capital_at_risk_pct=2.0,
            probability_of_ruin=0.01, ruin_threshold_pct=50.0,
            median_recovery_trades=10.0, p95_recovery_trades=30.0,
            worst_case_return_pct=-20.0, worst_case_drawdown_pct=40.0,
            best_case_return_pct=50.0, survival_probability=0.99,
        )
        defaults.update(kw)
        return MonteCarloSummary(**defaults)

    def test_no_warnings_healthy(self):
        summary = self._make_summary()
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert warnings == []

    def test_insufficient_simulations_warning(self):
        summary = self._make_summary()
        params = _default_params(n_simulations=100)   # < 200
        warnings = _generate_mc_warnings(summary, params)
        assert any("insufficient_simulations" in w for w in warnings)

    def test_fragile_expectancy_warning(self):
        summary = self._make_summary(return_p25=-0.5)   # p25 < 0
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert any("fragile_expectancy" in w for w in warnings)

    def test_high_tail_risk_drawdown_warning(self):
        summary = self._make_summary(max_dd_p95=35.0)   # > 30
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert any("high_tail_risk_drawdown" in w for w in warnings)

    def test_high_tail_risk_shortfall_warning(self):
        summary = self._make_summary(expected_shortfall_pct=-20.0)   # < -15
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert any("high_tail_risk_shortfall" in w for w in warnings)

    def test_high_ruin_probability_warning(self):
        summary = self._make_summary(probability_of_ruin=0.08)   # > 5%
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert any("high_ruin_probability" in w for w in warnings)

    def test_poor_recovery_profile_warning(self):
        summary = self._make_summary(median_recovery_trades=25.0)   # > 20
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert any("poor_recovery_profile" in w for w in warnings)

    def test_no_recovery_warning_when_none(self):
        summary = self._make_summary(median_recovery_trades=None, p95_recovery_trades=None)
        params = _default_params(n_simulations=500)
        warnings = _generate_mc_warnings(summary, params)
        assert not any("poor_recovery" in w for w in warnings)

    def test_multiple_warnings_possible(self):
        summary = self._make_summary(
            return_p25=-2.0,
            max_dd_p95=40.0,
            expected_shortfall_pct=-25.0,
            probability_of_ruin=0.15,
            median_recovery_trades=30.0,
        )
        params = _default_params(n_simulations=100)
        warnings = _generate_mc_warnings(summary, params)
        assert len(warnings) >= 5

    def test_run_monte_carlo_adds_warnings(self):
        # 100 sims → insufficient_simulations warning
        pnls = [2.0 if i % 2 == 0 else -1.0 for i in range(20)]
        trades = _make_trades(pnls)
        params = _default_params(n_simulations=100)
        result = run_monte_carlo(trades, params, "NIFTY", "30d")
        assert isinstance(result.warnings, list)
        # With 100 sims, should have insufficient_simulations warning
        assert any("insufficient_simulations" in w for w in result.warnings)
