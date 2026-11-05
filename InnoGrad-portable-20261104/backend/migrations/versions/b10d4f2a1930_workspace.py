"""Persist workspace records; frozen schema for reproducible migrations."""
from alembic import op
import sqlalchemy as sa
revision = 'b10d4f2a1930'
down_revision = '8e3b091c2d40'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('student_profiles',
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id'), primary_key=True, nullable=False),
        sa.Column('number', sa.String(length=100), unique=True, nullable=False),
        sa.Column('year', sa.String(length=30), nullable=False),
        sa.Column('major', sa.String(length=100), nullable=False),
        sa.Column('direction', sa.String(length=200), nullable=False),
        sa.Column('stage', sa.String(length=60), nullable=False),
    )
    op.create_table('rule_templates',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('requirements', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
    )
    op.create_table('student_imports',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('created_by', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('rows', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
    )
    op.create_table('follow_ups',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('student_id', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('task_id', sa.String(length=36), sa.ForeignKey('cultivation_tasks.id'), nullable=True),
        sa.Column('created_by', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('lock_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.Column('updated_at', sa.String(length=40), nullable=False),
    )
    op.create_table('worker_heartbeats',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('last_seen', sa.String(length=40), nullable=False),
    )

def downgrade():
    op.drop_table('worker_heartbeats')
    op.drop_table('follow_ups')
    op.drop_table('student_imports')
    op.drop_table('rule_templates')
    op.drop_table('student_profiles')
