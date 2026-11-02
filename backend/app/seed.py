"""Explicitly create synthetic accounts; never automatically seed application startup."""
import secrets
from sqlalchemy import select
from .db import User, Supervision, StudentProfile, now, connect
from .main import password_hash


def seed(factory):
    credentials = {}
    with factory.begin() as session:
        users = {}
        for username, name, role in [
            ("student1", "演示学生一", "student"), ("student2", "演示学生二", "student"),
            ("teacher", "上海智能教育研究院", "teacher"), ("manager", "上海智能教育研究院", "manager"),
            ("operator", "演示技术管理员", "operator")]:
            existing = session.scalar(select(User).where(User.username == username))
            if existing:
                raise RuntimeError("Demo accounts already exist; refusing to reset passwords")
            password = secrets.token_urlsafe(12)
            user = User(username=username, name=name, role=role, password_hash=password_hash(password))
            session.add(user)
            session.flush()
            users[username] = user
            credentials[username] = password
        for username, degree, major in [('student1','博士','智能教育'),('student2','硕士','人工智能')]:
            session.add(StudentProfile(user_id=users[username].id,number=username,degree=degree,major=major,year='待补录',direction='待补录',stage='待补录'))
        for teacher in ("teacher", "manager"):
            for student in ("student1", "student2"):
                session.add(Supervision(teacher_id=users[teacher].id, student_id=users[student].id, valid_from=now()))
    return credentials


if __name__ == "__main__":
    _, factory = connect()
    for username, password in seed(factory).items():
        print(f"{username}: {password}")
