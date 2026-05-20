"""Add scanner_notifications table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa

revision      = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'scanner_notifications',
        sa.Column('id',                sa.UUID(),          nullable=False),
        sa.Column('user_id',           sa.UUID(),          nullable=True),
        sa.Column('scan_run_id',       sa.UUID(),          nullable=True),
        sa.Column('scan_result_id',    sa.UUID(),          nullable=True),
        sa.Column('symbol',            sa.String(50),      nullable=False),
        sa.Column('notification_type', sa.String(50),      nullable=False),
        sa.Column('title',             sa.String(200),     nullable=False),
        sa.Column('message',           sa.Text(),          nullable=False),
        sa.Column('priority',          sa.Integer(),       nullable=False, server_default='0'),
        sa.Column('is_read',           sa.Boolean(),       nullable=False, server_default='false'),
        sa.Column('created_at',        sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'],        ['users.id'],        ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scan_run_id'],    ['scan_jobs.id'],    ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['scan_result_id'], ['scan_results.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scan_result_id', name='uq_notification_scan_result_id'),
        sa.UniqueConstraint('symbol', 'notification_type', 'scan_run_id',
                            name='uq_notification_symbol_type_run'),
    )
    op.create_index('ix_notif_user_read',    'scanner_notifications', ['user_id', 'is_read'])
    op.create_index('ix_notif_created_at',   'scanner_notifications', ['created_at'])
    op.create_index('ix_notif_symbol',       'scanner_notifications', ['symbol'])


def downgrade():
    op.drop_index('ix_notif_symbol',     table_name='scanner_notifications')
    op.drop_index('ix_notif_created_at', table_name='scanner_notifications')
    op.drop_index('ix_notif_user_read',  table_name='scanner_notifications')
    op.drop_table('scanner_notifications')
