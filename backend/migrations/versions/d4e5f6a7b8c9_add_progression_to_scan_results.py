"""Add progression fields to scan_results

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-10
"""

from alembic import op
import sqlalchemy as sa

revision       = 'd4e5f6a7b8c9'
down_revision  = 'c3d4e5f6a7b8'
branch_labels  = None
depends_on     = None


def upgrade():
    with op.batch_alter_table('scan_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('progression_type',          sa.String(40),    nullable=True))
        batch_op.add_column(sa.Column('progression_label',         sa.String(120),   nullable=True))
        batch_op.add_column(sa.Column('progression_priority',      sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column('previous_scan_result_id',   sa.UUID(),        nullable=True))
        batch_op.add_column(sa.Column('previous_status',           sa.String(30),    nullable=True))
        batch_op.add_column(sa.Column('previous_watchlist_level',  sa.String(10),    nullable=True))
        batch_op.add_column(sa.Column('previous_score',            sa.Float(),       nullable=True))
        batch_op.create_index('ix_scan_results_progression_type', ['progression_type'])
        batch_op.create_index('ix_scan_results_progression_priority', ['progression_priority'])


def downgrade():
    with op.batch_alter_table('scan_results', schema=None) as batch_op:
        batch_op.drop_index('ix_scan_results_progression_priority')
        batch_op.drop_index('ix_scan_results_progression_type')
        batch_op.drop_column('previous_score')
        batch_op.drop_column('previous_watchlist_level')
        batch_op.drop_column('previous_status')
        batch_op.drop_column('previous_scan_result_id')
        batch_op.drop_column('progression_priority')
        batch_op.drop_column('progression_label')
        batch_op.drop_column('progression_type')
