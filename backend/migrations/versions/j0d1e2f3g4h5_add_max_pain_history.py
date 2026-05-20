"""add max pain history tables

Revision ID: j0d1e2f3g4h5
Revises: i9c0d1e2f3g4
Create Date: 2026-05-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "j0d1e2f3g4h5"
down_revision = "i9c0d1e2f3g4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "max_pain_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("symbol",      sa.String(30),  nullable=False),
        sa.Column("expiry",      sa.String(30),  nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        # Price
        sa.Column("spot_price",   sa.Float, nullable=True),
        sa.Column("max_pain",     sa.Float, nullable=True),
        sa.Column("distance_pct", sa.Float, nullable=True),
        sa.Column("direction",    sa.String(10), nullable=True),

        # OI
        sa.Column("total_ce_oi", sa.BigInteger, nullable=True),
        sa.Column("total_pe_oi", sa.BigInteger, nullable=True),
        sa.Column("pcr",         sa.Float,      nullable=True),
        sa.Column("pcr_bias",    sa.String(10), nullable=True),

        # OI walls
        sa.Column("ce_wall_strike", sa.Float,      nullable=True),
        sa.Column("ce_wall_oi",     sa.BigInteger, nullable=True),
        sa.Column("pe_wall_strike", sa.Float,      nullable=True),
        sa.Column("pe_wall_oi",     sa.BigInteger, nullable=True),

        # IV
        sa.Column("atm_ce_iv", sa.Float, nullable=True),
        sa.Column("atm_pe_iv", sa.Float, nullable=True),
        sa.Column("avg_iv",    sa.Float, nullable=True),

        # Volume
        sa.Column("total_ce_volume", sa.BigInteger, nullable=True),
        sa.Column("total_pe_volume", sa.BigInteger, nullable=True),

        # Reversal score
        sa.Column("reversal_score",    sa.Float,      nullable=True),
        sa.Column("reversal_category", sa.String(20), nullable=True),

        # JSONB
        sa.Column("top_ce_strikes", postgresql.JSONB, nullable=True),
        sa.Column("top_pe_strikes", postgresql.JSONB, nullable=True),
    )

    op.create_index("ix_mps_symbol_time",    "max_pain_snapshots", ["symbol", "captured_at"])
    op.create_index("ix_mps_captured_at",    "max_pain_snapshots", ["captured_at"])
    op.create_index("ix_mps_symbol_expiry",  "max_pain_snapshots", ["symbol", "expiry", "captured_at"])
    op.create_index("ix_mps_distance_pct",   "max_pain_snapshots", ["distance_pct"])
    op.create_index("ix_mps_reversal_score", "max_pain_snapshots", ["reversal_score"])

    op.create_table(
        "oi_wall_snapshots",
        sa.Column("id",          postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("symbol",      sa.String(30), nullable=False),
        sa.Column("expiry",      sa.String(30), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("side",        sa.String(3),      nullable=False),   # CE | PE
        sa.Column("rank",        sa.Integer,         nullable=False),
        sa.Column("strike",      sa.Float,           nullable=False),
        sa.Column("oi",          sa.BigInteger,      nullable=False),
        sa.Column("oi_change",   sa.BigInteger,      nullable=True),
    )

    op.create_index("ix_oiws_symbol_side_time", "oi_wall_snapshots", ["symbol", "side", "captured_at"])
    op.create_index("ix_oiws_symbol_time",      "oi_wall_snapshots", ["symbol", "captured_at"])
    op.create_index("ix_oiws_strike",           "oi_wall_snapshots", ["strike"])


def downgrade():
    op.drop_index("ix_oiws_strike",           table_name="oi_wall_snapshots")
    op.drop_index("ix_oiws_symbol_time",      table_name="oi_wall_snapshots")
    op.drop_index("ix_oiws_symbol_side_time", table_name="oi_wall_snapshots")
    op.drop_table("oi_wall_snapshots")

    op.drop_index("ix_mps_reversal_score", table_name="max_pain_snapshots")
    op.drop_index("ix_mps_distance_pct",   table_name="max_pain_snapshots")
    op.drop_index("ix_mps_symbol_expiry",  table_name="max_pain_snapshots")
    op.drop_index("ix_mps_captured_at",    table_name="max_pain_snapshots")
    op.drop_index("ix_mps_symbol_time",    table_name="max_pain_snapshots")
    op.drop_table("max_pain_snapshots")
