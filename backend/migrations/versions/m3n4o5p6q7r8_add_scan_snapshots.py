"""add_scan_snapshots

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-05-20

Adds scan_snapshots table — stores the full run_scanner() response
payload so off-hours frontend requests can be served from the latest
successful scan rather than returning an empty table.

Design:
  - payload_json is TEXT (not JSONB) for SQLite compatibility in tests
    and because we always read it whole, never project inside it.
  - threshold, symbol_count, avg_fetch_ms, scan_elapsed_ms are real
    columns so history queries can sort/filter without JSON extraction.
  - Three indexes cover the three access patterns:
      1. Latest per threshold  → ix_ss_threshold_time
      2. Global history list   → ix_ss_created_at
      3. Market status filter  → ix_ss_market_status
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision      = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        "scan_snapshots",

        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),

        # Timing
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),

        # Scan config
        sa.Column("threshold",        sa.Float,   nullable=False, server_default="2.0"),

        # Aggregate metrics
        sa.Column("symbol_count",     sa.Integer, nullable=True),
        sa.Column("avg_fetch_ms",     sa.Float,   nullable=True),
        sa.Column("scan_elapsed_ms",  sa.Float,   nullable=True),

        # Market context
        sa.Column("market_status",    sa.String(20), nullable=True),

        # Full payload
        sa.Column("payload_json",     sa.Text,    nullable=False),
    )

    # Index 1: latest snapshot per threshold
    op.create_index(
        "ix_ss_threshold_time",
        "scan_snapshots",
        ["threshold", "created_at"],
    )

    # Index 2: global chronological list
    op.create_index(
        "ix_ss_created_at",
        "scan_snapshots",
        ["created_at"],
    )

    # Index 3: market status filter
    op.create_index(
        "ix_ss_market_status",
        "scan_snapshots",
        ["market_status"],
    )


def downgrade():
    op.drop_index("ix_ss_market_status", table_name="scan_snapshots")
    op.drop_index("ix_ss_created_at",    table_name="scan_snapshots")
    op.drop_index("ix_ss_threshold_time", table_name="scan_snapshots")
    op.drop_table("scan_snapshots")
