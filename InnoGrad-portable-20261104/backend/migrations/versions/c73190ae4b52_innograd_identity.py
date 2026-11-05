"""Brand existing sample institutional accounts without changing authentication."""
from alembic import op
import sqlalchemy as sa
revision='c73190ae4b52'
down_revision='b10d4f2a1930'
branch_labels=None
depends_on=None

def upgrade():
    connection=op.get_bind()
    for username,old_name in [('teacher','演示导师'),('manager','演示管理教师')]:
        connection.execute(sa.text('UPDATE users SET name=:new WHERE username=:username AND name=:old'),
            {'new':'上海智能教育研究院','username':username,'old':old_name})

def downgrade():
    connection=op.get_bind()
    for username,old_name in [('teacher','演示导师'),('manager','演示管理教师')]:
        connection.execute(sa.text('UPDATE users SET name=:old WHERE username=:username AND name=:new'),
            {'new':'上海智能教育研究院','username':username,'old':old_name})
