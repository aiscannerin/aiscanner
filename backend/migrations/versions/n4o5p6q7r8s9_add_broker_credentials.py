"""add_broker_credentials

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-05-22

Adds user_broker_credentials table — stores each user's broker (Dhan) API
credentials. The access token is encrypted at rest (Fernet); client_id is
plaintext. One row per (user, broker).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision      = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        "user_broker_credentials",

        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("broker", sa.String(20), nullable=False, server_default="dhan"),
        sa.Column("client_id", sa.String(50), nullable=False),
        sa.Column("access_token_encrypted", sa.Text, nullable=False),

        sa.Column("is_valid", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(255), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),

        sa.UniqueConstraint("user_id", "broker", name="uq_broker_cred_user_broker"),
    )

    op.create_index(
        "ix_broker_cred_user_id",
        "user_broker_credentials",
        ["user_id"],
    )


def downgrade():
    op.drop_index("ix_broker_cred_user_id", table_name="user_broker_credentials")
    op.drop_table("user_broker_credentials")
