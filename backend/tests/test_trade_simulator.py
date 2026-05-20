"""
Unit tests for trade_simulator.py

Pure computation — no database, no network, no Flask app.
ReplayPoint objects are built from minimal dataclasses that satisfy the
duck-typing contract expected by the simulator.

Coverage
--------
TestTradeParams         — validation, round_trip_cost
TestDetermineSide       — all 4 trade types × 2 directions
TestEntryPrice          — slippage on entry
TestComputeTarget       — mean_reversion (with/without target_pct), continuation, directional
TestComputeStop         — long and short
TestGrossPnl            — long and short, correctness
TestComputeMaeMfe       — long and short, empty case
TestMaxDrawdown         — flat, always-win, single-loss, progressive
TestSimulateTrade       — target_hit, stop_hit, time_stop, no_data,
                          continuation, long/short override
TestBuildExpectancyReport
                        — all wins, all losses, mixed, no simulated, no_data rate
TestWarnings            — param-level and result-level warnings
TestRegressionExpectancy
                        — expectancy formula correctness
"""

import importlib.util
import math
import sys
import os
import types
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ── Stub Flask / SQLAlchemy ──────────────────────────────────────────────────

def _pkg(name, **attrs):
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = []
        m.__package__ = name
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]

def _mod(name, **attrs):
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
_mod("app.services.max_pain_scanner_service",
     DEFAULT_FO_UNIVERSE=["NIFTY", "BANKNIFTY"])

# ── Load modules by path ──────────────────────────────────────────────────────

def _load(short, rel, alias=None):
    path = os.path.join(os.path.dirname(__file__), "..", rel)
    spec = importlib.util.spec_from_file_location(short, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[short] = mod
    if alias:
        sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod

_replay  = _load("max_pain_replay_service",
                 "app/services/max_pain_replay_service.py",
                 "app.services.max_pain_replay_service")
_regime  = _load("regime_classifier",
                 "app/services/regime_classifier.py",
                 "app.services.regime_classifier")
_val     = _load("max_pain_validation_service",
                 "app/services/max_pain_validation_service.py",
                 "app.services.max_pain_validation_service")
_sim     = _load("trade_simulator",
                 "app/services/trade_simulator.py",
                 "app.services.trade_simulator")

TradeParams           = _sim.TradeParams
SimulatedTrade        = _sim.SimulatedTrade
ExpectancyReport      = _sim.ExpectancyReport
_determine_side       = _sim._determine_side
_entry_price          = _sim._entry_price
_compute_target       = _sim._compute_target
_compute_stop         = _sim._compute_stop
_gross_pnl            = _sim._gross_pnl
_compute_mae_mfe      = _sim._compute_mae_mfe
_max_drawdown         = _sim._max_drawdown
_simulate_trade       = _sim._simulate_trade
build_expectancy_report = _sim.build_expectancy_report
_generate_param_warnings = _sim._generate_param_warnings
_horizons_up_to       = _sim._horizons_up_to
HORIZONS_ORDERED      = _sim.HORIZONS_ORDERED


# ── Minimal duck-typed ReplayPoint builder ────────────────────────────────────

@dataclass
class _HorizonOutcome:
    horizon:            str
    minutes:            int
    future_spot:        Optional[float]
    future_captured_at: Optional[str] = None
    raw_return_pct:     Optional[float] = None
    convergent_pct:     Optional[float] = None
    hit:                Optional[bool]  = None


@dataclass
class _WallState:
    ce_migrated:     bool = False
    pe_migrated:     bool = False
    ce_direction:    str  = "stable"
    pe_direction:    str  = "stable"
    wall_compressed: bool = False
    wall_expanded:   bool = False


@dataclass
class _ReplayPoint:
    snapshot_id:      str
    symbol:           str
    expiry:           str
    captured_at:      str
    spot_price:       float
    max_pain:         float
    distance_pct:     float
    direction:        str
    pcr:              float
    pcr_bias:         str
    avg_iv:           Optional[float]
    atm_ce_iv:        Optional[float]
    atm_pe_iv:        Optional[float]
    ce_wall_strike:   Optional[float]
    ce_wall_oi:       Optional[int]
    pe_wall_strike:   Optional[float]
    pe_wall_oi:       Optional[int]
    total_ce_oi:      Optional[int]
    total_pe_oi:      Optional[int]
    reversal_score:   Optional[float]
    original_distance: float
    days_to_expiry:   int
    wall_state:       _WallState  = field(default_factory=_WallState)
    outcomes:         dict        = field(default_factory=dict)


def _point(
    spot: float      = 22000.0,
    mp: float        = 22300.0,
    pcr: float       = 1.1,
    iv: float        = 15.0,
    dte: int         = 10,
    outcomes: dict   = None,
    direction: str   = None,
) -> _ReplayPoint:
    dist = abs(spot - mp) / spot * 100
    d    = direction or ("bullish" if spot < mp else "bearish")
    return _ReplayPoint(
        snapshot_id      = str(uuid.uuid4()),
        symbol           = "NIFTY",
        expiry           = "29-May-2026",
        captured_at      = datetime.now(timezone.utc).isoformat(),
        spot_price       = spot,
        max_pain         = mp,
        distance_pct     = dist,
        direction        = d,
        pcr              = pcr,
        pcr_bias         = "bullish",
        avg_iv           = iv,
        atm_ce_iv        = iv,
        atm_pe_iv        = iv,
        ce_wall_strike   = mp + 100,
        ce_wall_oi       = 100000,
        pe_wall_strike   = mp - 100,
        pe_wall_oi       = 110000,
        total_ce_oi      = 500000,
        total_pe_oi      = 550000,
        reversal_score   = 50.0,
        original_distance = abs(spot - mp),
        days_to_expiry   = dte,
        outcomes         = outcomes or {},
    )


def _outcomes(
    f15m: Optional[float] = None,
    f1h:  Optional[float] = None,
    f4h:  Optional[float] = None,
    f1d:  Optional[float] = None,
) -> dict:
    """Build an outcomes dict with futures at the given horizons."""
    data = {"15m": f15m, "1h": f1h, "4h": f4h, "1d": f1d}
    result = {}
    for label, future in data.items():
        result[label] = _HorizonOutcome(
            horizon=label, minutes=0, future_spot=future
        )
    return result


def _default_params(**kw) -> TradeParams:
    defaults = dict(
        trade_type="mean_reversion", stop_pct=1.0,
        target_pct=None, holding_horizon="1d",
        slippage_pct=0.0, transaction_cost_pct=0.0,
        min_distance_pct=0.0,
    )
    defaults.update(kw)
    return TradeParams(**defaults)


# ── Tests: TradeParams ───────────────────────────────────────────────────────

class TestTradeParams:

    def test_round_trip_cost(self):
        p = TradeParams(slippage_pct=0.05, transaction_cost_pct=0.05)
        assert abs(p.round_trip_cost - 0.15) < 1e-9

    def test_validate_invalid_trade_type(self):
        p = TradeParams(trade_type="nonsense")
        issues = p.validate()
        assert any("trade_type" in i for i in issues)

    def test_validate_invalid_stop(self):
        p = TradeParams(stop_pct=-1.0)
        issues = p.validate()
        assert any("stop_pct" in i for i in issues)

    def test_validate_invalid_horizon(self):
        p = TradeParams(holding_horizon="5d")
        issues = p.validate()
        assert any("holding_horizon" in i for i in issues)

    def test_validate_valid(self):
        p = TradeParams()
        assert p.validate() == []

    def test_to_dict(self):
        p = TradeParams(stop_pct=2.0)
        d = p.to_dict()
        assert d["stop_pct"] == 2.0
        assert "trade_type" in d


# ── Tests: _determine_side ───────────────────────────────────────────────────

class TestDetermineSide:

    def test_mean_reversion_bullish_is_long(self):
        assert _determine_side("bullish", "mean_reversion") == "long"

    def test_mean_reversion_bearish_is_short(self):
        assert _determine_side("bearish", "mean_reversion") == "short"

    def test_continuation_bullish_is_short(self):
        assert _determine_side("bullish", "continuation") == "short"

    def test_continuation_bearish_is_long(self):
        assert _determine_side("bearish", "continuation") == "long"

    def test_long_override_ignores_direction(self):
        assert _determine_side("bearish", "long")  == "long"
        assert _determine_side("bullish", "long")  == "long"

    def test_short_override_ignores_direction(self):
        assert _determine_side("bullish", "short") == "short"
        assert _determine_side("bearish", "short") == "short"


# ── Tests: _entry_price ───────────────────────────────────────────────────────

class TestEntryPrice:

    def test_long_entry_above_spot(self):
        # Long: buy at spot + slippage (worse fill for buyer)
        e = _entry_price(22000.0, "long", 0.05)
        assert e == pytest.approx(22000.0 * 1.0005, rel=1e-6)

    def test_short_entry_below_spot(self):
        # Short: sell at spot - slippage (worse fill for seller)
        e = _entry_price(22000.0, "short", 0.05)
        assert e == pytest.approx(22000.0 * 0.9995, rel=1e-6)

    def test_zero_slippage_returns_spot(self):
        assert _entry_price(22000.0, "long",  0.0) == 22000.0
        assert _entry_price(22000.0, "short", 0.0) == 22000.0


# ── Tests: _compute_target ────────────────────────────────────────────────────

class TestComputeTarget:

    def test_mean_reversion_no_target_pct_uses_max_pain(self):
        t = _compute_target("long", 22000.0, 22300.0, None, 1.36, "mean_reversion")
        assert t == 22300.0

    def test_mean_reversion_with_target_pct_long(self):
        t = _compute_target("long", 22000.0, 22300.0, 1.0, 1.36, "mean_reversion")
        assert t == pytest.approx(22000.0 * 1.01, rel=1e-9)

    def test_mean_reversion_with_target_pct_short(self):
        t = _compute_target("short", 22500.0, 22300.0, 1.0, 0.89, "mean_reversion")
        assert t == pytest.approx(22500.0 * 0.99, rel=1e-9)

    def test_continuation_no_target_pct_uses_signal_dist(self):
        # No target_pct → uses max(signal_dist_pct, 0.5) as target distance
        t = _compute_target("short", 22000.0, 22300.0, None, 2.0, "continuation")
        assert t == pytest.approx(22000.0 * 0.98, rel=1e-9)

    def test_continuation_with_target_pct(self):
        t = _compute_target("long", 22000.0, 22300.0, 1.5, 2.0, "continuation")
        assert t == pytest.approx(22000.0 * 1.015, rel=1e-9)

    def test_target_pct_override_on_long(self):
        t = _compute_target("long", 22000.0, 22300.0, 2.0, 1.0, "long")
        assert t == pytest.approx(22000.0 * 1.02, rel=1e-9)


# ── Tests: _compute_stop ─────────────────────────────────────────────────────

class TestComputeStop:

    def test_long_stop_below_entry(self):
        s = _compute_stop("long", 22000.0, 1.0)
        assert s == pytest.approx(22000.0 * 0.99, rel=1e-9)
        assert s < 22000.0

    def test_short_stop_above_entry(self):
        s = _compute_stop("short", 22000.0, 1.0)
        assert s == pytest.approx(22000.0 * 1.01, rel=1e-9)
        assert s > 22000.0


# ── Tests: _gross_pnl ────────────────────────────────────────────────────────

class TestGrossPnl:

    def test_long_profit(self):
        pnl = _gross_pnl("long", 22000.0, 22220.0)   # 1% gain
        assert abs(pnl - 1.0) < 1e-3

    def test_long_loss(self):
        pnl = _gross_pnl("long", 22000.0, 21780.0)   # 1% loss
        assert abs(pnl + 1.0) < 1e-3

    def test_short_profit(self):
        pnl = _gross_pnl("short", 22000.0, 21780.0)  # 1% gain (price fell)
        assert abs(pnl - 1.0) < 1e-3

    def test_short_loss(self):
        pnl = _gross_pnl("short", 22000.0, 22220.0)  # 1% loss (price rose)
        assert abs(pnl + 1.0) < 1e-3

    def test_zero_entry_returns_zero(self):
        assert _gross_pnl("long", 0.0, 22000.0) == 0.0


# ── Tests: _compute_mae_mfe ──────────────────────────────────────────────────

class TestComputeMaeMfe:

    def test_empty_prices_returns_none(self):
        mae, mfe = _compute_mae_mfe("long", 22000.0, [])
        assert mae is None
        assert mfe is None

    def test_long_all_gains(self):
        prices = [22100.0, 22200.0, 22300.0]
        mae, mfe = _compute_mae_mfe("long", 22000.0, prices)
        assert mae == 0.0               # no adverse move
        assert mfe > 0                  # favorable move exists

    def test_long_all_losses(self):
        prices = [21900.0, 21800.0, 21700.0]
        mae, mfe = _compute_mae_mfe("long", 22000.0, prices)
        assert mae > 0                  # adverse moves
        assert mfe == 0.0               # no favorable move

    def test_short_all_gains(self):
        prices = [21900.0, 21800.0, 21700.0]  # falling prices = gains for short
        mae, mfe = _compute_mae_mfe("short", 22000.0, prices)
        assert mae == 0.0
        assert mfe > 0

    def test_mae_magnitude_correct(self):
        # Long: entry=22000, low=21780 → loss ≈ 1%
        prices = [21780.0]
        mae, _ = _compute_mae_mfe("long", 22000.0, prices)
        assert abs(mae - 1.0) < 0.01

    def test_mfe_magnitude_correct(self):
        # Long: entry=22000, high=22220 → gain ≈ 1%
        prices = [22220.0]
        _, mfe = _compute_mae_mfe("long", 22000.0, prices)
        assert abs(mfe - 1.0) < 0.01


# ── Tests: _max_drawdown ─────────────────────────────────────────────────────

class TestMaxDrawdown:

    def test_empty_returns_zero(self):
        assert _max_drawdown([]) == 0.0

    def test_all_wins_returns_zero(self):
        assert _max_drawdown([1.0, 1.0, 1.0]) == 0.0

    def test_single_loss(self):
        # Cumulative: 1, 0, 1 → drawdown at position 1 = 1.0
        dd = _max_drawdown([1.0, -1.0, 1.0])
        assert abs(dd - 1.0) < 1e-9

    def test_progressive_loss(self):
        # Cumulative: 1, 0, -1 → max drawdown = 2.0 (from peak=1 to trough=-1)
        dd = _max_drawdown([1.0, -1.0, -1.0])
        assert abs(dd - 2.0) < 1e-9

    def test_always_loss(self):
        dd = _max_drawdown([-1.0, -1.0, -1.0])
        # Peak stays 0 (we never gain), trough = -3 → dd = 3
        assert abs(dd - 3.0) < 1e-9


# ── Tests: _simulate_trade ────────────────────────────────────────────────────

import pytest  # need for approx

class TestSimulateTrade:

    def test_target_hit_at_1h(self):
        """For a bullish signal (spot=22000, mp=22300), price reaches max_pain at 1h."""
        params  = _default_params(holding_horizon="1d")
        point   = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f15m=22100, f1h=22350, f4h=22400, f1d=22350),
        )
        trade = _simulate_trade(point, params)
        assert trade.exit_reason   == "target"
        assert trade.exit_horizon  == "1h"
        assert trade.exit_price    == pytest.approx(22300.0)   # natural target = max_pain
        assert trade.is_win        is True

    def test_stop_hit_at_15m(self):
        """Price falls through stop at 15m → stop exit."""
        # stop = 22000 * (1 - 1%) = 21780
        params = _default_params(stop_pct=1.0, holding_horizon="1d")
        point  = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f15m=21700, f1h=22100),  # 15m below stop
        )
        trade = _simulate_trade(point, params)
        assert trade.exit_reason   == "stop"
        assert trade.exit_horizon  == "15m"
        assert trade.exit_price    == pytest.approx(22000.0 * 0.99)
        assert trade.is_win        is False

    def test_time_stop_at_1d(self):
        """No target/stop hit → time stop at 1d."""
        params = _default_params(stop_pct=2.0, holding_horizon="1d")
        point  = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f15m=22050, f1h=22100, f4h=22150, f1d=22180),
        )
        trade = _simulate_trade(point, params)
        assert trade.exit_reason  == "time_stop"
        assert trade.exit_horizon == "1d"
        assert trade.exit_price   == pytest.approx(22180.0)

    def test_no_data(self):
        """No forward prices at all → no_data."""
        params = _default_params(holding_horizon="1d")
        point  = _point(spot=22000, mp=22300, outcomes={})
        trade  = _simulate_trade(point, params)
        assert trade.exit_reason == "no_data"
        assert trade.net_pnl_pct is None
        assert trade.is_win      is None

    def test_bearish_short_target_hit(self):
        """Bearish signal (spot > mp) → SHORT trade; price falls to max_pain."""
        params  = _default_params(holding_horizon="1d")
        point   = _point(
            spot=22500, mp=22300, direction="bearish",
            outcomes=_outcomes(f15m=22400, f1h=22280, f4h=22200, f1d=22200),
        )
        trade = _simulate_trade(point, params)
        assert trade.side        == "short"
        assert trade.exit_reason == "target"
        assert trade.is_win      is True

    def test_continuation_trade_goes_short_on_bullish(self):
        """Continuation: bullish signal → SHORT (price continues to fall)."""
        params = _default_params(trade_type="continuation", target_pct=1.0, stop_pct=1.0)
        point  = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f1d=21780),   # price fell
        )
        trade = _simulate_trade(point, params)
        assert trade.side == "short"

    def test_pnl_correct_no_costs(self):
        """With zero costs, gross P&L = (exit - entry) / entry * 100 for long."""
        params = _default_params(stop_pct=2.0, holding_horizon="1d",
                                 slippage_pct=0.0, transaction_cost_pct=0.0)
        point  = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f1d=22100),   # +0.4545…% return
        )
        trade = _simulate_trade(point, params)
        expected_gross = (22100 - 22000) / 22000 * 100
        assert trade.gross_pnl_pct == pytest.approx(expected_gross, rel=1e-4)
        assert trade.net_pnl_pct   == pytest.approx(expected_gross, rel=1e-4)  # no costs

    def test_pnl_deducts_costs(self):
        """With costs, net P&L = gross - round_trip_cost."""
        params = _default_params(
            stop_pct=2.0, holding_horizon="1d",
            slippage_pct=0.05, transaction_cost_pct=0.05,
        )
        point = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f1d=22100),
        )
        trade = _simulate_trade(point, params)
        assert trade.net_pnl_pct == pytest.approx(
            trade.gross_pnl_pct - params.round_trip_cost, rel=1e-6
        )

    def test_horizons_checked_in_order(self):
        """Target is hit at 1h but stop is not hit at 15m → should exit at 1h."""
        params = _default_params(stop_pct=1.0, holding_horizon="1d")
        point  = _point(
            spot=22000, mp=22300,
            # 15m: safe (no hit), 1h: reaches target
            outcomes=_outcomes(f15m=22100, f1h=22320, f4h=22400),
        )
        trade = _simulate_trade(point, params)
        assert trade.exit_horizon == "1h"
        assert trade.exit_reason  == "target"

    def test_mae_mfe_populated(self):
        """MAE and MFE should be non-None when horizon prices exist."""
        params = _default_params(stop_pct=2.0, holding_horizon="1d")
        point  = _point(
            spot=22000, mp=22300,
            outcomes=_outcomes(f15m=22050, f1h=22150, f4h=22200, f1d=22250),
        )
        trade = _simulate_trade(point, params)
        assert trade.mae_pct is not None
        assert trade.mfe_pct is not None


# ── Tests: build_expectancy_report ────────────────────────────────────────────

def _make_trade(net_pnl: Optional[float], direction="bullish",
                gross_pnl: Optional[float] = None,
                exit_reason="time_stop",
                mae=None, mfe=None) -> SimulatedTrade:
    if gross_pnl is None:
        gross_pnl = net_pnl
    is_win = (net_pnl > 0) if net_pnl is not None else None
    return SimulatedTrade(
        snapshot_id="x", symbol="NIFTY", captured_at="2025-01-01T09:15:00",
        signal_spot=22000, max_pain=22300, signal_dist_pct=1.36,
        direction=direction, days_to_expiry=5, pcr=1.1, avg_iv=15.0,
        trade_type="mean_reversion", side="long",
        entry_price=22000, target_price=22300, stop_price=21780,
        exit_price=22000 + (net_pnl or 0) / 100 * 22000,
        exit_horizon="1d", exit_reason=exit_reason,
        gross_pnl_pct=gross_pnl, net_pnl_pct=net_pnl,
        is_win=is_win, mae_pct=mae, mfe_pct=mfe,
    )


class TestBuildExpectancyReport:

    def _params(self):
        return _default_params()

    def test_all_wins(self):
        trades = [_make_trade(1.0)] * 20 + [_make_trade(0.5)] * 10
        r = build_expectancy_report(trades, self._params(), "NIFTY", "30d")
        assert r.win_rate   == 1.0
        assert r.wins       == 30
        assert r.losses     == 0
        assert r.avg_loss_pct is None  # no losses

    def test_all_losses(self):
        trades = [_make_trade(-1.0)] * 20
        r = build_expectancy_report(trades, self._params(), "NIFTY", "30d")
        assert r.win_rate    == 0.0
        assert r.losses      == 20
        assert r.avg_win_pct is None

    def test_mixed_50_50(self):
        """50% win rate, avg win = 1%, avg loss = 1% → expectancy = 0."""
        wins   = [_make_trade(1.0)]  * 15
        losses = [_make_trade(-1.0)] * 15
        r = build_expectancy_report(wins + losses, self._params(), "NIFTY", "30d")
        assert r.win_rate == pytest.approx(0.5)
        assert abs(r.expectancy_pct) < 1e-6

    def test_positive_edge(self):
        """win_rate=0.6, avg_win=2%, avg_loss=1% → expectancy = 0.6*2 - 0.4*1 = 0.8."""
        wins   = [_make_trade(2.0)]  * 60
        losses = [_make_trade(-1.0)] * 40
        r = build_expectancy_report(wins + losses, self._params(), "NIFTY", "30d")
        assert r.expectancy_pct == pytest.approx(0.8, abs=0.01)
        assert r.profit_factor  is not None
        assert r.profit_factor  > 1.0

    def test_payoff_ratio(self):
        wins   = [_make_trade(2.0)]  * 10
        losses = [_make_trade(-1.0)] * 10
        r = build_expectancy_report(wins + losses, self._params(), "NIFTY", "30d")
        assert r.payoff_ratio == pytest.approx(2.0, rel=1e-3)

    def test_kelly_fraction(self):
        """W=0.6, RR=2 → Kelly = 0.6 - 0.4/2 = 0.40."""
        wins   = [_make_trade(2.0)]  * 6
        losses = [_make_trade(-1.0)] * 4
        r = build_expectancy_report(wins + losses, self._params(), "NIFTY", "30d")
        assert r.kelly_fraction    == pytest.approx(0.40, abs=0.02)
        assert r.recommended_kelly == pytest.approx(0.10, abs=0.01)

    def test_no_data_counted_but_excluded_from_pnl(self):
        trades = [_make_trade(1.0)] * 5 + [_make_trade(None, exit_reason="no_data")] * 5
        r = build_expectancy_report(trades, self._params(), "NIFTY", "30d")
        assert r.total_signals == 10
        assert r.no_data       == 5
        assert r.simulated     == 5

    def test_exits_by_reason(self):
        targets   = [_make_trade(1.0,  exit_reason="target")]   * 3
        stops     = [_make_trade(-1.0, exit_reason="stop")]     * 2
        time_stop = [_make_trade(0.5,  exit_reason="time_stop")]* 5
        r = build_expectancy_report(targets + stops + time_stop,
                                    self._params(), "NIFTY", "30d")
        assert r.exits_by_reason["target"]    == 3
        assert r.exits_by_reason["stop"]      == 2
        assert r.exits_by_reason["time_stop"] == 5

    def test_drawdown_all_losses(self):
        """Three consecutive losses of 1% each → max drawdown = 3%."""
        trades = [_make_trade(-1.0)] * 3
        r = build_expectancy_report(trades, self._params(), "NIFTY", "30d")
        assert r.max_drawdown_pct == pytest.approx(3.0, abs=0.01)

    def test_avg_mae_mfe(self):
        trades = [_make_trade(0.5, mae=0.8, mfe=1.2)] * 4
        r = build_expectancy_report(trades, self._params(), "NIFTY", "30d")
        assert r.avg_mae_pct == pytest.approx(0.8, abs=1e-6)
        assert r.avg_mfe_pct == pytest.approx(1.2, abs=1e-6)


# ── Tests: Warnings ───────────────────────────────────────────────────────────

class TestWarnings:

    def test_always_has_discrete_price_warning(self):
        params = TradeParams()
        warnings = _generate_param_warnings(params)
        assert any("discrete_price_check" in w for w in warnings)

    def test_unrealistic_stop_warning(self):
        params = TradeParams(stop_pct=0.05)  # below 0.10 threshold
        warnings = _generate_param_warnings(params)
        assert any("unrealistic_stop" in w for w in warnings)

    def test_no_unrealistic_stop_warning_for_normal(self):
        params = TradeParams(stop_pct=1.0)
        warnings = _generate_param_warnings(params)
        assert not any("unrealistic_stop" in w for w in warnings)

    def test_target_below_cost_warning(self):
        # target_pct = 0.05, round_trip_cost = 0.15 → target below cost
        params = TradeParams(target_pct=0.05, slippage_pct=0.05, transaction_cost_pct=0.05)
        warnings = _generate_param_warnings(params)
        assert any("target_below_cost" in w for w in warnings)

    def test_insufficient_sample_warning(self):
        params = _default_params()
        small_trades = [_make_trade(1.0)] * 5   # only 5 < 30 threshold
        r = build_expectancy_report(small_trades, params, "NIFTY", "30d")
        assert any("insufficient_sample" in w for w in r.warnings)

    def test_no_insufficient_sample_warning_for_large(self):
        params = _default_params()
        trades = [_make_trade(1.0)] * 30
        r = build_expectancy_report(trades, params, "NIFTY", "30d")
        assert not any("insufficient_sample" in w for w in r.warnings)

    def test_negative_expectancy_warning(self):
        params = _default_params()
        # all losses
        trades = [_make_trade(-1.0)] * 30
        r = build_expectancy_report(trades, params, "NIFTY", "30d")
        assert any("negative_expectancy" in w for w in r.warnings)


# ── Tests: Horizons utility ────────────────────────────────────────────────────

class TestHorizonsUpTo:

    def test_15m_returns_only_15m(self):
        assert _horizons_up_to("15m") == ["15m"]

    def test_1h_returns_15m_and_1h(self):
        assert _horizons_up_to("1h") == ["15m", "1h"]

    def test_1d_returns_all(self):
        assert _horizons_up_to("1d") == ["15m", "1h", "4h", "1d"]


# ── Regression: expectancy formula ────────────────────────────────────────────

class TestRegressionExpectancy:

    def test_formula_matches_manual_calc(self):
        """
        Manual: win_rate=0.55, avg_win=1.5%, avg_loss=1.0%
        expectancy = 0.55 * 1.5 - 0.45 * 1.0 = 0.825 - 0.45 = 0.375
        """
        wins   = [_make_trade(1.5)]  * 11   # 55%
        losses = [_make_trade(-1.0)] * 9    # 45%
        r = build_expectancy_report(wins + losses, _default_params(), "NIFTY", "30d")
        expected = 0.55 * 1.5 - 0.45 * 1.0
        assert r.expectancy_pct == pytest.approx(expected, abs=0.01)

    def test_expectancy_r_is_expectancy_divided_by_loss(self):
        wins   = [_make_trade(2.0)]  * 6
        losses = [_make_trade(-1.0)] * 4
        r = build_expectancy_report(wins + losses, _default_params(), "NIFTY", "30d")
        assert r.expectancy_r == pytest.approx(
            r.expectancy_pct / r.avg_loss_pct, rel=1e-3
        )

    def test_profit_factor_ratio(self):
        """profit_factor = gross_wins / gross_losses."""
        wins   = [_make_trade(2.0, gross_pnl=2.0)]  * 10
        losses = [_make_trade(-1.0, gross_pnl=-1.0)] * 10
        r = build_expectancy_report(wins + losses, _default_params(), "NIFTY", "30d")
        # gross: 10*2 / 10*1 = 2.0
        assert r.profit_factor == pytest.approx(2.0, rel=1e-3)

    def test_expectancy_zero_for_breakeven(self):
        """Win rate 0.5, avg_win = avg_loss → expectancy = 0."""
        wins   = [_make_trade(1.0)]  * 50
        losses = [_make_trade(-1.0)] * 50
        r = build_expectancy_report(wins + losses, _default_params(), "NIFTY", "30d")
        assert abs(r.expectancy_pct) < 0.01
