"""Add immutable evidence portrait snapshots; existing archives remain untouched."""
from alembic import op
import sqlalchemy as sa

revision = "8e3b091c2d40"
down_revision = "54f51b05aa83"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("portrait_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("archive_id", sa.String(36), sa.ForeignKey("archives.id"), nullable=False, unique=True),
        sa.Column("rule_version", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False))


def downgrade():
    op.drop_table("portrait_snapshots")
