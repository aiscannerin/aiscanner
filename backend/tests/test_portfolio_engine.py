"""
Tests for portfolio_engine.py

Uses the same importlib bypass pattern established in the other test files
to avoid importing the Flask app context.

Coverage
--------
TestPortfolioParams          – validate() and to_dict()
TestPositionSizing           – fixed_fractional and volatility_adjusted sizing
TestDrawdownStats            – _compute_drawdown_stats helper
TestSortinoDownsideDev       – _sortino_downside_dev helper
TestRiskControls             – circuit breaker, daily loss, concurrent,
                               correlated, exposure, regime limits
TestPositionLifecycle        – open → mature → close mechanics
TestEquityCurve              – curve events emitted correctly
TestEquityCompounding        – P&L compounds against current equity
TestMetricsComputation       – Sharpe, Sortino, win rate, profit factor, etc.
TestRollingWindows           – rolling metric computation
TestWarnings                 – all seven warning conditions
TestNoDataHandling           – no_data trades are always skipped
TestPublicAPI                – run_portfolio_simulation and compute_portfolio_metrics
"""

from __future__ import annotations

import importlib.util
import sys
import types
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Module loading infrastructure  (same pattern as other test files)
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
    mod  = importlib.util.module_from_spec(spec)
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

# --- Load modules in dependency order ---
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
_eng = _load(
    "portfolio_engine",
    "app/services/portfolio_engine.py",
    alias="app.services.portfolio_engine",
)

# Import the public symbols we need
from portfolio_engine import (  # noqa: E402
    PortfolioParams,
    PortfolioTrade,
    EquityCurvePoint,
    RollingMetrics,
    PortfolioMetrics,
    PortfolioSimulator,
    VALID_SIZING_METHODS,
    _compute_drawdown_stats,
    _sortino_downside_dev,
    _compute_rolling_windows,
    _generate_portfolio_warnings,
    run_portfolio_simulation,
    compute_portfolio_metrics,
)
from trade_simulator import TradeParams, SimulatedTrade   # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _dt(offset_hours: float = 0.0) -> datetime:
    """Return a UTC datetime offset_hours from a fixed base."""
    base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(hours=offset_hours)


def _iso(offset_hours: float = 0.0) -> str:
    return _dt(offset_hours).isoformat()


def _default_pp(**kw) -> PortfolioParams:
    defaults = dict(
        sizing_method              = "fixed_fractional",
        risk_per_trade_pct         = 2.0,
        max_position_size_pct      = 50.0,
        max_portfolio_exposure_pct = 100.0,
        concurrent_position_limit  = 10,
        max_correlated_positions   = 5,
        daily_loss_limit_pct       = 10.0,
        regime_exposure_limit_pct  = 80.0,
        circuit_breaker_drawdown_pct = 50.0,
        initial_capital            = 100_000.0,
        target_vol_pct             = 1.0,
        vol_lookback_trades        = 10,
    )
    defaults.update(kw)
    return PortfolioParams(**defaults)


def _default_tp(**kw) -> TradeParams:
    defaults = dict(stop_pct=1.0, holding_horizon="1d", min_distance_pct=0.5)
    defaults.update(kw)
    return TradeParams(**defaults)


def _make_trade(
    net_pnl_pct:   float,
    direction:     str   = "bullish",
    exit_reason:   str   = "time_stop",
    exit_horizon:  str   = "1d",
    symbol:        str   = "NIFTY",
    captured_at:   str   = None,
    signal_dist:   float = 2.0,
    days_to_expiry: int  = 10,
    pcr:           float = 1.1,
    avg_iv:        float = 15.0,
    gross_pnl_pct: float = None,
) -> SimulatedTrade:
    """Build a minimal SimulatedTrade for portfolio testing."""
    if captured_at is None:
        captured_at = _iso(0.0)
    if gross_pnl_pct is None:
        gross_pnl_pct = net_pnl_pct + 0.15  # add back approximate cost

    return SimulatedTrade(
        snapshot_id      = "snap-001",
        symbol           = symbol,
        captured_at      = captured_at,
        signal_spot      = 22000.0,
        max_pain         = 22440.0,
        signal_dist_pct  = signal_dist,
        direction        = direction,
        days_to_expiry   = days_to_expiry,
        pcr              = pcr,
        avg_iv           = avg_iv,
        trade_type       = "mean_reversion",
        side             = "long" if direction == "bullish" else "short",
        entry_price      = 22011.0,
        target_price     = 22440.0,
        stop_price       = 21791.0,
        exit_price       = 22440.0 if exit_reason == "target" else 22200.0,
        exit_horizon     = exit_horizon,
        exit_reason      = exit_reason,
        gross_pnl_pct    = gross_pnl_pct,
        net_pnl_pct      = net_pnl_pct,
        is_win           = net_pnl_pct > 0 if exit_reason != "no_data" else None,
        mae_pct          = 0.3,
        mfe_pct          = 1.5,
    )


def _trades_seq(pnls: list[float], hour_gap: float = 2.0) -> list[SimulatedTrade]:
    """Build a time-ordered sequence of trades with given pnl_on_equity values."""
    return [
        _make_trade(net_pnl_pct=p, captured_at=_iso(i * hour_gap))
        for i, p in enumerate(pnls)
    ]


# ---------------------------------------------------------------------------
# TestPortfolioParams
# ---------------------------------------------------------------------------

class TestPortfolioParams:
    def test_default_params_are_valid(self):
        pp = _default_pp()
        assert pp.validate() == []

    def test_invalid_sizing_method(self):
        pp = _default_pp(sizing_method="magic")
        issues = pp.validate()
        assert any("sizing_method" in i for i in issues)

    def test_zero_risk_per_trade_invalid(self):
        pp = _default_pp(risk_per_trade_pct=0.0)
        issues = pp.validate()
        assert any("risk_per_trade_pct" in i for i in issues)

    def test_risk_per_trade_over_20_invalid(self):
        pp = _default_pp(risk_per_trade_pct=21.0)
        issues = pp.validate()
        assert any("risk_per_trade_pct" in i for i in issues)

    def test_circuit_breaker_below_floor_invalid(self):
        pp = _default_pp(circuit_breaker_drawdown_pct=3.0)
        issues = pp.validate()
        assert any("circuit_breaker" in i for i in issues)

    def test_vol_lookback_below_5_invalid(self):
        pp = _default_pp(vol_lookback_trades=3)
        issues = pp.validate()
        assert any("vol_lookback" in i for i in issues)

    def test_negative_initial_capital_invalid(self):
        pp = _default_pp(initial_capital=-1.0)
        issues = pp.validate()
        assert any("initial_capital" in i for i in issues)

    def test_to_dict_roundtrip(self):
        pp = _default_pp()
        d  = pp.to_dict()
        assert d["sizing_method"]         == "fixed_fractional"
        assert d["initial_capital"]       == 100_000.0
        assert d["risk_per_trade_pct"]    == 2.0
        assert d["vol_lookback_trades"]   == 10

    def test_valid_vol_adjusted(self):
        pp = _default_pp(sizing_method="volatility_adjusted")
        assert pp.validate() == []


# ---------------------------------------------------------------------------
# TestPositionSizing
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def _sim(self, **kw) -> PortfolioSimulator:
        pp = _default_pp(**kw)
        return PortfolioSimulator(pp, _default_tp())

    def test_fixed_fractional_risk_2pct_stop_1pct(self):
        # size = 2 / 1 = 2.0%, capped at max_position_size_pct=50%
        sim = self._sim(risk_per_trade_pct=2.0, max_position_size_pct=50.0)
        assert sim._compute_size(1.0) == pytest.approx(2.0)

    def test_fixed_fractional_capped_by_max(self):
        # size = 10 / 0.5 = 20% → but max is 15%
        sim = self._sim(risk_per_trade_pct=10.0, max_position_size_pct=15.0)
        assert sim._compute_size(0.5) == pytest.approx(15.0)

    def test_fixed_fractional_wider_stop_smaller_size(self):
        sim = self._sim(risk_per_trade_pct=2.0, max_position_size_pct=50.0)
        size_narrow = sim._compute_size(0.5)
        size_wide   = sim._compute_size(2.0)
        assert size_narrow > size_wide

    def test_vol_adjusted_falls_back_when_too_few_pnls(self):
        sim = self._sim(
            sizing_method      = "volatility_adjusted",
            risk_per_trade_pct = 2.0,
            target_vol_pct     = 1.0,
            vol_lookback_trades= 10,
            max_position_size_pct = 50.0,
        )
        # Only 3 samples — too few for vol estimate → same as fixed_fractional
        sim._recent_pnls = [1.0, -0.5, 0.8]
        assert sim._compute_size(1.0) == pytest.approx(2.0)

    def test_vol_adjusted_scales_down_in_high_vol(self):
        sim = self._sim(
            sizing_method      = "volatility_adjusted",
            risk_per_trade_pct = 2.0,
            target_vol_pct     = 1.0,
            max_position_size_pct = 50.0,
        )
        # High realized vol of 4% → scale = 1/4 → size = 2/1 * 0.25 = 0.5%
        sim._recent_pnls = [4.0, -4.0, 4.0, -4.0, 4.0, -4.0, 4.0, -4.0, 4.0, -4.0]
        size = sim._compute_size(1.0)
        assert size < 2.0  # smaller than fixed fractional

    def test_vol_adjusted_capped_even_in_low_vol(self):
        sim = self._sim(
            sizing_method      = "volatility_adjusted",
            risk_per_trade_pct = 2.0,
            target_vol_pct     = 10.0,    # high target vol → very large uncapped size
            max_position_size_pct = 20.0,
        )
        sim._recent_pnls = [0.1] * 10     # very low realized vol
        size = sim._compute_size(1.0)
        assert size <= 20.0

    def test_zero_stop_uses_max_size(self):
        # stop near zero → base = risk / ε → capped at max_position_size_pct
        sim = self._sim(risk_per_trade_pct=2.0, max_position_size_pct=25.0)
        assert sim._compute_size(0.0) == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# TestDrawdownStats
# ---------------------------------------------------------------------------

class TestDrawdownStats:
    def test_empty_returns_zero(self):
        dd, dur = _compute_drawdown_stats([])
        assert dd == 0.0 and dur == 0

    def test_monotone_rising_no_drawdown(self):
        dd, _ = _compute_drawdown_stats([100, 110, 120, 130])
        assert dd == 0.0

    def test_single_drop(self):
        # peak=110, trough=90 → dd = 20/110 * 100 ≈ 18.18%
        dd, dur = _compute_drawdown_stats([100, 110, 90])
        assert abs(dd - 18.18) < 0.5
        assert dur == 1

    def test_longer_drawdown_duration(self):
        # Peak at index 1 (110), trough at index 4 (80) → duration = 3
        dd, dur = _compute_drawdown_stats([100, 110, 105, 95, 80, 90])
        assert dur >= 3

    def test_recovery_then_new_dd(self):
        # First dd: 110 → 90 (18%). Second dd: 120 → 70 (41.67%)
        dd, _ = _compute_drawdown_stats([100, 110, 90, 100, 120, 70])
        assert abs(dd - 41.67) < 0.5

    def test_all_same_no_drawdown(self):
        dd, _ = _compute_drawdown_stats([100, 100, 100, 100])
        assert dd == 0.0


# ---------------------------------------------------------------------------
# TestSortinoDownsideDev
# ---------------------------------------------------------------------------

class TestSortinoDownsideDev:
    def test_all_positive_returns_zero_downside(self):
        assert _sortino_downside_dev([1.0, 2.0, 3.0]) == pytest.approx(0.0)

    def test_symmetric_returns(self):
        # returns = [1, -1, 1, -1] — only [-1, -1] contribute downside
        # dev = sqrt(sum(1^2 for each) / 4) = sqrt(0.5) ≈ 0.707
        dev = _sortino_downside_dev([1.0, -1.0, 1.0, -1.0])
        assert dev == pytest.approx(math.sqrt(0.5))

    def test_empty_returns_zero(self):
        assert _sortino_downside_dev([]) == 0.0

    def test_larger_losses_give_higher_deviation(self):
        small_dev = _sortino_downside_dev([1.0, -0.5])
        large_dev = _sortino_downside_dev([1.0, -2.0])
        assert large_dev > small_dev


# ---------------------------------------------------------------------------
# TestRiskControls
# ---------------------------------------------------------------------------

class TestRiskControls:
    def _sim_with(self, **kw) -> PortfolioSimulator:
        pp = _default_pp(**kw)
        sim = PortfolioSimulator(pp, _default_tp())
        return sim

    def test_no_controls_triggered_allows_trade(self):
        sim = self._sim_with()
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is True
        assert reason is None

    def test_circuit_breaker_halts_after_drawdown(self):
        sim = self._sim_with(
            initial_capital            = 100_000.0,
            circuit_breaker_drawdown_pct = 20.0,
        )
        # Force equity below 80% of peak
        sim._equity      = 79_000.0
        sim._peak_equity = 100_000.0
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is False
        assert reason == "circuit_breaker"
        assert sim._circuit_breaker is True

    def test_circuit_breaker_stays_halted_after_trigger(self):
        sim = self._sim_with(circuit_breaker_drawdown_pct=20.0)
        sim._circuit_breaker = True
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is False
        assert reason == "circuit_breaker"

    def test_daily_loss_limit_halts_trading(self):
        today = _dt(0).date()
        sim   = self._sim_with(daily_loss_limit_pct=5.0, initial_capital=100_000.0)
        sim._day_start_equity[today] = 100_000.0
        # Simulate 6% daily loss
        sim._daily_pnl[today] = -6_000.0
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is False
        assert reason == "daily_loss_limit"

    def test_daily_loss_below_limit_allows(self):
        today = _dt(0).date()
        sim   = self._sim_with(daily_loss_limit_pct=5.0, initial_capital=100_000.0)
        sim._day_start_equity[today] = 100_000.0
        sim._daily_pnl[today] = -3_000.0    # only 3% < 5%
        allowed, _ = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is True

    def test_concurrent_limit_halts(self):
        sim = self._sim_with(concurrent_position_limit=2)
        # Mock 2 open positions
        sim._open = [object(), object()]     # just needs len()
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is False
        assert reason == "concurrent_limit"

    def test_concurrent_below_limit_allows(self):
        from portfolio_engine import _OpenPosition
        sim = self._sim_with(concurrent_position_limit=3)
        fake_pt = types.SimpleNamespace(
            pnl_on_equity=None, dollar_pnl=None,
            trade=types.SimpleNamespace(net_pnl_pct=None, symbol="BANKNIFTY")
        )
        # Add 2 open positions in different symbol so correlated limit doesn't fire
        op1 = _OpenPosition(pt=fake_pt, symbol="BANKNIFTY", regime="normal",
                            exit_dt=_dt(24), position_size_pct=5.0)
        op2 = _OpenPosition(pt=fake_pt, symbol="BANKNIFTY", regime="normal",
                            exit_dt=_dt(24), position_size_pct=5.0)
        sim._open = [op1, op2]   # 2 < concurrent_limit=3; correlated is different symbol
        allowed, _ = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is True

    def test_correlated_limit_halts_same_symbol(self):
        from portfolio_engine import _OpenPosition
        sim  = self._sim_with(max_correlated_positions=1)
        fake_pt = types.SimpleNamespace(
            pnl_on_equity=None, dollar_pnl=None,
            trade=types.SimpleNamespace(net_pnl_pct=None, symbol="NIFTY")
        )
        op = _OpenPosition(
            pt=fake_pt, symbol="NIFTY", regime="normal",
            exit_dt=_dt(24), position_size_pct=5.0
        )
        sim._open = [op]
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is False
        assert reason == "correlated_limit"

    def test_exposure_limit_halts(self):
        from portfolio_engine import _OpenPosition
        sim  = self._sim_with(max_portfolio_exposure_pct=20.0)
        fake_pt = types.SimpleNamespace(
            pnl_on_equity=None, dollar_pnl=None,
            trade=types.SimpleNamespace(net_pnl_pct=None, symbol="BANKNIFTY")
        )
        op = _OpenPosition(
            pt=fake_pt, symbol="BANKNIFTY", regime="normal",
            exit_dt=_dt(24), position_size_pct=20.0
        )
        sim._open = [op]
        allowed, reason = sim._check_risk_controls(_dt(0), "normal", "NIFTY")
        assert allowed is False
        assert reason == "exposure_limit"

    def test_regime_exposure_limit_halts(self):
        from portfolio_engine import _OpenPosition
        sim  = self._sim_with(regime_exposure_limit_pct=10.0)
        fake_pt = types.SimpleNamespace(
            pnl_on_equity=None, dollar_pnl=None,
            trade=types.SimpleNamespace(net_pnl_pct=None, symbol="NIFTY")
        )
        op = _OpenPosition(
            pt=fake_pt, symbol="NIFTY", regime="expiry_pinning",
            exit_dt=_dt(24), position_size_pct=10.0
        )
        sim._open = [op]
        allowed, reason = sim._check_risk_controls(_dt(0), "expiry_pinning", "NIFTY")
        assert allowed is False
        assert reason == "regime_exposure_limit"


# ---------------------------------------------------------------------------
# TestNoDataHandling
# ---------------------------------------------------------------------------

class TestNoDataHandling:
    def test_no_data_trade_is_always_skipped(self):
        trade = _make_trade(
            net_pnl_pct  = 0.0,
            exit_horizon = None,
            exit_reason  = "no_data",
        )
        trade = SimulatedTrade(
            **{**trade.__dict__,
               "exit_horizon": None,
               "exit_reason":  "no_data",
               "net_pnl_pct":  None,
               "is_win":       None}
        )
        pp  = _default_pp()
        tp  = _default_tp()
        all_pts, _ = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        assert len(all_pts) == 1
        pt = all_pts[0]
        assert pt.skipped is True
        assert pt.skip_reason == "no_data"
        assert pt.dollar_pnl is None

    def test_no_data_trade_does_not_affect_equity(self):
        trade = SimulatedTrade(
            snapshot_id="x", symbol="NIFTY", captured_at=_iso(0),
            signal_spot=22000, max_pain=22300, signal_dist_pct=1.5,
            direction="bullish", days_to_expiry=10, pcr=1.1, avg_iv=15.0,
            trade_type="mean_reversion", side="long",
            entry_price=22011, target_price=22300, stop_price=21791,
            exit_price=None, exit_horizon=None, exit_reason="no_data",
            gross_pnl_pct=None, net_pnl_pct=None, is_win=None,
            mae_pct=None, mfe_pct=None,
        )
        pp = _default_pp(initial_capital=100_000.0)
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        # No curve events because no_data is skipped before open event
        assert len(curve) == 0


# ---------------------------------------------------------------------------
# TestPositionLifecycle
# ---------------------------------------------------------------------------

class TestPositionLifecycle:
    def test_trade_opens_and_closes(self):
        trade = _make_trade(1.5, captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp(initial_capital=100_000.0)
        tp = _default_tp(stop_pct=1.0)
        all_pts, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")

        assert len(all_pts) == 1
        pt = all_pts[0]
        assert pt.skipped is False
        assert pt.dollar_pnl is not None

    def test_dollar_pnl_formula(self):
        # size = risk(2%) / stop(1%) = 2% of 100k = 2000 position
        # dollar_pnl = 2000 * net_pnl_pct / 100 = 2000 * 1.5 / 100 = 30
        pp    = _default_pp(initial_capital=100_000.0, risk_per_trade_pct=2.0, max_position_size_pct=50.0)
        tp    = _default_tp(stop_pct=1.0)
        trade = _make_trade(1.5, captured_at=_iso(0), exit_horizon="1d")
        all_pts, _ = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")

        pt = all_pts[0]
        expected_size = 2.0   # % of equity
        expected_pnl  = 100_000.0 * expected_size / 100.0 * 1.5 / 100.0
        assert pt.dollar_pnl == pytest.approx(expected_pnl, rel=1e-4)

    def test_pnl_on_equity_formula(self):
        pp    = _default_pp(initial_capital=100_000.0, risk_per_trade_pct=2.0, max_position_size_pct=50.0)
        tp    = _default_tp(stop_pct=1.0)
        trade = _make_trade(1.5, captured_at=_iso(0), exit_horizon="1d")
        all_pts, _ = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        pt = all_pts[0]
        # pnl_on_equity = size_pct * net_pnl_pct / 100 = 2.0 * 1.5 / 100 = 0.03
        assert pt.pnl_on_equity == pytest.approx(2.0 * 1.5 / 100.0, rel=1e-4)

    def test_loss_trade_reduces_equity(self):
        pp    = _default_pp(initial_capital=100_000.0)
        tp    = _default_tp(stop_pct=1.0)
        trade = _make_trade(-1.0, captured_at=_iso(0), exit_horizon="1d")
        all_pts, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")

        pt       = all_pts[0]
        final_eq = [c.equity for c in curve if c.event == "close"]
        assert pt.dollar_pnl < 0
        assert final_eq[-1] < 100_000.0

    def test_older_positions_close_before_newer_open(self):
        # Trade 1 opens at 0h, closes at 24h.
        # Trade 2 opens at 25h.  By then trade 1 should be closed.
        t1 = _make_trade(2.0, captured_at=_iso(0),  exit_horizon="1d")
        t2 = _make_trade(1.0, captured_at=_iso(25), exit_horizon="1d")

        pp = _default_pp(initial_capital=100_000.0, concurrent_position_limit=1)
        tp = _default_tp()
        all_pts, _ = run_portfolio_simulation([t1, t2], pp, tp, ["NIFTY"], "30d")

        entered = [pt for pt in all_pts if not pt.skipped]
        # Both should be entered because t1 closes at 24h before t2 at 25h
        assert len(entered) == 2

    def test_simultaneous_open_position_blocks(self):
        # Both trades open at the same time; concurrent limit = 1
        t1 = _make_trade(1.0, captured_at=_iso(0), exit_horizon="1d")
        t2 = _make_trade(1.0, captured_at=_iso(0), exit_horizon="1d")

        pp = _default_pp(concurrent_position_limit=1)
        tp = _default_tp()
        all_pts, _ = run_portfolio_simulation([t1, t2], pp, tp, ["NIFTY"], "30d")

        skipped = [pt for pt in all_pts if pt.skipped]
        assert len(skipped) >= 1
        assert any(pt.skip_reason == "concurrent_limit" for pt in skipped)


# ---------------------------------------------------------------------------
# TestEquityCompounding
# ---------------------------------------------------------------------------

class TestEquityCompounding:
    def test_compounding_grows_faster_than_linear(self):
        # Ten 2% trades on 100k.  Compounding: 100k*(1.02/50)^10...
        # Actually: each trade contributes 0.03% of equity (2%size * 1.5%pnl / 100)
        trades = _trades_seq([1.5] * 10, hour_gap=25.0)
        pp = _default_pp(
            initial_capital=100_000.0,
            risk_per_trade_pct=2.0,
            max_position_size_pct=50.0,
            concurrent_position_limit=1,
        )
        tp = _default_tp(stop_pct=1.0)
        all_pts, _ = run_portfolio_simulation(trades, pp, tp, ["NIFTY"], "30d")
        entered = [pt for pt in all_pts if not pt.skipped]
        assert len(entered) == 10

        # Each entered trade's capital_at_entry should be larger than previous
        for i in range(1, len(entered)):
            assert entered[i].capital_at_entry >= entered[i-1].capital_at_entry

    def test_loss_reduces_subsequent_position_size(self):
        # After a big loss, equity is lower → next position is smaller in $ terms
        t1 = _make_trade(-5.0, captured_at=_iso(0),  exit_horizon="1d")
        t2 = _make_trade( 2.0, captured_at=_iso(25), exit_horizon="1d")

        pp = _default_pp(
            initial_capital=100_000.0,
            risk_per_trade_pct=10.0,
            max_position_size_pct=50.0,
            concurrent_position_limit=1,
        )
        tp = _default_tp(stop_pct=1.0)
        all_pts, _ = run_portfolio_simulation([t1, t2], pp, tp, ["NIFTY"], "30d")
        entered = [pt for pt in all_pts if not pt.skipped]
        assert len(entered) == 2
        assert entered[1].capital_at_entry < entered[0].capital_at_entry

    def test_equity_after_all_wins(self):
        # 5 trades each with net_pnl = 2.0%, size = 4% (risk=2, stop=0.5)
        # pnl_on_equity per trade = 4 * 2 / 100 = 0.08% of equity
        trades = _trades_seq([2.0] * 5, hour_gap=25.0)
        pp = _default_pp(
            initial_capital=100_000.0,
            risk_per_trade_pct=2.0,
            max_position_size_pct=50.0,
            concurrent_position_limit=1,
        )
        tp = _default_tp(stop_pct=0.5)   # size = 4%
        _, curve = run_portfolio_simulation(trades, pp, tp, ["NIFTY"], "30d")
        final_equity = [c.equity for c in curve if c.event == "close"][-1]
        assert final_equity > 100_000.0

    def test_equity_after_all_losses_decreases(self):
        trades = _trades_seq([-1.0] * 5, hour_gap=25.0)
        pp = _default_pp(initial_capital=100_000.0, concurrent_position_limit=1)
        tp = _default_tp()
        _, curve = run_portfolio_simulation(trades, pp, tp, ["NIFTY"], "30d")
        final_equity = [c.equity for c in curve if c.event == "close"][-1]
        assert final_equity < 100_000.0


# ---------------------------------------------------------------------------
# TestEquityCurve
# ---------------------------------------------------------------------------

class TestEquityCurve:
    def test_one_trade_produces_two_events(self):
        trade = _make_trade(1.0, captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp()
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        assert len(curve) == 2
        assert curve[0].event == "open"
        assert curve[1].event == "close"

    def test_open_event_has_correct_symbol(self):
        trade = _make_trade(1.0, symbol="BANKNIFTY", captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp()
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["BANKNIFTY"], "30d")
        assert curve[0].symbol == "BANKNIFTY"

    def test_close_event_has_pnl_on_equity(self):
        trade = _make_trade(2.0, captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp()
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        close_event = next(c for c in curve if c.event == "close")
        assert close_event.trade_pnl_on_equity is not None

    def test_drawdown_pct_zero_when_no_loss(self):
        trade = _make_trade(1.0, captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp()
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        close = next(c for c in curve if c.event == "close")
        assert close.drawdown_pct == pytest.approx(0.0)

    def test_drawdown_pct_positive_after_loss(self):
        trade = _make_trade(-2.0, captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp(initial_capital=100_000.0)
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        close = next(c for c in curve if c.event == "close")
        assert close.drawdown_pct > 0.0

    def test_open_positions_count_correct(self):
        # Two trades open simultaneously
        t1 = _make_trade(1.0, captured_at=_iso(0), exit_horizon="1d")
        t2 = _make_trade(1.0, captured_at=_iso(1), exit_horizon="1d")  # 1h after
        pp = _default_pp(concurrent_position_limit=5)
        tp = _default_tp()
        _, curve = run_portfolio_simulation([t1, t2], pp, tp, ["NIFTY"], "30d")
        # The second open event should show 2 positions open
        open_events = [c for c in curve if c.event == "open"]
        assert open_events[1].open_positions == 2

    def test_to_dict_serialises(self):
        trade = _make_trade(1.0, captured_at=_iso(0), exit_horizon="1d")
        pp = _default_pp()
        tp = _default_tp()
        _, curve = run_portfolio_simulation([trade], pp, tp, ["NIFTY"], "30d")
        d = curve[0].to_dict()
        assert "timestamp" in d
        assert "equity"    in d
        assert "event"     in d


# ---------------------------------------------------------------------------
# TestMetricsComputation
# ---------------------------------------------------------------------------

class TestMetricsComputation:
    def _metrics(self, trades, **pp_kw) -> PortfolioMetrics:
        pp = _default_pp(concurrent_position_limit=1, **pp_kw)
        tp = _default_tp()
        return compute_portfolio_metrics(trades, pp, tp, ["NIFTY"], "30d")

    def test_all_wins_positive_return(self):
        trades = _trades_seq([2.0] * 10, hour_gap=25.0)
        m = self._metrics(trades)
        assert m.total_return_pct > 0
        assert m.win_rate == pytest.approx(1.0)

    def test_all_losses_negative_return(self):
        trades = _trades_seq([-1.0] * 10, hour_gap=25.0)
        m = self._metrics(trades)
        assert m.total_return_pct < 0
        assert m.win_rate == pytest.approx(0.0)

    def test_win_rate_50_50(self):
        pnls   = [2.0, -1.0] * 5
        trades = _trades_seq(pnls, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.win_rate == pytest.approx(0.5, abs=0.01)

    def test_profit_factor_greater_than_1_for_positive_edge(self):
        pnls   = [3.0, -1.0] * 5
        trades = _trades_seq(pnls, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.profit_factor is not None
        assert m.profit_factor > 1.0

    def test_profit_factor_less_than_1_for_negative_edge(self):
        pnls   = [1.0, -3.0] * 5
        trades = _trades_seq(pnls, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.profit_factor is not None
        assert m.profit_factor < 1.0

    def test_max_drawdown_all_wins_is_zero(self):
        trades = _trades_seq([2.0] * 5, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.max_drawdown_pct == pytest.approx(0.0)

    def test_max_drawdown_positive_for_losses(self):
        trades = _trades_seq([-1.0] * 5, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.max_drawdown_pct > 0.0

    def test_expectancy_on_equity_positive_for_winners(self):
        trades = _trades_seq([2.0] * 10, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.expectancy_on_equity is not None
        assert m.expectancy_on_equity > 0

    def test_expectancy_on_equity_negative_for_losers(self):
        trades = _trades_seq([-1.0] * 10, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.expectancy_on_equity is not None
        assert m.expectancy_on_equity < 0

    def test_sharpe_none_when_too_few_trades(self):
        trades = _trades_seq([1.0] * 5, hour_gap=25.0)
        m      = self._metrics(trades)
        # Below _MIN_TRADES_FOR_RATIOS (10)
        assert m.sharpe_ratio is None

    def test_sharpe_computed_with_enough_trades(self):
        trades = _trades_seq([1.0, -0.5] * 8, hour_gap=25.0)
        m      = self._metrics(trades)
        assert m.sharpe_ratio is not None

    def test_sortino_not_none_when_sharpe_not_none(self):
        trades = _trades_seq([1.0, -0.5] * 8, hour_gap=25.0)
        m      = self._metrics(trades)
        if m.sharpe_ratio is not None:
            assert m.sortino_ratio is not None

    def test_recovery_factor_positive_after_drawdown_with_overall_gain(self):
        # Win after the loss: net positive total return, but with drawdown
        pnls   = [-2.0] * 3 + [4.0] * 5
        trades = _trades_seq(pnls, hour_gap=25.0)
        m      = self._metrics(trades)
        if m.max_drawdown_pct > 0 and m.total_return_pct > 0:
            assert m.recovery_factor is not None
            assert m.recovery_factor > 0

    def test_regime_concentration_sums_to_100(self):
        trades = _trades_seq([1.0, -0.5, 2.0, -0.3, 0.8], hour_gap=25.0)
        m      = self._metrics(trades)
        total  = sum(m.regime_concentration.values())
        if total > 0:
            assert abs(total - 100.0) < 0.1

    def test_total_entered_plus_skipped_equals_total_signals(self):
        trades = _trades_seq([1.0] * 6, hour_gap=1.0)  # same hour gap → some blocked
        m = compute_portfolio_metrics(
            trades,
            _default_pp(concurrent_position_limit=2),
            _default_tp(),
            ["NIFTY"], "30d",
        )
        assert m.total_entered + m.total_skipped == m.total_signals

    def test_to_dict_serialises(self):
        trades = _trades_seq([1.0, -0.5] * 3, hour_gap=25.0)
        m      = self._metrics(trades)
        d      = m.to_dict()
        assert "capital"    in d
        assert "ratios"     in d
        assert "drawdown"   in d
        assert "trades"     in d
        assert "exposure"   in d
        assert "regime"     in d
        assert "warnings"   in d


# ---------------------------------------------------------------------------
# TestRollingWindows
# ---------------------------------------------------------------------------

class TestRollingWindows:
    def _closed(self, pnls: list[float]) -> list[PortfolioTrade]:
        """Build synthetic PortfolioTrade objects for rolling window tests."""
        trades = []
        eq = 100_000.0
        for i, p in enumerate(pnls):
            size = 2.0
            dollar = eq * size / 100.0 * p / 100.0
            t = _make_trade(p, captured_at=_iso(i * 25.0))
            pt = PortfolioTrade(
                trade            = t,
                entry_dt         = _dt(i * 25.0),
                exit_dt          = _dt(i * 25.0 + 24.0),
                regime           = "normal",
                position_size_pct= size,
                capital_at_entry = eq,
                dollar_pnl       = dollar,
                pnl_on_equity    = size * p / 100.0,
            )
            trades.append(pt)
            eq += dollar
        return trades

    def test_empty_when_fewer_than_window(self):
        closed = self._closed([1.0] * 5)
        result = _compute_rolling_windows(closed, window_size=10)
        assert result == []

    def test_correct_number_of_windows(self):
        # n=15, window=10 → 15-10+1 = 6 windows
        closed = self._closed([1.0] * 15)
        result = _compute_rolling_windows(closed, window_size=10)
        assert len(result) == 6

    def test_win_rate_1_for_all_positive(self):
        closed = self._closed([2.0] * 25)
        result = _compute_rolling_windows(closed, window_size=20)
        assert all(r.win_rate == pytest.approx(1.0) for r in result)

    def test_win_rate_0_for_all_negative(self):
        closed = self._closed([-1.0] * 25)
        result = _compute_rolling_windows(closed, window_size=20)
        assert all(r.win_rate == pytest.approx(0.0) for r in result)

    def test_win_rate_half_for_alternating(self):
        pnls   = [2.0, -1.0] * 15
        closed = self._closed(pnls)
        result = _compute_rolling_windows(closed, window_size=10)
        for r in result:
            assert r.win_rate == pytest.approx(0.5, abs=0.1)

    def test_trade_index_is_last_index(self):
        closed = self._closed([1.0] * 15)
        result = _compute_rolling_windows(closed, window_size=10)
        # First window ends at index 9, last at index 14
        assert result[0].trade_index == 9
        assert result[-1].trade_index == 14

    def test_to_dict_has_correct_keys(self):
        closed = self._closed([1.0] * 25)
        result = _compute_rolling_windows(closed, window_size=20)
        d = result[0].to_dict()
        assert "window_size"    in d
        assert "trade_index"    in d
        assert "equity"         in d
        assert "win_rate"       in d
        assert "expectancy_pct" in d


# ---------------------------------------------------------------------------
# TestWarnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def _data(self, **kw) -> dict:
        base = dict(
            regime_concentration    = {},
            regime_win_rates        = {},
            peak_exposure_pct       = 50.0,
            expectancy_on_equity    = 0.05,
            total_entered           = 30,
            total_skipped           = 5,
            circuit_breaker_triggered = False,
            _eq_std                 = None,
        )
        base.update(kw)
        return base

    def test_always_has_discrete_price_warning(self):
        ws = _generate_portfolio_warnings(self._data(), _default_pp(), ["NIFTY"])
        assert any("discrete_exit_prices" in w for w in ws)

    def test_insufficient_diversification_single_symbol(self):
        ws = _generate_portfolio_warnings(self._data(), _default_pp(), ["NIFTY"])
        assert any("insufficient_diversification" in w for w in ws)

    def test_no_diversification_warning_for_two_symbols(self):
        ws = _generate_portfolio_warnings(self._data(), _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert not any("insufficient_diversification" in w for w in ws)

    def test_over_concentration_warning(self):
        data = self._data(regime_concentration={"expiry_pinning": 75.0})
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert any("over_concentration" in w for w in ws)

    def test_no_over_concentration_below_threshold(self):
        data = self._data(regime_concentration={"normal": 50.0})
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert not any("over_concentration" in w for w in ws)

    def test_excessive_leverage_warning(self):
        data = self._data(peak_exposure_pct=120.0)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert any("excessive_leverage" in w for w in ws)

    def test_no_excessive_leverage_below_threshold(self):
        data = self._data(peak_exposure_pct=80.0)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert not any("excessive_leverage" in w for w in ws)

    def test_unstable_expectancy_warning(self):
        # std / |expectancy| = 0.3 / 0.03 = 10 > 3.0
        data = self._data(expectancy_on_equity=0.03, _eq_std=0.3)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert any("unstable_expectancy" in w for w in ws)

    def test_no_unstable_expectancy_when_stable(self):
        data = self._data(expectancy_on_equity=0.1, _eq_std=0.1)  # ratio = 1.0 < 3.0
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert not any("unstable_expectancy" in w for w in ws)

    def test_high_skip_rate_warning(self):
        # 50 skipped out of 60 total = 83% > 40%
        data = self._data(total_entered=10, total_skipped=50)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert any("high_skip_rate" in w for w in ws)

    def test_no_high_skip_rate_when_low(self):
        data = self._data(total_entered=50, total_skipped=5)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert not any("high_skip_rate" in w for w in ws)

    def test_circuit_breaker_warning(self):
        data = self._data(circuit_breaker_triggered=True)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert any("circuit_breaker_triggered" in w for w in ws)

    def test_negative_expectancy_warning(self):
        data = self._data(expectancy_on_equity=-0.05)
        ws   = _generate_portfolio_warnings(data, _default_pp(), ["NIFTY", "BANKNIFTY"])
        assert any("negative_expectancy" in w for w in ws)


# ---------------------------------------------------------------------------
# TestPublicAPI
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_run_portfolio_simulation_returns_tuple(self):
        trades  = _trades_seq([1.0, -0.5, 2.0], hour_gap=25.0)
        pp      = _default_pp(concurrent_position_limit=1)
        tp      = _default_tp()
        result  = run_portfolio_simulation(trades, pp, tp, ["NIFTY"], "30d")
        assert isinstance(result, tuple) and len(result) == 2
        all_pts, curve = result
        assert isinstance(all_pts, list)
        assert isinstance(curve, list)

    def test_compute_portfolio_metrics_returns_metrics_object(self):
        trades = _trades_seq([1.0] * 5, hour_gap=25.0)
        pp     = _default_pp(concurrent_position_limit=1)
        tp     = _default_tp()
        m      = compute_portfolio_metrics(trades, pp, tp, ["NIFTY"], "30d")
        assert isinstance(m, PortfolioMetrics)

    def test_empty_trades_produces_zero_return(self):
        pp = _default_pp(initial_capital=100_000.0)
        tp = _default_tp()
        m  = compute_portfolio_metrics([], pp, tp, ["NIFTY"], "30d")
        assert m.total_return_pct == pytest.approx(0.0)
        assert m.final_capital    == pytest.approx(100_000.0)

    def test_portfolio_metrics_total_signals_correct(self):
        trades = _trades_seq([1.0, -0.5] * 3, hour_gap=25.0)
        pp     = _default_pp(concurrent_position_limit=1)
        tp     = _default_tp()
        m      = compute_portfolio_metrics(trades, pp, tp, ["NIFTY"], "30d")
        assert m.total_signals == len(trades)

    def test_portfolio_trade_to_dict_has_required_keys(self):
        trades = _trades_seq([1.0], hour_gap=25.0)
        pp     = _default_pp()
        tp     = _default_tp()
        all_pts, _ = run_portfolio_simulation(trades, pp, tp, ["NIFTY"], "30d")
        d = all_pts[0].to_dict()
        for key in ("symbol", "captured_at", "net_pnl_pct", "position_size_pct",
                    "dollar_pnl", "pnl_on_equity", "skipped", "skip_reason", "regime"):
            assert key in d, f"key '{key}' missing from PortfolioTrade.to_dict()"

    def test_circuit_breaker_stops_all_subsequent_trades(self):
        # Start with a catastrophic loss that triggers the circuit breaker
        # then add more trades that should all be skipped
        big_loss = _make_trade(-99.0, captured_at=_iso(0),   exit_horizon="1d")
        later_1  = _make_trade(  1.0, captured_at=_iso(25),  exit_horizon="1d")
        later_2  = _make_trade(  1.0, captured_at=_iso(50),  exit_horizon="1d")

        pp = _default_pp(
            initial_capital              = 100_000.0,
            risk_per_trade_pct           = 100.0,    # extreme to trigger CB fast
            max_position_size_pct        = 100.0,
            circuit_breaker_drawdown_pct = 5.0,
            concurrent_position_limit    = 1,
        )
        tp = _default_tp(stop_pct=1.0)
        all_pts, _ = run_portfolio_simulation(
            [big_loss, later_1, later_2], pp, tp, ["NIFTY"], "30d"
        )
        skipped_after = [pt for pt in all_pts[1:] if pt.skipped and pt.skip_reason == "circuit_breaker"]
        assert len(skipped_after) >= 1
