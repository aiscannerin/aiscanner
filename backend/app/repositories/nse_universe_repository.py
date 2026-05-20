"""
Repository for NseUniverse and NseUniverseStock operations.
"""

from datetime import datetime, timezone
from typing import Optional

from app.extensions import db
from app.models.nse_stock import NseStock
from app.models.nse_universe import NseUniverse
from app.models.nse_universe_stock import NseUniverseStock


class NseUniverseRepository:

    # ── Universe CRUD ──────────────────────────────────────────────────────────

    def get_by_slug(self, slug: str) -> Optional[NseUniverse]:
        return db.session.execute(
            db.select(NseUniverse).where(NseUniverse.slug == slug)
        ).scalar_one_or_none()

    def get_all_active(self) -> list[NseUniverse]:
        return list(
            db.session.execute(
                db.select(NseUniverse)
                .where(NseUniverse.is_active == True)   # noqa: E712
                .order_by(NseUniverse.name)
            ).scalars()
        )

    def get_all(self) -> list[NseUniverse]:
        return list(
            db.session.execute(
                db.select(NseUniverse).order_by(NseUniverse.name)
            ).scalars()
        )

    def upsert(self, slug: str, data: dict) -> tuple[NseUniverse, bool]:
        """Insert or update a universe by slug. Returns (universe, created)."""
        universe = self.get_by_slug(slug)
        created = universe is None
        if created:
            universe = NseUniverse(slug=slug)
            db.session.add(universe)
        for field, value in data.items():
            if hasattr(universe, field) and field != "id":
                setattr(universe, field, value)
        return universe, created

    def mark_synced(self, universe: NseUniverse) -> None:
        universe.last_synced_at = datetime.now(timezone.utc)

    # ── Membership (universe ↔ stock) ─────────────────────────────────────────

    def get_symbols_for_universe(self, slug: str) -> list[str]:
        """
        Return a list of NSE symbol strings for the given universe slug.
        Returns [] if the universe doesn't exist or has no members.
        """
        universe = self.get_by_slug(slug)
        if not universe:
            return []

        rows = db.session.execute(
            db.select(NseStock.symbol)
            .join(NseUniverseStock, NseUniverseStock.stock_id == NseStock.id)
            .where(
                NseUniverseStock.universe_id == universe.id,
                NseStock.is_active == True,   # noqa: E712
            )
            .order_by(NseStock.symbol)
        ).scalars()
        return list(rows)

    def replace_memberships(
        self,
        universe: NseUniverse,
        symbol_weight_pairs: list[tuple[str, Optional[float]]],
    ) -> tuple[int, int]:
        """
        Replace all existing memberships for a universe with a new set.

        Args:
            universe: NseUniverse instance
            symbol_weight_pairs: list of (symbol, weight_or_None)

        Returns:
            (added_count, skipped_count)
        """
        # Delete existing memberships
        db.session.execute(
            db.delete(NseUniverseStock).where(
                NseUniverseStock.universe_id == universe.id
            )
        )

        added = 0
        skipped = 0

        for symbol, weight in symbol_weight_pairs:
            stock = db.session.execute(
                db.select(NseStock).where(NseStock.symbol == symbol.upper())
            ).scalar_one_or_none()

            if not stock:
                skipped += 1
                continue

            db.session.add(
                NseUniverseStock(
                    universe_id=universe.id,
                    stock_id=stock.id,
                    weight=weight,
                )
            )
            added += 1

        return added, skipped

    def count_members(self, slug: str) -> int:
        universe = self.get_by_slug(slug)
        if not universe:
            return 0
        return db.session.execute(
            db.select(db.func.count(NseUniverseStock.id))
            .where(NseUniverseStock.universe_id == universe.id)
        ).scalar_one()
