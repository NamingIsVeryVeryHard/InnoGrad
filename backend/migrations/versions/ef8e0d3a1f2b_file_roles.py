"""add frozen attachment roles"""

from alembic import op
import sqlalchemy as sa

revision = "ef8e0d3a1f2b"
down_revision = "f1a4928d7e60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("files", sa.Column("role", sa.String(length=40), server_default="other", nullable=False))


def downgrade():
    op.drop_column("files", "role")
