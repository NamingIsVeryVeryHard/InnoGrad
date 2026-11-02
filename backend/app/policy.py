"""Current development authorization; all consumers recheck active scope."""
from sqlalchemy import select
from .db import Supervision, now


def relation(session, teacher, student):
    return session.scalar(select(Supervision).where(
        Supervision.teacher_id == teacher, Supervision.student_id == student,
        Supervision.valid_from <= now(),
        (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now())))


def can_read(session, user, sub):
    if not user or not user.enabled or not sub:
        return False
    if sub.student_id == user.id:
        return True
    return bool(sub.current_version_id and user.role in ("teacher", "manager") and
                relation(session, user.id, sub.student_id))
