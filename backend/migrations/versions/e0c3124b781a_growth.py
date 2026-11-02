"""Evidence-linked growth entries and immutable warning actions."""
from alembic import op
import sqlalchemy as sa
revision='e0c3124b781a'
down_revision='d9a4c8b12031'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('growth_entries',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('student_id', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_by', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('period', sa.String(length=80), nullable=False),
        sa.Column('dimension', sa.String(length=30), nullable=True),
        sa.Column('due_date', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('source_version_id', sa.String(length=36), sa.ForeignKey('submission_versions.id'), nullable=True),
        sa.Column('source_field', sa.String(length=100), nullable=True),
        sa.Column('source_quote', sa.Text(), nullable=True),
        sa.Column('lock_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.Column('updated_at', sa.String(length=40), nullable=False),
    )
    op.create_table('warning_actions',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('warning_key', sa.String(length=64), nullable=False),
        sa.Column('student_id', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('actor_id', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_warning_actions_warning_key','warning_actions',['warning_key'])

def downgrade():
    op.drop_index('ix_warning_actions_warning_key',table_name='warning_actions')
    op.drop_table('warning_actions')
    op.drop_table('growth_entries')
