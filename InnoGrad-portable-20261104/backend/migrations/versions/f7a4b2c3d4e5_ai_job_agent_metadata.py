"""store agent execution metadata and error codes"""

from alembic import op
import sqlalchemy as sa

revision = "f7a4b2c3d4e5"
down_revision = "ef8e0d3a1f2b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_jobs", sa.Column("error_code", sa.String(length=40), nullable=True))
    op.add_column("ai_jobs", sa.Column("agent_session_id", sa.String(length=120), nullable=True))
    op.add_column("ai_jobs", sa.Column("skill_version", sa.String(length=120), nullable=True))
    op.add_column("ai_jobs", sa.Column("response_model", sa.String(length=120), nullable=True))


def downgrade():
    op.drop_column("ai_jobs", "response_model")
    op.drop_column("ai_jobs", "skill_version")
    op.drop_column("ai_jobs", "agent_session_id")
    op.drop_column("ai_jobs", "error_code")
