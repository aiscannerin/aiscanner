"""
MaxPainSnapshot — one row per symbol per 5-minute capture tick.

Schema is optimised for three query patterns:
  1. Time-series for a symbol  → (symbol, captured_at DESC)
  2. Cross-symbol at a time    → (captured_at)
  3. Per-expiry trend          → (symbol, expiry, captured_at DESC)

Scalar metrics are stored as dedicated columns (not JSONB) so PostgreSQL can
use index-only scans and range operators without JSON extraction overhead.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


class MaxPainSnapshot(db.Model):
    __tablename__ = "max_pain_snapshots"

    __table_args__ = (
        # Primary time-series access pattern
        db.Index("ix_mps_symbol_time",   "symbol", "captured_at"),
        # Cross-symbol range queries
        db.Index("ix_mps_captured_at",   "captured_at"),
        # Per-expiry trend
        db.Index("ix_mps_symbol_expiry", "symbol", "expiry", "captured_at"),
        # High-deviation alerts
        db.Index("ix_mps_distance_pct",  "distance_pct"),
        # Score queries
        db.Index("ix_mps_reversal_score", "reversal_score"),
    )

    id = db.Column(db.UUID(as_uuid=True), primary_key=True,
                   default=uuid.uuid4, nullable=False)

    # ── Identity ──────────────────────────────────────────────────────────────
    symbol      = db.Column(db.String(30),  nullable=False)
    expiry      = db.Column(db.String(30),  nullable=True)   # e.g. "25-Jul-2024"
    captured_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    # ── Price ─────────────────────────────────────────────────────────────────
    spot_price   = db.Column(db.Float, nullable=True)
    max_pain     = db.Column(db.Float, nullable=True)
    distance_pct = db.Column(db.Float, nullable=True)  # abs(spot-mp)/spot*100
    direction    = db.Column(db.String(10), nullable=True)  # bullish | bearish

    # ── OI metrics ────────────────────────────────────────────────────────────
    total_ce_oi  = db.Column(db.BigInteger, nullable=True)
    total_pe_oi  = db.Column(db.BigInteger, nullable=True)
    pcr          = db.Column(db.Float, nullable=True)  # pe_oi / ce_oi
    pcr_bias     = db.Column(db.String(10), nullable=True)

    # ── OI walls (top strike by OI above/below spot) ──────────────────────────
    ce_wall_strike = db.Column(db.Float, nullable=True)   # strongest call wall
    ce_wall_oi     = db.Column(db.BigInteger, nullable=True)
    pe_wall_strike = db.Column(db.Float, nullable=True)   # strongest put wall
    pe_wall_oi     = db.Column(db.BigInteger, nullable=True)

    # ── Volatility ────────────────────────────────────────────────────────────
    atm_ce_iv  = db.Column(db.Float, nullable=True)   # IV of ATM call
    atm_pe_iv  = db.Column(db.Float, nullable=True)   # IV of ATM put
    avg_iv     = db.Column(db.Float, nullable=True)   # mean(atm_ce_iv, atm_pe_iv)

    # ── Volume ────────────────────────────────────────────────────────────────
    total_ce_volume = db.Column(db.BigInteger, nullable=True)
    total_pe_volume = db.Column(db.BigInteger, nullable=True)

    # ── Reversal score ────────────────────────────────────────────────────────
    reversal_score    = db.Column(db.Float,      nullable=True)
    reversal_category = db.Column(db.String(20), nullable=True)  # Weak/Moderate/Strong/Extreme

    # ── Top OI zones (compact JSON — top 5 CE and PE strikes by OI) ─────────
    top_ce_strikes = db.Column(JSONB, nullable=True)   # [{strike, oi}, …]
    top_pe_strikes = db.Column(JSONB, nullable=True)

    # ── Top pain strikes (lowest total payout — for replay) ──────────────────
    top_pain_strikes = db.Column(JSONB, nullable=True)  # [{strike, ce_payout, pe_payout, total_pain}, …]

    def to_dict(self) -> dict:
        return {
            "id":                str(self.id),
            "symbol":            self.symbol,
            "expiry":            self.expiry,
            "captured_at":       self.captured_at.isoformat(),
            "spot_price":        self.spot_price,
            "max_pain":          self.max_pain,
            "distance_pct":      self.distance_pct,
            "direction":         self.direction,
            "total_ce_oi":       self.total_ce_oi,
            "total_pe_oi":       self.total_pe_oi,
            "pcr":               self.pcr,
            "pcr_bias":          self.pcr_bias,
            "ce_wall_strike":    self.ce_wall_strike,
            "ce_wall_oi":        self.ce_wall_oi,
            "pe_wall_strike":    self.pe_wall_strike,
            "pe_wall_oi":        self.pe_wall_oi,
            "atm_ce_iv":         self.atm_ce_iv,
            "atm_pe_iv":         self.atm_pe_iv,
            "avg_iv":            self.avg_iv,
            "total_ce_volume":   self.total_ce_volume,
            "total_pe_volume":   self.total_pe_volume,
            "reversal_score":    self.reversal_score,
            "reversal_category": self.reversal_category,
            "top_ce_strikes":     self.top_ce_strikes,
            "top_pe_strikes":     self.top_pe_strikes,
            "top_pain_strikes":   self.top_pain_strikes,
        }

    def __repr__(self):
        return f"<MaxPainSnapshot {self.symbol} @ {self.captured_at}>"


class OIWallSnapshot(db.Model):
    """
    Tracks the top-N OI walls per symbol per tick.
    One row = one strike-side combination at a given time.

    Querying the migration of a wall over time:
        SELECT captured_at, strike, oi
        FROM oi_wall_snapshots
        WHERE symbol = 'NIFTY' AND side = 'CE' AND rank = 1
        ORDER BY captured_at;
    """
    __tablename__ = "oi_wall_snapshots"

    __table_args__ = (
        db.Index("ix_oiws_symbol_side_time", "symbol", "side", "captured_at"),
        db.Index("ix_oiws_symbol_time",      "symbol", "captured_at"),
        db.Index("ix_oiws_strike",           "strike"),
    )

    id = db.Column(db.UUID(as_uuid=True), primary_key=True,
                   default=uuid.uuid4, nullable=False)

    symbol      = db.Column(db.String(30), nullable=False)
    expiry      = db.Column(db.String(30), nullable=True)
    captured_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    side   = db.Column(db.String(3),  nullable=False)   # 'CE' or 'PE'
    rank   = db.Column(db.Integer,    nullable=False)    # 1 = largest OI
    strike = db.Column(db.Float,      nullable=False)
    oi     = db.Column(db.BigInteger, nullable=False)
    oi_change = db.Column(db.BigInteger, nullable=True)  # vs previous tick

    def to_dict(self) -> dict:
        return {
            "id":           str(self.id),
            "symbol":       self.symbol,
            "expiry":       self.expiry,
            "captured_at":  self.captured_at.isoformat(),
            "side":         self.side,
            "rank":         self.rank,
            "strike":       self.strike,
            "oi":           self.oi,
            "oi_change":    self.oi_change,
        }
