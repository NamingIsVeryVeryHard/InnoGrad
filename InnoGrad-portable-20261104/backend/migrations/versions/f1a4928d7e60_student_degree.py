"""Separate degree level from major; normalize only explicitly synthetic accounts."""
from uuid import uuid5,NAMESPACE_URL
from alembic import op
import sqlalchemy as sa
revision='f1a4928d7e60'
down_revision='e0c3124b781a'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('student_profiles',sa.Column('degree',sa.String(20),nullable=False,server_default='未标注'))
    conn=op.get_bind()
    for i in range(12):
        sid=str(uuid5(NAMESPACE_URL,f'innograd-synthetic-cohort-v1/s{i+1:02}'))
        degree,major=('硕士','人工智能') if i%2 else ('博士','智能教育')
        conn.execute(sa.text('UPDATE student_profiles SET degree=:degree, major=:major WHERE user_id=:sid AND user_id IN (SELECT id FROM users WHERE username=:username AND role=\'student\')'),
            dict(degree=degree,major=major,sid=sid,username=f'sim_student_{i+1:02}'))
    for username,name,degree,major in [('student1','演示学生一','博士','智能教育'),('student2','演示学生二','硕士','人工智能')]:
        sid=conn.execute(sa.text('SELECT id FROM users WHERE username=:u AND name=:n AND role=\'student\''),dict(u=username,n=name)).scalar()
        if not sid:continue
        exists=conn.execute(sa.text('SELECT user_id FROM student_profiles WHERE user_id=:sid'),dict(sid=sid)).scalar()
        if exists:
            conn.execute(sa.text('UPDATE student_profiles SET degree=:degree,major=:major WHERE user_id=:sid'),dict(degree=degree,major=major,sid=sid))
        else:
            conn.execute(sa.text('INSERT INTO student_profiles (user_id,number,year,major,direction,stage,degree) VALUES (:sid,:number,\'待补录\',:major,\'待补录\',\'待补录\',:degree)'),dict(sid=sid,number=username,major=major,degree=degree))

def downgrade():
    op.drop_column('student_profiles','degree')
