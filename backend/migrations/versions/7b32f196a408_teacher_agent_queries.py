"""Add teacher query conversations, turns, and run receipts."""
from alembic import op
import sqlalchemy as sa

revision = "7b32f196a408"
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
        "query_turn",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("query_conversation.id"), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("parent_turn_id", sa.String(36), sa.ForeignKey("query_turn.id"), nullable=True),
        sa.Column("input_mode", sa.String(30), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_patch", sa.JSON(), nullable=True),
        sa.Column("resolved_query_spec", sa.JSON(), nullable=True),
        sa.Column("planner_trace", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("clarification_payload", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("conversation_id", "turn_index", name="uq_query_turn_conv_index"),
    )
    op.create_index("ix_query_turn_conversation_id", "query_turn", ["conversation_id"])
    op.create_table(
        "query_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("query_conversation.id"), nullable=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("query_turn.id"), nullable=True),
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
    op.drop_table("query_turn")
    op.drop_table("query_conversation")
