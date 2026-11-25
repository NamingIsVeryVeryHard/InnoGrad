"""Add teacher query conversations with embedded turns and run receipts."""
from alembic import op
import sqlalchemy as sa

revision = "5f2e71c609bd"
down_revision = "f1a4928d7e60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "query_conversation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="新对话"),
        sa.Column("active_domain", sa.String(30), nullable=False, server_default="paper"),
        sa.Column("active_query_spec", sa.JSON(), nullable=True),
        sa.Column("turns_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("scope_digest_snapshot", sa.String(64), nullable=False),
        sa.Column("scope_size_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_query_conversation_teacher_updated", "query_conversation", ["teacher_id", "updated_at"])
    op.create_table(
        "query_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("query_conversation.id"), nullable=True),
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("parent_run_id", sa.String(36), sa.ForeignKey("query_run.id"), nullable=True),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("domain", sa.String(30), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("basis", sa.String(40), nullable=False),
        sa.Column("applied_query", sa.JSON(), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("scope_size", sa.Integer(), nullable=False),
        sa.Column("data_as_of", sa.String(40), nullable=False),
        sa.Column("result_version", sa.String(40), nullable=False),
        sa.Column("metric_receipt", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_query_run_teacher_created", "query_run", ["teacher_id", "created_at"])
    op.create_index("ix_query_run_turn_id", "query_run", ["turn_id"])


def downgrade():
    op.drop_table("query_run")
    op.drop_table("query_conversation")
