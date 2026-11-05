"""Create initial manager and teacher without demo users or password output."""
import getpass
from sqlalchemy import select
from app.db import connect, User
from app.main import password_hash

def main():
    _, factory = connect()
    with factory.begin() as session:
        for role in ('manager', 'teacher'):
            username = input(f'{role} username: ').strip()
            name = input(f'{role} display name: ').strip()
            if not username or not name:
                raise SystemExit('Username and display name are required')
            if session.scalar(select(User).where(User.username == username)):
                raise SystemExit('Account already exists; refusing to reset it')
            password = getpass.getpass(f'{role} password (12+ characters): ')
            if len(password) < 12 or password != getpass.getpass('Repeat password: '):
                raise SystemExit('Password too short or confirmation differs')
            session.add(User(username=username, name=name, role=role, password_hash=password_hash(password)))
    print('Initial accounts created. No demo students were imported.')

if __name__ == '__main__':
    main()
