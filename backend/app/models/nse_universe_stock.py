import uuid
from datetime import datetime, timezone

from app.extensions import db


class NseUniverseStock(db.Model):
    """
    Join table linking NseUniverse ↔ NseStock.

    `weight` is optional — used for index-weighted universes (e.g. NIFTY 50
    market-cap weights). For unweighted universes it stays NULL.
    """

    __tablename__ = "nse_universe_stocks"

    __table_args__ = (
        db.UniqueConstraint(
            "universe_id", "stock_id",
            name="uq_nse_universe_stocks_universe_stock",
        ),
        db.Index("ix_nse_universe_stocks_universe_id", "universe_id"),
        db.Index("ix_nse_universe_stocks_stock_id", "stock_id"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    universe_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("nse_universes.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("nse_stocks.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional: index weightage (0.0 – 100.0), NULL for equal-weight / sector universes
    weight = db.Column(db.Numeric(8, 4), nullable=True)

    added_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ────────────────────────────────────────────────────────────
    universe = db.relationship("NseUniverse", back_populates="memberships")
    stock    = db.relationship("NseStock",    back_populates="universe_memberships")

    def __repr__(self):
        return f"<NseUniverseStock universe={self.universe_id} stock={self.stock_id}>"
