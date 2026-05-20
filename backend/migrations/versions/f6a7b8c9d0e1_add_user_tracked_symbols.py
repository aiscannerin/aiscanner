"""Add user_tracked_symbols table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision    = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'user_tracked_symbols',

        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'), nullable=False),

        sa.Column('user_id',      postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),

        sa.Column('symbol',       sa.String(50),  nullable=False),
        sa.Column('scanner_name', sa.String(100), nullable=False),
        sa.Column('htf',          sa.String(10),  nullable=False),
        sa.Column('ltf',          sa.String(10),  nullable=True),
        sa.Column('note',         sa.Text(),       nullable=True),
        sa.Column('is_active',    sa.Boolean(),    nullable=False, server_default='true'),

        sa.Column('created_at',   sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at',   sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )

    # Unique: prevent active duplicate tracking for same user+symbol+scanner+htf+ltf
    op.create_unique_constraint(
        'uq_tracked_active_combo',
        'user_tracked_symbols',
        ['user_id', 'symbol', 'scanner_name', 'htf', 'ltf'],
    )

    op.create_index('ix_tracked_user_id',    'user_tracked_symbols', ['user_id'])
    op.create_index('ix_tracked_symbol',     'user_tracked_symbols', ['symbol'])
    op.create_index('ix_tracked_is_active',  'user_tracked_symbols', ['is_active'])


def downgrade():
    op.drop_table('user_tracked_symbols')
