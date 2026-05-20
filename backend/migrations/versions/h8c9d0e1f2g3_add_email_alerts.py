"""Add user_alert_settings table; add email tracking to scanner_notifications

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-05-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = 'h8c9d0e1f2g3'
down_revision = 'g7b8c9d0e1f2'
branch_labels = None
depends_on    = None


def upgrade():
    # ── user_alert_settings ────────────────────────────────────────────────────
    op.create_table(
        'user_alert_settings',

        sa.Column('id',                    postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id',               postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('email_alerts_enabled',  sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('email_address',         sa.String(254), nullable=True),
        sa.Column('created_at',            sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at',            sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )

    # One settings row per user
    op.create_unique_constraint(
        'uq_alert_settings_user_id', 'user_alert_settings', ['user_id']
    )
    op.create_index('ix_alert_settings_user_id', 'user_alert_settings', ['user_id'])

    # ── email tracking columns on scanner_notifications ─────────────────────────
    op.add_column('scanner_notifications',
        sa.Column('email_sent',    sa.Boolean(),              nullable=False,
                  server_default='false'))
    op.add_column('scanner_notifications',
        sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('scanner_notifications',
        sa.Column('email_error',   sa.String(200),             nullable=True))


def downgrade():
    op.drop_column('scanner_notifications', 'email_error')
    op.drop_column('scanner_notifications', 'email_sent_at')
    op.drop_column('scanner_notifications', 'email_sent')
    op.drop_table('user_alert_settings')
