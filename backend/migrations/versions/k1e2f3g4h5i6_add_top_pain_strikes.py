"""add top_pain_strikes column to max_pain_snapshots

Revision ID: k1e2f3g4h5i6
Revises: j0d1e2f3g4h5
Create Date: 2026-05-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "k1e2f3g4h5i6"
down_revision = "j0d1e2f3g4h5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "max_pain_snapshots",
        sa.Column("top_pain_strikes", postgresql.JSONB, nullable=True),
    )


def downgrade():
    op.drop_column("max_pain_snapshots", "top_pain_strikes")
