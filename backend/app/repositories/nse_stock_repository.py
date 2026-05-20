"""
Repository for NseStock CRUD operations.
All methods operate within the caller's SQLAlchemy session context.
"""

from datetime import datetime, timezone
from typing import Optional

from app.extensions import db
from app.models.nse_stock import NseStock


class NseStockRepository:

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_by_symbol(self, symbol: str) -> Optional[NseStock]:
        return db.session.execute(
            db.select(NseStock).where(NseStock.symbol == symbol.upper())
        ).scalar_one_or_none()

    def get_by_isin(self, isin: str) -> Optional[NseStock]:
        return db.session.execute(
            db.select(NseStock).where(NseStock.isin == isin)
        ).scalar_one_or_none()

    def get_all_active(self) -> list[NseStock]:
        return list(
            db.session.execute(
                db.select(NseStock)
                .where(NseStock.is_active == True)   # noqa: E712
                .order_by(NseStock.symbol)
            ).scalars()
        )

    def get_all(self) -> list[NseStock]:
        return list(
            db.session.execute(
                db.select(NseStock).order_by(NseStock.symbol)
            ).scalars()
        )

    def get_by_sector(self, sector: str) -> list[NseStock]:
        return list(
            db.session.execute(
                db.select(NseStock)
                .where(
                    NseStock.sector == sector,
                    NseStock.is_active == True,   # noqa: E712
                )
                .order_by(NseStock.symbol)
            ).scalars()
        )

    def get_by_industry(self, industry: str) -> list[NseStock]:
        return list(
            db.session.execute(
                db.select(NseStock)
                .where(
                    NseStock.industry == industry,
                    NseStock.is_active == True,   # noqa: E712
                )
                .order_by(NseStock.symbol)
            ).scalars()
        )

    def get_distinct_sectors(self) -> list[str]:
        rows = db.session.execute(
            db.select(NseStock.sector)
            .where(NseStock.sector.isnot(None), NseStock.is_active == True)   # noqa: E712
            .distinct()
            .order_by(NseStock.sector)
        ).scalars()
        return [r for r in rows if r]

    def get_distinct_industries(self) -> list[str]:
        rows = db.session.execute(
            db.select(NseStock.industry)
            .where(NseStock.industry.isnot(None), NseStock.is_active == True)   # noqa: E712
            .distinct()
            .order_by(NseStock.industry)
        ).scalars()
        return [r for r in rows if r]

    def count_active(self) -> int:
        return db.session.execute(
            db.select(db.func.count(NseStock.id)).where(NseStock.is_active == True)   # noqa: E712
        ).scalar_one()

    # ── Write ──────────────────────────────────────────────────────────────────

    def upsert(self, symbol: str, data: dict) -> tuple[NseStock, bool]:
        """
        Insert or update a stock record by symbol.

        Returns (stock, created) where created=True means a new row was inserted.
        """
        stock = self.get_by_symbol(symbol)
        created = stock is None

        if created:
            stock = NseStock(symbol=symbol.upper())
            db.session.add(stock)

        for field, value in data.items():
            if hasattr(stock, field) and field != "id":
                setattr(stock, field, value)

        stock.last_synced_at = datetime.now(timezone.utc)
        return stock, created

    def deactivate_missing(self, active_symbols: set[str]) -> int:
        """
        Mark all stocks NOT in active_symbols as is_active=False.
        Returns count of rows deactivated.
        """
        upper_symbols = {s.upper() for s in active_symbols}
        result = db.session.execute(
            db.update(NseStock)
            .where(
                NseStock.symbol.not_in(upper_symbols),
                NseStock.is_active == True,   # noqa: E712
            )
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )
        return result.rowcount
