"""Authorize bounded teacher agent tool calls across API workers."""
import sqlalchemy as sa
from alembic import op

revision = "a731c5e21984"
down_revision = "7b32f196a408"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "query_turn_grant",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("query_conversation.id"), nullable=False, unique=True),
        sa.Column("turn_id", sa.String(36), nullable=False, unique=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("selected", sa.JSON(), nullable=False),
        sa.Column("calls", sa.JSON(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("query_turn_grant")
