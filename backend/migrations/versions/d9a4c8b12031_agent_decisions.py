"""Record decision provenance without rebuilding archive-referenced SQLite tables."""
from alembic import op
import sqlalchemy as sa
revision='d9a4c8b12031'
down_revision='c73190ae4b52'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('review_decisions',sa.Column('actor_type',sa.String(20),nullable=False,server_default='human'))
    if op.get_bind().dialect.name=='sqlite':
        op.execute('ALTER TABLE review_decisions ADD COLUMN ai_job_id VARCHAR(36) REFERENCES ai_jobs(id)')
    else:
        op.add_column('review_decisions',sa.Column('ai_job_id',sa.String(36),nullable=True))
        op.create_foreign_key('fk_decision_ai_job','review_decisions','ai_jobs',['ai_job_id'],['id'])

def downgrade():
    if op.get_bind().dialect.name!='sqlite':
        op.drop_constraint('fk_decision_ai_job','review_decisions',type_='foreignkey')
    op.drop_column('review_decisions','ai_job_id')
    op.drop_column('review_decisions','actor_type')
