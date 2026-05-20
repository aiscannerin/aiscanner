import uuid
from datetime import datetime, timezone

from app.extensions import db


class NseStock(db.Model):
    """
    Master table for all NSE-listed equity instruments.

    Populated via `flask nse sync-stocks` (fetches the NSE equity bhavcopy /
    securities CSV) and optionally enriched with sector data via
    `flask nse import-industry-csv`.

    yfinance_symbol = symbol + ".NS"  (e.g. "RELIANCE.NS")
    """

    __tablename__ = "nse_stocks"

    __table_args__ = (
        db.Index("ix_nse_stocks_symbol", "symbol"),
        db.Index("ix_nse_stocks_sector", "sector"),
        db.Index("ix_nse_stocks_industry", "industry"),
        db.Index("ix_nse_stocks_is_active", "is_active"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ── Core identity ────────────────────────────────────────────────────────────
    symbol = db.Column(db.String(30), nullable=False, unique=True)
    company_name = db.Column(db.String(255), nullable=True)
    series = db.Column(db.String(10), nullable=True)          # EQ, BE, SM, etc.
    isin = db.Column(db.String(20), nullable=True, unique=True)
    exchange = db.Column(db.String(10), nullable=False, default="NSE")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # ── Sector / industry classification ─────────────────────────────────────────
    # Populated from NSE industry classification CSV (downloaded separately or
    # manually imported via `flask nse import-industry-csv`).
    macro_sector = db.Column(db.String(100), nullable=True)   # e.g. "FINANCIAL SERVICES"
    sector = db.Column(db.String(100), nullable=True)          # e.g. "BANKING"
    industry = db.Column(db.String(150), nullable=True)        # e.g. "PRIVATE SECTOR BANK"
    basic_industry = db.Column(db.String(200), nullable=True)  # granular level

    # ── yfinance integration ─────────────────────────────────────────────────────
    # Pre-computed once so we don't rebuild it on every scan tick.
    yfinance_symbol = db.Column(db.String(40), nullable=True)  # e.g. "RELIANCE.NS"

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
    universe_memberships = db.relationship(
        "NseUniverseStock",
        back_populates="stock",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<NseStock {self.symbol}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "symbol": self.symbol,
            "company_name": self.company_name,
            "series": self.series,
            "isin": self.isin,
            "exchange": self.exchange,
            "is_active": self.is_active,
            "macro_sector": self.macro_sector,
            "sector": self.sector,
            "industry": self.industry,
            "basic_industry": self.basic_industry,
            "yfinance_symbol": self.yfinance_symbol,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
        }
