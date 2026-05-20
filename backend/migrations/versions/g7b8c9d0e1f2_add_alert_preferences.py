"""Add alert preferences to user_tracked_symbols; add notification_scope to scanner_notifications

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision      = 'g7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on    = None


def upgrade():
    # ── alert preference columns on user_tracked_symbols ───────────────────────
    op.add_column('user_tracked_symbols',
        sa.Column('alert_became_confirmed',        sa.Boolean(), nullable=False,
                  server_default='true'))
    op.add_column('user_tracked_symbols',
        sa.Column('alert_improved_level',          sa.Boolean(), nullable=False,
                  server_default='true'))
    op.add_column('user_tracked_symbols',
        sa.Column('alert_became_watchlist',        sa.Boolean(), nullable=False,
                  server_default='true'))
    op.add_column('user_tracked_symbols',
        sa.Column('alert_degraded',                sa.Boolean(), nullable=False,
                  server_default='false'))
    op.add_column('user_tracked_symbols',
        sa.Column('alert_score_crossed_threshold', sa.Boolean(), nullable=False,
                  server_default='false'))
    op.add_column('user_tracked_symbols',
        sa.Column('score_threshold',               sa.Integer(), nullable=True))

    # ── notification_scope on scanner_notifications ───────────────────────────
    op.add_column('scanner_notifications',
        sa.Column('notification_scope', sa.String(20), nullable=False,
                  server_default='global'))

    op.create_index('ix_notif_scope', 'scanner_notifications', ['notification_scope'])


def downgrade():
    op.drop_index('ix_notif_scope', table_name='scanner_notifications')
    op.drop_column('scanner_notifications', 'notification_scope')

    for col in [
        'score_threshold', 'alert_score_crossed_threshold',
        'alert_degraded', 'alert_became_watchlist',
        'alert_improved_level', 'alert_became_confirmed',
    ]:
        op.drop_column('user_tracked_symbols', col)
