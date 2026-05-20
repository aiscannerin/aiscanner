"""add_regime_snapshots

Revision ID: l2m3n4o5p6q7
Revises: k1e2f3g4h5i6
Create Date: 2025-05-19

Adds the regime_snapshots table, which stores the output of the
market regime classifier for each MaxPainSnapshot tick.

Design:
  - Separate table (not columns on max_pain_snapshots) so classification
    can be re-run independently and at different lookback settings.
  - snapshot_id FK uses SET NULL on delete so regime rows survive the
    90-day max_pain_snapshots retention cleanup.
  - Three covering indexes for the three access patterns described in
    the model docstring.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision    = "l2m3n4o5p6q7"
down_revision = "k1e2f3g4h5i6"
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        "regime_snapshots",

        sa.Column("id",
                  postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  nullable=False),

        # FK to source snapshot — SET NULL so regime rows outlive the source
        sa.Column("snapshot_id",
                  postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("max_pain_snapshots.id", ondelete="SET NULL"),
                  nullable=True),

        # Identity
        sa.Column("symbol",      sa.String(30),                        nullable=False),
        sa.Column("expiry",      sa.String(30),                        nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True),           nullable=False),

        # Primary classification
        sa.Column("regime",      sa.String(40),                        nullable=False),
        sa.Column("confidence",  sa.Float,                             nullable=False),

        # Extended data (JSONB)
        sa.Column("secondary_regimes", postgresql.JSONB,               nullable=True),
        sa.Column("scores",            postgresql.JSONB,               nullable=True),
        sa.Column("metrics",           postgresql.JSONB,               nullable=True),
        sa.Column("warnings",          postgresql.JSONB,               nullable=True),

        # Context window metadata
        sa.Column("n_window",  sa.Integer, nullable=True),
        sa.Column("lookback",  sa.Integer, nullable=True),
    )

    # Time-series index per symbol
    op.create_index(
        "ix_rs_symbol_time",
        "regime_snapshots",
        ["symbol", "captured_at"],
    )

    # Cross-symbol time queries
    op.create_index(
        "ix_rs_captured_at",
        "regime_snapshots",
        ["captured_at"],
    )

    # Regime-filtered time-series (e.g. "show all trending bars for NIFTY")
    op.create_index(
        "ix_rs_symbol_regime_time",
        "regime_snapshots",
        ["symbol", "regime", "captured_at"],
    )

    # snapshot_id FK index
    op.create_index(
        "ix_rs_snapshot_id",
        "regime_snapshots",
        ["snapshot_id"],
    )


def downgrade():
    op.drop_index("ix_rs_snapshot_id",       table_name="regime_snapshots")
    op.drop_index("ix_rs_symbol_regime_time", table_name="regime_snapshots")
    op.drop_index("ix_rs_captured_at",        table_name="regime_snapshots")
    op.drop_index("ix_rs_symbol_time",        table_name="regime_snapshots")
    op.drop_table("regime_snapshots")
