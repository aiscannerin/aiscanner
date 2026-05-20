"""extend scan_jobs and scan_results with persistence fields

Revision ID: c3d4e5f6a7b8
Revises: e5de22952863
Create Date: 2026-05-10 00:00:00.000000

Adds denormalised columns to scan_jobs for run-level metrics and to
scan_results for per-symbol queryable fields.  result_data JSONB blob is
kept intact as the canonical full payload.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision     = 'c3d4e5f6a7b8'
down_revision = 'e5de22952863'
branch_labels = None
depends_on    = None


def upgrade():
    # ── scan_jobs new columns ─────────────────────────────────────────────────
    with op.batch_alter_table('scan_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scanner_name',    sa.String(100),  nullable=True))
        batch_op.add_column(sa.Column('ltf',             sa.String(20),   nullable=True))
        batch_op.add_column(sa.Column('scan_mode',       sa.String(20),   nullable=True))
        batch_op.add_column(sa.Column('candidate_mode',  sa.String(20),   nullable=True))
        batch_op.add_column(sa.Column('confirmed_count', sa.Integer(),    nullable=True))
        batch_op.add_column(sa.Column('watchlist_count', sa.Integer(),    nullable=True))
        batch_op.add_column(sa.Column('near_miss_count', sa.Integer(),    nullable=True))
        batch_op.add_column(sa.Column('no_result_count', sa.Integer(),    nullable=True))
        batch_op.add_column(sa.Column('fetch_elapsed_s', sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('scan_elapsed_s',  sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('cache_hits',      sa.Integer(),    nullable=True))
        batch_op.add_column(sa.Column('cache_misses',    sa.Integer(),    nullable=True))

    # ── scan_results new columns ──────────────────────────────────────────────
    with op.batch_alter_table('scan_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('classification',       sa.String(30),   nullable=True))
        batch_op.add_column(sa.Column('watchlist_level',      sa.String(5),    nullable=True))
        batch_op.add_column(sa.Column('watchlist_level_label',sa.String(120),  nullable=True))
        batch_op.add_column(sa.Column('current_stage_label',  sa.String(150),  nullable=True))
        batch_op.add_column(sa.Column('trade_plan_type',      sa.String(30),   nullable=True))
        batch_op.add_column(sa.Column('liquidity_source',     sa.String(50),   nullable=True))
        batch_op.add_column(sa.Column('entry',                sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('stop_loss',            sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('target_1',             sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('target_2',             sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('risk',                 sa.Float(),      nullable=True))
        batch_op.add_column(sa.Column('sequence_valid',       sa.Boolean(),    nullable=True))
        batch_op.add_column(sa.Column('entry_ready',          sa.Boolean(),    nullable=True))
        batch_op.add_column(sa.Column(
            'quality_flags',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'checklist',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'debug_trace',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ))
        # index for symbol history queries
        batch_op.create_index('ix_scan_results_symbol', ['symbol'], unique=False)
        # index for classification filter queries
        batch_op.create_index('ix_scan_results_classification', ['classification'], unique=False)


def downgrade():
    with op.batch_alter_table('scan_results', schema=None) as batch_op:
        batch_op.drop_index('ix_scan_results_classification')
        batch_op.drop_index('ix_scan_results_symbol')
        for col in [
            'debug_trace', 'checklist', 'quality_flags', 'entry_ready',
            'sequence_valid', 'risk', 'target_2', 'target_1', 'stop_loss',
            'entry', 'liquidity_source', 'trade_plan_type', 'current_stage_label',
            'watchlist_level_label', 'watchlist_level', 'classification',
        ]:
            batch_op.drop_column(col)

    with op.batch_alter_table('scan_jobs', schema=None) as batch_op:
        for col in [
            'cache_misses', 'cache_hits', 'scan_elapsed_s', 'fetch_elapsed_s',
            'no_result_count', 'near_miss_count', 'watchlist_count', 'confirmed_count',
            'candidate_mode', 'scan_mode', 'ltf', 'scanner_name',
        ]:
            batch_op.drop_column(col)
