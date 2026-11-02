"""Review retry scheduling, outbox failure isolation and upload timestamps."""
from alembic import op
import sqlalchemy as sa

revision = "a81cb4d62009"
down_revision = "f7a4b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("ai_jobs", sa.Column("next_attempt_at", sa.String(40), nullable=True))
    op.add_column("ai_jobs", sa.Column("agent_metadata", sa.JSON(), nullable=True))
    op.add_column("outbox_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outbox_events", sa.Column("next_attempt_at", sa.String(40), nullable=True))
    op.add_column("outbox_events", sa.Column("error_code", sa.String(40), nullable=True))
    # Existing files predate upload timestamp tracking; preserve that distinction.
    op.add_column("files", sa.Column("created_at", sa.String(40), nullable=False, server_default="unknown"))


def downgrade():
    op.drop_column("files", "created_at")
    for column in ("error_code", "next_attempt_at", "attempts"):
        op.drop_column("outbox_events", column)
    for column in ("agent_metadata", "next_attempt_at", "max_attempts"):
        op.drop_column("ai_jobs", column)
