import hashlib

from fastapi import HTTPException

from .db import LoginSession, User, now


def find_login(session, token):
    return session.get(LoginSession, hashlib.sha256(token.encode()).hexdigest()) if token else None


def login_user(session, login):
    if login is None or login.expires_at <= now():
        raise HTTPException(401, "请重新登录")
    user = session.get(User, login.user_id)
    if user is None or not user.enabled:
        raise HTTPException(401, "账号不可用")
    return user
