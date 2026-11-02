from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import hashlib
import hmac
import json
import os
import secrets
import zipfile
import io

from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File as Upload
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .db import (Base, User, LoginSession, Supervision, Task, Assignment, Submission,
                 Version, File, Decision, Archive, Idempotency, Outbox, Audit, connect, uid, now)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
    return f"{salt}${value}"


def verify(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split("$")[0]), encoded)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class CreateSubmission(Input):
    kind: Literal["paper", "annual"]
    task_id: str | None = None
    reviewer_id: str | None = None


class Draft(Input):
    expected_lock_version: int = Field(ge=0)
    form: dict
    file_ids: list[str] = Field(default_factory=list, max_length=30)
    reference_ids: list[str] = Field(default_factory=list, max_length=100)


class Submit(Input):
    expected_lock_version: int = Field(ge=0)


class Review(Submit):
    version_id: str
    outcome: Literal["approved", "returned"]
    opinion: str = Field(min_length=1, max_length=5000)


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=200)
    period: str = Field(min_length=1, max_length=80)
    deadline: datetime
    reviewer_id: str
    student_ids: list[str] = Field(min_length=1, max_length=500)
    rule_id: str = "annual-1"


def create_app(database_url=None, storage=None):
    app = FastAPI(title="InnoGrad · 上海智能教育研究院", version="0.3.0")
    engine, factory = connect(database_url)
    app.state.engine, app.state.sessions = engine, factory
    root = Path(storage or os.getenv("FILE_ROOT", "runtime/files"))
    root.mkdir(parents=True, exist_ok=True)

    def db():
        with factory() as session:
            yield session

    def error(code, message):
        raise HTTPException(code, message)

    def authenticated(request: Request, session=Depends(db)):
        token = request.cookies.get("session", "")
        login = session.get(LoginSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
        if not login or login.expires_at < now():
            error(401, "请重新登录")
        user = session.get(User, login.user_id)
        if not user or not user.enabled:
            error(401, "账号不可用")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), login.csrf):
                error(403, "请求校验失败，请重新登录")
        return user

    def audit(session, user, action, obj):
        session.add(Audit(actor_id=user.id, action=action, object_id=obj))

    from .policy import relation, can_read

    def accessible(session, user, sub):
        return can_read(session, user, sub)

    def get_sub(session, user, ident, owner=False):
        sub = session.get(Submission, ident)
        if not sub or not accessible(session, user, sub) or (owner and sub.student_id != user.id):
            error(404, "记录不存在或无权访问")
        return sub

    def cas(session, sub, expected, **values):
        result = session.execute(update(Submission).where(Submission.id == sub.id,
            Submission.lock_version == expected).values(lock_version=expected + 1, **values))
        if result.rowcount != 1:
            error(409, "版本已变化，请刷新后重试")
        session.flush()
        session.refresh(sub)

    def replay(session, request, user, body):
        key = request.headers.get("Idempotency-Key", "")
        if not key or len(key) > 100:
            error(422, "必须提供长度不超过 100 的 Idempotency-Key")
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        operation = request.url.path
        previous = session.scalar(select(Idempotency).where(Idempotency.user_id == user.id,
            Idempotency.operation == operation, Idempotency.key == key))
        if previous:
            if previous.request_hash != digest:
                error(409, "幂等键已用于其他内容")
            return previous.response, None
        return None, dict(user_id=user.id, operation=operation, key=key, request_hash=digest)

    def finish(session, idem, result):
        session.add(Idempotency(**idem, response=result))
        session.commit()
        return result

    def serialize(session, user, sub):
        versions = session.scalars(select(Version).where(Version.submission_id == sub.id).order_by(Version.number)).all()
        version_ids = [v.id for v in versions]
        decisions = session.scalars(select(Decision).where(Decision.version_id.in_(version_ids))).all() if version_ids else []
        from .db import Correction, AIJob, ReviewChange
        corrections = session.scalars(select(Correction).where(Correction.submission_id == sub.id).order_by(Correction.created_at)).all()
        ai_jobs = session.scalars(select(AIJob).where(AIJob.submission_id == sub.id).order_by(AIJob.created_at)).all()
        changes = session.scalars(select(ReviewChange).where(ReviewChange.submission_id == sub.id).order_by(ReviewChange.created_at)).all()
        visible_file_ids = {fid for v in versions for fid in v.snapshot.get('file_ids', [])}
        if user.id == sub.student_id:
            visible_file_ids.update(sub.draft.get('file_ids', []))
        files = session.scalars(select(File).where(File.id.in_(visible_file_ids), File.submission_id == sub.id)).all()
        archive = session.get(Archive, sub.effective_archive_id) if sub.effective_archive_id else None
        archived_version = session.get(Version, archive.version_id) if archive else None
        return dict(created_at=sub.created_at,
            files=[dict(id=f.id, name=f.name, size=f.size, media_type=f.media_type, sha256=f.sha256) for f in files],
            effective_archive=dict(id=archive.id, version_id=archive.version_id, number=archived_version.number,
                snapshot=archived_version.snapshot, created_at=archive.created_at) if archive else None,
            corrections=[dict(id=c.id, reason=c.reason, status=c.status, opinion=c.opinion, archive_id=c.archive_id) for c in corrections],
            ai_jobs=[dict(id=j.id, status=j.status, version_id=j.version_id, mode=j.config['mode']) for j in ai_jobs],
            reviewer_changes=[dict(reviewer_id=c.reviewer_id, actor_id=c.actor_id, reason=c.reason, created_at=c.created_at) for c in changes],
            id=sub.id, student_id=sub.student_id, kind=sub.kind, task_id=sub.task_id,
            reviewer_id=sub.reviewer_id, status=sub.status, lock_version=sub.lock_version,
            current_version_id=sub.current_version_id, effective_archive_id=sub.effective_archive_id,
            draft=sub.draft if user.id == sub.student_id else None,
            versions=[dict(id=v.id, number=v.number, snapshot=v.snapshot, created_at=v.created_at) for v in versions],
            decisions=[dict(version_id=d.version_id, outcome=d.outcome, opinion=d.opinion,
                            reviewer_id=d.reviewer_id, actor_type=d.actor_type, ai_job_id=d.ai_job_id, created_at=d.created_at) for d in decisions])

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": "记录已被处理或违反唯一约束，请刷新重试"})

    @app.get("/health")
    def health(session=Depends(db)):
        session.execute(select(1))
        return {"status": "ok", "ai_mode": os.getenv("AI_MODE", "rules"), "automatic_approval": os.getenv("REVIEW_WORKFLOW")=="agent", "environment": "development"}

    @app.post("/api/v1/auth/login")
    def login(body: Login, request: Request, response: Response, session=Depends(db)):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            error(403, "登录来源不允许")
        user = session.scalar(select(User).where(User.username == body.username))
        dummy = "0" * 32 + "$" + "0" * 64
        valid = verify(body.password, user.password_hash if user else dummy)
        if not user or not user.enabled or not valid:
            error(401, "账号或密码错误")
        token, csrf = secrets.token_urlsafe(32), secrets.token_hex(24)
        session.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
            csrf=csrf, expires_at=(datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()))
        audit(session, user, "login", user.id)
        session.commit()
        response.set_cookie("session", token, httponly=True, samesite="strict", max_age=28800,
                            secure=os.getenv("COOKIE_SECURE", "0") == "1")
        return {"csrf_token": csrf, "user": {"id": user.id, "name": user.name, "role": user.role}}

    @app.get("/api/v1/me")
    def me(request: Request, user=Depends(authenticated), session=Depends(db)):
        login = session.get(LoginSession, hashlib.sha256(request.cookies["session"].encode()).hexdigest())
        return {"id": user.id, "name": user.name, "role": user.role, "csrf_token": login.csrf}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, user=Depends(authenticated), session=Depends(db)):
        login = session.get(LoginSession, hashlib.sha256(request.cookies["session"].encode()).hexdigest())
        session.delete(login)
        session.commit()
        response.delete_cookie("session")
        return {"ok": True}

    @app.get("/api/v1/people")
    def people(user=Depends(authenticated), session=Depends(db)):
        relations = session.scalars(select(Supervision).where(
            (Supervision.student_id == user.id) | (Supervision.teacher_id == user.id),
            Supervision.valid_from <= now(),
            (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now()))).all()
        ids = {user.id} | {r.student_id for r in relations} | {r.teacher_id for r in relations}
        if user.role == "manager":
            students = {r.student_id for r in relations if r.teacher_id == user.id}
            ids.update(session.scalars(select(Supervision.teacher_id).where(
                Supervision.student_id.in_(students), Supervision.valid_from <= now(),
                (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now()))))
        return [{"id": u.id, "name": u.name, "role": u.role} for u in session.scalars(select(User).where(User.id.in_(ids)))]

    @app.post("/api/v1/cultivation-tasks", status_code=201)
    def create_task(body: TaskInput, request: Request, user=Depends(authenticated), session=Depends(db)):
        if user.role != "manager":
            error(403, "仅授权管理教师可发布任务")
        old, idem = replay(session, request, user, body.model_dump(mode="json"))
        if old is not None:
            return old
        students = set(body.student_ids)
        for ident in students:
            student = session.get(User, ident)
            if not student or student.role != "student" or not relation(session, user.id, ident):
                error(403, "包含未授权学生")
            reviewer = session.get(User, body.reviewer_id)
            if not reviewer or reviewer.role != "teacher" or not relation(session, body.reviewer_id, ident):
                error(422, "复核人必须对全部学生具有有效审核范围")
        if body.deadline.tzinfo is None:
            error(422, "截止时间必须包含时区")
        from .workspace import DEFAULT_RULE
        from .db import RuleTemplate
        requirements = DEFAULT_RULE['requirements']
        if body.rule_id != 'annual-1':
            rule = session.get(RuleTemplate, body.rule_id)
            if not rule or rule.created_by != user.id:
                error(404, '规则版本不存在或无权使用')
            requirements = rule.requirements
        task = Task(id=uid(), title=body.title, period=body.period,
            deadline=body.deadline.astimezone(timezone.utc).isoformat(), reviewer_id=body.reviewer_id,
            requirements=requirements, created_by=user.id)
        session.add(task)
        session.flush()
        for student in students:
            session.add(Assignment(task_id=task.id, student_id=student))
        audit(session, user, "task.published", task.id)
        return finish(session, idem, {"id": task.id})

    @app.get("/api/v1/me/tasks")
    def tasks(user=Depends(authenticated), session=Depends(db)):
        if user.role == "student":
            rows = session.scalars(select(Task).join(Assignment).where(Assignment.student_id == user.id)).all()
        elif user.role == "manager":
            rows = session.scalars(select(Task).where(Task.created_by == user.id)).all()
        else:
            rows = session.scalars(select(Task).where(Task.reviewer_id == user.id)).all()
        from .workspace import scope_ids
        allowed = set(scope_ids(session, user))
        result = []
        for t in rows:
            assigned = list(session.scalars(select(Assignment.student_id).where(Assignment.task_id == t.id)))
            visible = [sid for sid in assigned if sid in allowed]
            if visible:
                result.append(dict(id=t.id, title=t.title, period=t.period, deadline=t.deadline,
                    requirements=t.requirements, reviewer_id=t.reviewer_id, student_ids=visible))
        return result

    @app.post("/api/v1/submissions", status_code=201)
    def create(body: CreateSubmission, request: Request, user=Depends(authenticated), session=Depends(db)):
        if user.role != "student":
            error(403, "仅学生可创建本人材料")
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None:
            return old
        if body.kind == "annual":
            task = session.get(Task, body.task_id) if body.task_id else None
            if not task or not session.scalar(select(Assignment).where(Assignment.task_id == task.id, Assignment.student_id == user.id)):
                error(404, "没有该任务的提交资格")
            reviewer = task.reviewer_id
        else:
            if body.task_id:
                error(422, "论文申报不绑定年度任务")
            reviewer = body.reviewer_id
            teacher = session.get(User, reviewer) if reviewer else None
            if not teacher or teacher.role != "teacher" or not relation(session, reviewer, user.id):
                error(422, "请选择有效指导范围内的复核教师")
        sub = Submission(id=uid(), student_id=user.id, kind=body.kind, task_id=body.task_id,
                         reviewer_id=reviewer, draft={"form": {}, "file_ids": [], "reference_ids": []})
        session.add(sub)
        session.flush()
        audit(session, user, "submission.created", sub.id)
        return finish(session, idem, {"id": sub.id, "lock_version": 0})

    @app.get("/api/v1/submissions")
    def listing(offset: int = 0, limit: int = 100, user=Depends(authenticated), session=Depends(db)):
        if offset < 0 or limit < 1 or limit > 100: error(422, "分页参数无效")
        # Deliberately narrow initial development cohort; no unrestricted admin listing.
        if user.role == "student":
            query = select(Submission).where(Submission.student_id == user.id)
        else:
            allowed = select(Supervision.student_id).where(Supervision.teacher_id == user.id,
                Supervision.valid_from <= now(), (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now()))
            query = select(Submission).where(Submission.student_id.in_(allowed), Submission.current_version_id.is_not(None))
        rows = session.scalars(query.order_by(Submission.created_at.desc(), Submission.id).offset(offset).limit(limit)).all()
        return [serialize(session, user, s) for s in rows]

    @app.get("/api/v1/submissions/{ident}")
    def detail(ident: str, user=Depends(authenticated), session=Depends(db)):
        return serialize(session, user, get_sub(session, user, ident))

    @app.patch("/api/v1/submissions/{ident}/draft")
    def draft(ident: str, body: Draft, user=Depends(authenticated), session=Depends(db)):
        sub = get_sub(session, user, ident, owner=True)
        if sub.status not in ("draft", "returned"):
            error(409, "当前状态不可修改工作稿")
        if len(json.dumps(body.form, ensure_ascii=False)) > 100000:
            error(422, "表单内容过大")
        cas(session, sub, body.expected_lock_version, draft=body.model_dump(exclude={"expected_lock_version"}))
        audit(session, user, "draft.saved", sub.id)
        session.commit()
        return {"lock_version": sub.lock_version}

    @app.post("/api/v1/submissions/{ident}/files", status_code=201)
    async def upload(ident: str, file: UploadFile = Upload(...), user=Depends(authenticated), session=Depends(db)):
        sub = get_sub(session, user, ident, owner=True)
        if sub.status not in ("draft", "returned"):
            error(409, "当前版本不可增加附件")
        data = await file.read(50 * 1024 * 1024 + 1)
        if not data or len(data) > 50 * 1024 * 1024:
            error(422, "文件为空或超过 50 MB")
        name = Path((file.filename or "file").replace("\\", "/")).name[:255]
        suffix = Path(name).suffix.lower()
        media = None
        if suffix == ".pdf" and data.startswith(b"%PDF-"):
            media = "application/pdf"
        elif suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
            media = "image/png"
        elif suffix in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff"):
            media = "image/jpeg"
        elif suffix == ".docx":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as doc:
                    entries = doc.infolist()
                    if len(entries) <= 2000 and sum(i.file_size for i in entries) <= 200 * 1024 * 1024 and "word/document.xml" in doc.namelist() and "[Content_Types].xml" in doc.namelist():
                        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            except (zipfile.BadZipFile, OSError):
                pass
        if not media:
            error(422, "文件内容与允许格式不符")
        key = uid()
        path = root / key
        path.write_bytes(data)
        row = File(id=uid(), owner_id=user.id, submission_id=sub.id, name=name, media_type=media,
                   storage_key=key, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        session.add(row)
        audit(session, user, "file.uploaded", row.id)
        try:
            session.commit()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {"id": row.id, "name": row.name, "status": row.status, "size": row.size}

    @app.get("/api/v1/files/{ident}/download")
    def download(ident: str, user=Depends(authenticated), session=Depends(db)):
        row = session.get(File, ident)
        if not row:
            error(404, "文件不存在")
        sub = get_sub(session, user, row.submission_id)
        if user.id != sub.student_id:
            versions = session.scalars(select(Version).where(Version.submission_id == sub.id)).all()
            if not any(ident in v.snapshot["file_ids"] for v in versions):
                error(404, "文件未进入可见提交版本")
        path = root / row.storage_key
        if not path.exists():
            error(404, "文件暂不可用，请联系维护人员")
        audit(session, user, "file.downloaded", row.id)
        session.commit()
        return FileResponse(path, filename=row.name, media_type=row.media_type,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/v1/submissions/{ident}/submit", status_code=202)
    def submit(ident: str, body: Submit, request: Request, user=Depends(authenticated), session=Depends(db)):
        sub = get_sub(session, user, ident, owner=True)
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None:
            return old
        if sub.status not in ("draft", "returned"):
            error(409, "当前状态不能提交")
        draft = sub.draft
        form = draft.get("form", {})
        task = session.get(Task, sub.task_id) if sub.task_id else None
        required = ["title", "contribution", "publication_status"] if sub.kind == "paper" else list(dict.fromkeys(['summary'] + task.requirements.get('required_fields', [])))
        if any(not isinstance(form.get(k), str) or not form[k].strip() for k in required):
            error(422, "缺少必填信息：" + "、".join(required))
        if sub.kind == "paper":
            state = form["publication_status"]
            if state not in ("submitted", "accepted", "published"):
                error(422, "论文状态无效")
            key = {"submitted": "submission_date", "accepted": "acceptance_date", "published": "publication_date"}[state]
            try:
                datetime.strptime(form.get(key, ""), "%Y-%m-%d")
            except (ValueError, TypeError):
                error(422, f"请填写有效的 {key}")
        ids = list(dict.fromkeys(draft.get("file_ids", [])))
        if not ids:
            error(422, "至少提供一份证明或报告附件")
        for fid in ids:
            row = session.get(File, fid)
            if not row or row.submission_id != sub.id or row.owner_id != user.id or row.status != "ready" or not (root / row.storage_key).exists():
                error(422, "附件不可用或无权引用")
        refs = []
        for ref_id in dict.fromkeys(draft.get("reference_ids", [])):
            ref = get_sub(session, user, ref_id, owner=True)
            if ref.kind != "paper" or not ref.current_version_id:
                error(422, "只能引用本人已提交的论文")
            version_id = ref.current_version_id
            if ref.effective_archive_id:
                version_id = session.get(Archive, ref.effective_archive_id).version_id
            version = session.get(Version, version_id)
            refs.append({"submission_id": ref.id, "version_id": version.id,
                         "recognition": "archived" if ref.effective_archive_id else "unverified",
                         "form": version.snapshot["form"]})
        task = session.get(Task, sub.task_id) if sub.task_id else None
        requirements = task.requirements if task else {"version": "paper-1", "review_policy": "manual_all"}
        from .db import Correction
        correction = session.scalar(select(Correction).where(Correction.submission_id==sub.id, Correction.status=='opened'))
        number = (session.scalar(select(func.max(Version.number)).where(Version.submission_id == sub.id)) or 0) + 1
        version = Version(id=uid(), submission_id=sub.id, number=number,
            snapshot={"review_workflow": os.getenv("REVIEW_WORKFLOW","manual"), "correction_id": correction.id if correction else None, "form": form, "file_ids": ids, "references": refs, "requirements": requirements,
                      "period": task.period if task else None, "late": bool(task and now() > task.deadline)})
        session.add(version)
        cas(session, sub, body.expected_lock_version, current_version_id=version.id, status="pending_review")
        from .jobs import enqueue_ai
        ai_job = enqueue_ai(session, sub, version, user.id, automatic=True)
        event = Outbox(id=uid(), kind="submission.version_created", aggregate_id=sub.id,
                       payload={"version_id": version.id, "ai_job_id": ai_job.id})
        session.add(event)
        audit(session, user, "version.submitted", version.id)
        return finish(session, idem, {"version_id": version.id, "number": number, "status": sub.status,
                                      "lock_version": sub.lock_version, "event_id": event.id, "ai_job_id": ai_job.id})

    @app.post("/api/v1/submissions/{ident}/decision")
    def decide(ident: str, body: Review, request: Request, user=Depends(authenticated), session=Depends(db)):
        sub = get_sub(session, user, ident)
        if not relation(session, user.id, sub.student_id) or not (user.role == "teacher" and sub.reviewer_id == user.id or user.role == "manager" and os.getenv("REVIEW_WORKFLOW") == "agent"):
            error(403, "没有本次复核权限")
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None:
            return old
        if sub.status != "pending_review" or sub.current_version_id != body.version_id:
            error(409, "该版本不再等待复核")
        if os.getenv('REVIEW_WORKFLOW', 'manual') == 'agent':
            from .db import AIJob
            latest = session.scalar(select(AIJob).where(AIJob.submission_id == sub.id,
                AIJob.version_id == sub.current_version_id).order_by(AIJob.created_at.desc(), AIJob.id.desc()).limit(1))
            from .auto_review import assess
            if not latest or assess(latest)[0] != 'exception':
                error(409, '只有 Agent 发现异常、无法判断或执行失败的任务需要机构处理')
        decision = Decision(id=uid(), version_id=body.version_id, reviewer_id=user.id,
                            outcome=body.outcome, opinion=body.opinion)
        session.add(decision)
        cas(session, sub, body.expected_lock_version, status=body.outcome)
        if body.outcome == "approved":
            session.add(Outbox(kind="review.approved", aggregate_id=sub.id,
                               payload={"version_id": body.version_id, "decision_id": decision.id}))
        audit(session, user, "review." + body.outcome, body.version_id)
        return finish(session, idem, {"id": decision.id, "status": sub.status, "lock_version": sub.lock_version})

    @app.get("/api/v1/events/{ident}")
    def event_status(ident: str, user=Depends(authenticated), session=Depends(db)):
        event = session.get(Outbox, ident)
        if not event:
            error(404, "事件不存在")
        get_sub(session, user, event.aggregate_id)
        return {"id": event.id, "kind": event.kind, "status": event.status}

    from .extensions import register
    register(app, {key: value for key, value in locals().copy().items() if key in
        ('db', 'authenticated', 'get_sub', 'error', 'audit', 'cas', 'replay', 'finish')})

    from .workspace import register as register_workspace
    register_workspace(app, {key: value for key, value in locals().copy().items() if key in
        ('db', 'authenticated', 'error', 'audit', 'replay', 'finish')})

    from .growth import register as register_growth
    register_growth(app, {key:value for key,value in locals().copy().items() if key in ('db','authenticated','error','audit','replay','finish')})

    from .review_flow import register as register_review_flow
    register_review_flow(app, db, authenticated)

    from .portraits import register as register_portraits
    register_portraits(app, db, authenticated)

    static = Path(__file__).resolve().parents[2] / "frontend"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app


app = create_app()
