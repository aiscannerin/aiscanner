"""Add scan_health columns to scan_jobs

Revision ID: i9c0d1e2f3g4
Revises: h8c9d0e1f2g3
Create Date: 2026-05-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = 'i9c0d1e2f3g4'
down_revision = 'h8c9d0e1f2g3'
branch_labels = None
depends_on    = None


def upgrade():
    # ── scan_health_json: full structured health object ────────────────────────
    op.add_column('scan_jobs',
        sa.Column('scan_health_json', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True))

    # ── denormalised health columns (for fast DB queries / filtering) ─────────
    op.add_column('scan_jobs',
        sa.Column('symbols_requested', sa.Integer(), nullable=True))
    op.add_column('scan_jobs',
        sa.Column('symbols_scanned',   sa.Integer(), nullable=True))
    op.add_column('scan_jobs',
        sa.Column('symbols_failed',    sa.Integer(), nullable=True))
    op.add_column('scan_jobs',
        sa.Column('partial_scan',      sa.Boolean(), nullable=True))
    op.add_column('scan_jobs',
        sa.Column('data_quality',      sa.String(10), nullable=True))  # good|partial|poor

    # Index for quick quality-based queries
    op.create_index('ix_scan_jobs_data_quality', 'scan_jobs', ['data_quality'])


def downgrade():
    op.drop_index('ix_scan_jobs_data_quality', table_name='scan_jobs')
    op.drop_column('scan_jobs', 'data_quality')
    op.drop_column('scan_jobs', 'partial_scan')
    op.drop_column('scan_jobs', 'symbols_failed')
    op.drop_column('scan_jobs', 'symbols_scanned')
    op.drop_column('scan_jobs', 'symbols_requested')
    op.drop_column('scan_jobs', 'scan_health_json')
