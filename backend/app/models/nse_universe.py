import uuid
from datetime import datetime, timezone

from app.extensions import db


class NseUniverse(db.Model):
    """
    A named collection of NSE symbols — e.g. "NIFTY 50", "NIFTY BANK",
    "IT Sector", or a custom watchlist.

    Universes are referenced by the scanner's `universe` field.
    The scanner service calls get_symbols_for_universe(slug) to get the
    actual list of symbols at scan time.

    Built-in slugs (must match scanner_job_service expectations):
        nifty50, nifty100, nifty500, nifty_bank, nifty_it, nifty_pharma,
        nifty_auto, nifty_fno
    """

    __tablename__ = "nse_universes"

    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_nse_universes_slug"),
        db.Index("ix_nse_universes_is_active", "is_active"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    name = db.Column(db.String(100), nullable=False)            # "NIFTY 50"
    slug = db.Column(db.String(60), nullable=False, unique=True)# "nifty50"
    description = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # ── Source metadata ──────────────────────────────────────────────────────────
    # "index" = pulled from NSE index constituent API
    # "sector" = auto-built from sector classification
    # "manual" = manually curated
    source = db.Column(db.String(20), nullable=False, default="manual")

    # ── Timestamps ───────────────────────────────────────────────────────────────
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Relationships ────────────────────────────────────────────────────────────
    memberships = db.relationship(
        "NseUniverseStock",
        back_populates="universe",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<NseUniverse {self.slug}>"

    def to_dict(self, include_count=False):
        d = {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "is_active": self.is_active,
            "source": self.source,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
        }
        if include_count:
            d["stock_count"] = len(self.memberships)
        return d
