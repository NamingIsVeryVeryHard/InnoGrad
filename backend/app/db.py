from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import os
from sqlalchemy import create_engine, event, String, Text, Integer, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[int] = mapped_column(Integer, default=1)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(40))


class Supervision(Base):
    __tablename__ = "supervisions"
    __table_args__ = (UniqueConstraint("student_id", "teacher_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    valid_from: Mapped[str] = mapped_column(String(40))
    valid_to: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Task(Base):
    __tablename__ = "cultivation_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    period: Mapped[str] = mapped_column(String(80))
    deadline: Mapped[str] = mapped_column(String(40))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    requirements: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Assignment(Base):
    __tablename__ = "task_assignments"
    __table_args__ = (UniqueConstraint("task_id", "student_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("cultivation_tasks.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("task_id", "student_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("cultivation_tasks.id"), nullable=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    lock_version: Mapped[int] = mapped_column(Integer, default=0)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    effective_archive_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Version(Base):
    __tablename__ = "submission_versions"
    __table_args__ = (UniqueConstraint("submission_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))
    number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class File(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))
    name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(36), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(40), default="other", server_default="other")
    status: Mapped[str] = mapped_column(String(30), default="ready")


class Decision(Base):
    __tablename__ = "review_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version_id: Mapped[str] = mapped_column(ForeignKey("submission_versions.id"), unique=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    actor_type: Mapped[str] = mapped_column(String(20), default="human", server_default="human")
    ai_job_id: Mapped[str | None] = mapped_column(ForeignKey("ai_jobs.id"), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))
    opinion: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Archive(Base):
    __tablename__ = "archives"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version_id: Mapped[str] = mapped_column(ForeignKey("submission_versions.id"), unique=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("review_decisions.id"), unique=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Idempotency(Base):
    __tablename__ = "idempotency"
    __table_args__ = (UniqueConstraint("user_id", "operation", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    operation: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class Outbox(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[str] = mapped_column(String(40), default=now)


def connect(url=None):
    Path("runtime").mkdir(exist_ok=True)
    url = url or os.getenv("DATABASE_URL", "sqlite:///runtime/development.db")
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 20} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_setup(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
    return engine, sessionmaker(engine, expire_on_commit=False)


class Correction(Base):
    __tablename__ = "corrections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))
    archive_id: Mapped[str] = mapped_column(ForeignKey("archives.id"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    opinion: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class ExportJob(Base):
    __tablename__ = "export_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    manifest: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    expires_at: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class AIJob(Base):
    __tablename__ = "ai_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("submission_versions.id"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    input_pack: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    execution_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ReviewChange(Base):
    __tablename__ = "review_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class PortraitSnapshot(Base):
    __tablename__ = "portrait_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    archive_id: Mapped[str] = mapped_column(ForeignKey("archives.id"), unique=True)
    rule_version: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class StudentProfile(Base):
    __tablename__ = 'student_profiles'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    number: Mapped[str] = mapped_column(String(100), unique=True)
    year: Mapped[str] = mapped_column(String(30))
    degree: Mapped[str] = mapped_column(String(20), default='未标注', server_default='未标注')
    major: Mapped[str] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(60), default='课程学习')


class RuleTemplate(Base):
    __tablename__ = 'rule_templates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    requirements: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class StudentImport(Base):
    __tablename__ = 'student_imports'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    rows: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default='preview')
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class FollowUp(Base):
    __tablename__ = 'follow_ups'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    task_id: Mapped[str | None] = mapped_column(ForeignKey('cultivation_tasks.id'), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(30), default='open')
    lock_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class WorkerHeartbeat(Base):
    __tablename__ = 'worker_heartbeats'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    last_seen: Mapped[str] = mapped_column(String(40))


class GrowthEntry(Base):
    __tablename__ = 'growth_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    period: Mapped[str] = mapped_column(String(80))
    dimension: Mapped[str | None] = mapped_column(String(30), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='planned')
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey('submission_versions.id'), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class WarningAction(Base):
    __tablename__ = 'warning_actions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    warning_key: Mapped[str] = mapped_column(String(64), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
