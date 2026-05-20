"""
RegimeSnapshot — one row per snapshot classification.

Stores the output of the regime classifier for each MaxPainSnapshot.
Kept as a separate table (not columns on max_pain_snapshots) so:
  - Classification can be re-run independently without schema migration.
  - Multiple classification passes can be stored (e.g. different lookbacks).
  - Queries for regime history are index-only on this table.

Query patterns:
  1. Regime history for a symbol        → (symbol, captured_at DESC)
  2. Cross-symbol at a time             → (captured_at)
  3. Distribution of regimes per symbol → (symbol, regime, captured_at)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


class RegimeSnapshot(db.Model):
    __tablename__ = "regime_snapshots"

    __table_args__ = (
        # Primary access: recent regimes for a symbol
        db.Index("ix_rs_symbol_time",         "symbol", "captured_at"),
        # Cross-symbol: what regime was the market in at this moment?
        db.Index("ix_rs_captured_at",          "captured_at"),
        # Regime-filtered time-series queries
        db.Index("ix_rs_symbol_regime_time",   "symbol", "regime", "captured_at"),
    )

    id = db.Column(
        db.UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, nullable=False,
    )

    # ── Link to source snapshot ──────────────────────────────────────────────
    # Nullable so we can store classifications even if the source row was
    # cleaned up by the retention policy.
    snapshot_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("max_pain_snapshots.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # ── Identity ─────────────────────────────────────────────────────────────
    symbol      = db.Column(db.String(30), nullable=False)
    expiry      = db.Column(db.String(30), nullable=True)
    captured_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Primary classification ────────────────────────────────────────────────
    regime     = db.Column(db.String(40), nullable=False)   # primary label
    confidence = db.Column(db.Float,      nullable=False)   # 0.0 – 1.0

    # ── Extended classification data (JSONB) ─────────────────────────────────
    secondary_regimes = db.Column(JSONB, nullable=True)   # list[str]
    scores            = db.Column(JSONB, nullable=True)   # {regime: score}
    metrics           = db.Column(JSONB, nullable=True)   # supporting time-series
    warnings          = db.Column(JSONB, nullable=True)   # list[str]

    # ── Context window metadata ──────────────────────────────────────────────
    n_window  = db.Column(db.Integer, nullable=True)   # snapshots used
    lookback  = db.Column(db.Integer, nullable=True)   # lookback parameter used

    def to_dict(self) -> dict:
        return {
            "id":                str(self.id),
            "snapshot_id":       str(self.snapshot_id) if self.snapshot_id else None,
            "symbol":            self.symbol,
            "expiry":            self.expiry,
            "captured_at":       self.captured_at.isoformat(),
            "regime":            self.regime,
            "confidence":        self.confidence,
            "secondary_regimes": self.secondary_regimes or [],
            "scores":            self.scores or {},
            "metrics":           self.metrics or {},
            "warnings":          self.warnings or [],
            "n_window":          self.n_window,
            "lookback":          self.lookback,
        }

    def __repr__(self):
        return (
            f"<RegimeSnapshot {self.symbol} "
            f"regime={self.regime} conf={self.confidence:.2f} "
            f"@ {self.captured_at}>"
        )
