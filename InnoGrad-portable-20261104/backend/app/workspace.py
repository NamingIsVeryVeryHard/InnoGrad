"""Authenticated workspace features. No browser-owned business state."""
from typing import Literal
from datetime import datetime, timezone
import secrets
import os
from fastapi import Depends, Request
from pydantic import Field
from sqlalchemy import select, update, func
from .db import (User, StudentProfile, Supervision, RuleTemplate, StudentImport, FollowUp,
                 Task, Assignment, Audit, Submission, Version, Decision, Correction,
                 AIJob, ExportJob, ReviewChange, PortraitSnapshot, File, WorkerHeartbeat, uid, now)
from .policy import relation

DEFAULT_RULE = {'id': 'annual-1', 'title': '年度培养报告', 'content': '填写研究进展与下一阶段计划，并提交报告附件；由教师逐项复核。',
    'requirements': {'version': 'annual-1', 'required_fields': ['summary'], 'attachment_required': True, 'review_policy': 'manual_all'}, 'date': ''}


def scope_ids(session, user):
    if user.role == 'student':
        return [user.id]
    if user.role not in ('manager', 'teacher'):
        return []
    return list(session.scalars(select(Supervision.student_id).where(Supervision.teacher_id == user.id,
        Supervision.valid_from <= now(), (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now()))))


def teacher_ids(session, user):
    ids = scope_ids(session, user)
    return list(session.scalars(select(User.id).join(Supervision, Supervision.teacher_id == User.id).where(
        User.role == 'teacher', User.enabled == 1, Supervision.student_id.in_(ids), Supervision.valid_from <= now(),
        (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now())).distinct()))


def register(app, ctx):
    from .main import Input, password_hash
    db, auth, error, audit, replay, finish = (ctx[k] for k in ('db', 'authenticated', 'error', 'audit', 'replay', 'finish'))

    class StudentInput(Input):
        degree: Literal["博士","硕士","未标注"] = "未标注"
        name: str = Field(min_length=1, max_length=100)
        number: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
        year: str = Field(min_length=1, max_length=30)
        major: str = Field(min_length=1, max_length=100)
        direction: str = Field(min_length=1, max_length=200)
        teacher_id: str

    class ProfileInput(Input):
        degree: Literal["博士","硕士","未标注"] | None = None
        year: str = Field(min_length=1, max_length=30)
        major: str = Field(min_length=1, max_length=100)
        direction: str = Field(min_length=1, max_length=200)
        stage: str = Field(min_length=1, max_length=60)

    class ImportInput(Input):
        rows: list[StudentInput] = Field(min_length=1, max_length=100)

    class RuleInput(Input):
        title: str = Field(min_length=1, max_length=200)
        content: str = Field(min_length=1, max_length=10000)
        required_fields: list[Literal['title', 'summary', 'plan']] = Field(min_length=1, max_length=3)

    class ReminderInput(Input):
        student_id: str
        task_id: str | None = None
        title: str = Field(min_length=1, max_length=200)
        text: str = Field(min_length=1, max_length=4000)

    class FollowInput(Input):
        note: str = Field(min_length=1, max_length=4000)
        status: Literal['open', 'done']
        expected_lock_version: int = Field(ge=0)

    def manager(user):
        if user.role != 'manager': error(403, '仅管理教师可执行此操作')

    def validate_student(session, user, row):
        if row['number'].startswith('__'): error(422,'此账号前缀保留给系统服务')
        if row['teacher_id'] not in teacher_ids(session, user): error(403, '导师不在当前管理范围内')
        if session.scalar(select(User.id).where(User.username == row['number'])) or session.scalar(select(StudentProfile.user_id).where(StudentProfile.number == row['number'])):
            error(409, '学号或账号已存在，请核对后重新导入')

    def add_student(session, user, row):
        validate_student(session, user, row)
        password = secrets.token_urlsafe(16)
        student = User(id=uid(), name=row['name'], username=row['number'], role='student', password_hash=password_hash(password))
        session.add(student)
        session.flush()
        session.add(StudentProfile(user_id=student.id, degree=row.get('degree','未标注'), **{k: row[k] for k in ('number','year','major','direction')}))
        for teacher in (user.id, row['teacher_id']):
            session.add(Supervision(student_id=student.id, teacher_id=teacher, valid_from=now()))
        audit(session, user, 'student.created', student.id)
        return {'id': student.id, 'username': student.username, 'initial_password': password, 'name': student.name}

    @app.get('/api/v1/students')
    def students(user=Depends(auth), session=Depends(db)):
        rows = session.execute(select(User, StudentProfile).outerjoin(StudentProfile, StudentProfile.user_id == User.id)
            .where(User.id.in_(scope_ids(session, user)), User.role == 'student').order_by(User.name)).all()
        output = []
        for u, p in rows:
            teachers = session.scalars(select(User).join(Supervision, Supervision.teacher_id == User.id).where(
                Supervision.student_id == u.id, User.role == 'teacher', Supervision.valid_from <= now(),
                (Supervision.valid_to.is_(None)) | (Supervision.valid_to > now()))).all()
            output.append(dict(id=u.id, name=u.name, number=p.number if p else u.username, year=p.year if p else '待补录',
                degree=p.degree if p else '未标注', major=p.major if p else '待补录', direction=p.direction if p else '待补录', stage=p.stage if p else '待补录',
                teachers=[dict(id=t.id, name=t.name) for t in teachers]))
        return output

    @app.patch('/api/v1/students/{ident}/profile')
    def edit_profile(ident: str, body: ProfileInput, user=Depends(auth), session=Depends(db)):
        manager(user)
        if ident not in scope_ids(session, user): error(404, '学生不存在或无权访问')
        student = session.get(User, ident)
        if not student or student.role != 'student': error(404, '学生不存在')
        row = session.get(StudentProfile, ident)
        if not row:
            row = StudentProfile(user_id=ident, number=student.username, **body.model_dump(exclude_none=True))
            session.add(row)
        else:
            for key,value in body.model_dump(exclude_none=True).items(): setattr(row,key,value)
        audit(session,user,'student.profile_updated',ident)
        session.commit()
        return {'ok': True}

    @app.post('/api/v1/students', status_code=201)
    def create_student(body: StudentInput, request: Request, user=Depends(auth), session=Depends(db)):
        manager(user)
        # Do not persist plaintext initial credentials in the idempotency table.
        row = add_student(session, user, body.model_dump())
        session.commit()
        return row

    @app.post('/api/v1/student-imports', status_code=201)
    def preview_import(body: ImportInput, user=Depends(auth), session=Depends(db)):
        manager(user)
        rows = [r.model_dump() for r in body.rows]
        seen, checks = set(), []
        for row in rows:
            problem = ''
            try: validate_student(session, user, row)
            except Exception as exc:
                from fastapi import HTTPException
                if not isinstance(exc, HTTPException): raise
                problem = exc.detail
            if row['number'] in seen: problem = '本批学号重复'
            seen.add(row['number'])
            checks.append({'row': row, 'error': problem})
        batch = StudentImport(id=uid(), created_by=user.id, rows=rows)
        session.add(batch)
        audit(session, user, 'student_import.previewed', batch.id)
        session.commit()
        return {'id': batch.id, 'checks': checks, 'valid': not any(c['error'] for c in checks)}

    @app.post('/api/v1/student-imports/{ident}/commit')
    def commit_import(ident: str, user=Depends(auth), session=Depends(db)):
        manager(user)
        batch = session.get(StudentImport, ident)
        if not batch or batch.created_by != user.id: error(404, '导入批次不存在')
        changed = session.execute(update(StudentImport).where(StudentImport.id == ident, StudentImport.status == 'preview').values(status='committed'))
        if not changed.rowcount: error(409, '该批次已导入，不可重复提交')
        credentials = []
        for row in batch.rows:
            credentials.append(add_student(session, user, row))
            session.flush()
        audit(session, user, 'student_import.committed', ident)
        session.commit()
        return {'created': credentials}

    @app.get('/api/v1/rules')
    def rules(user=Depends(auth), session=Depends(db)):
        rows = session.scalars(select(RuleTemplate).where(RuleTemplate.created_by == user.id).order_by(RuleTemplate.created_at)).all() if user.role == 'manager' else []
        return [DEFAULT_RULE] + [dict(id=r.id, title=r.title, content=r.content, requirements=r.requirements, date=r.created_at) for r in rows]

    @app.post('/api/v1/rules', status_code=201)
    def publish_rule(body: RuleInput, request: Request, user=Depends(auth), session=Depends(db)):
        manager(user)
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        ident = uid()
        required = list(dict.fromkeys(['summary'] + body.required_fields))
        from .material_rules import freeze_requirements
        row = RuleTemplate(id=ident, title=body.title, content=body.content, created_by=user.id,
            requirements=freeze_requirements("annual", {'version':ident, 'required_fields':required, 'attachment_required':True, 'review_policy':'manual_all', 'instructions':body.content}))
        session.add(row)
        audit(session, user, 'rule.published', ident)
        return finish(session, idem, {'id': ident})

    @app.get('/api/v1/alerts')
    def alerts(user=Depends(auth), session=Depends(db)):
        rows = session.scalars(select(FollowUp).where(FollowUp.student_id.in_(scope_ids(session, user))).order_by(FollowUp.updated_at.desc())).all()
        return [dict(id=r.id, student=r.student_id, task=r.task_id, title=r.title, text=r.text, note=r.note, status=r.status,
                     lock_version=r.lock_version, updated_at=r.updated_at) for r in rows]

    @app.post('/api/v1/alerts', status_code=201)
    def remind(body: ReminderInput, request: Request, user=Depends(auth), session=Depends(db)):
        if user.role not in ('teacher','manager') or body.student_id not in scope_ids(session, user): error(403, '无权为此学生创建提醒')
        if body.task_id:
            t = session.get(Task, body.task_id)
            if not t or user.id not in (t.reviewer_id, t.created_by) or not session.scalar(select(Assignment).where(Assignment.task_id==t.id, Assignment.student_id==body.student_id)):
                error(404, '任务或学生分配不存在')
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        if body.task_id and session.scalar(select(FollowUp).where(FollowUp.task_id==body.task_id, FollowUp.student_id==body.student_id, FollowUp.status=='open')):
            error(409, '此任务已有待处理提醒')
        row = FollowUp(id=uid(), created_by=user.id, **body.model_dump())
        session.add(row)
        audit(session, user, 'reminder.created', row.id)
        return finish(session, idem, {'id': row.id})

    @app.patch('/api/v1/alerts/{ident}')
    def follow(ident: str, body: FollowInput, user=Depends(auth), session=Depends(db)):
        row = session.get(FollowUp, ident)
        if not row or row.student_id not in scope_ids(session, user): error(404, '提醒不存在')
        changed = session.execute(update(FollowUp).where(FollowUp.id==ident, FollowUp.lock_version==body.expected_lock_version)
            .values(note=body.note, status=body.status, lock_version=body.expected_lock_version+1, updated_at=now()))
        if not changed.rowcount: error(409, '跟进记录已变化，请刷新后重试')
        audit(session, user, 'reminder.updated', row.id)
        session.commit()
        return {'ok':True}

    @app.get('/api/v1/audit-logs')
    def audit_logs(user=Depends(auth), session=Depends(db)):
        # Scope by business object, not by actor: a teacher may act in several scopes.
        ids = set(scope_ids(session, user)) | {user.id}
        sub_ids = list(session.scalars(select(Submission.id).where(Submission.student_id.in_(scope_ids(session,user)), Submission.current_version_id.is_not(None))))
        if user.role == 'student': sub_ids = list(session.scalars(select(Submission.id).where(Submission.student_id==user.id)))
        ids.update(sub_ids)
        versions = list(session.scalars(select(Version.id).where(Version.submission_id.in_(sub_ids))))
        ids.update(versions)
        for model in (Correction, AIJob):
            ids.update(session.scalars(select(model.id).where(model.submission_id.in_(sub_ids))))
        ids.update(session.scalars(select(Decision.id).where(Decision.version_id.in_(versions))))
        ids.update(session.scalars(select(FollowUp.id).where(FollowUp.student_id.in_(scope_ids(session,user)))))
        from .db import GrowthEntry, WarningAction
        for model in (GrowthEntry, WarningAction):
            ids.update(session.scalars(select(model.id).where(model.student_id.in_(scope_ids(session,user)))))
        # Files are only exposed after submission; draft upload auditing is owner-only.
        files = session.scalars(select(File).where(File.submission_id.in_(sub_ids))).all()
        visible_files = set()
        for v in session.scalars(select(Version).where(Version.id.in_(versions))): visible_files.update(v.snapshot.get('file_ids',[]))
        ids.update(f.id for f in files if f.owner_id==user.id or f.id in visible_files)
        logs = session.execute(select(Audit, User.name).join(User, User.id==Audit.actor_id).where(
            (Audit.actor_id==user.id) | Audit.object_id.in_(ids)).order_by(Audit.created_at.desc()).limit(1000)).all()
        return [dict(time=r.created_at, actor=name, action=r.action, object_id=r.object_id) for r,name in logs]

    @app.get('/api/v1/workspace/status')
    def status(user=Depends(auth), session=Depends(db)):
        pulse = session.get(WorkerHeartbeat, 'main')
        active = bool(pulse and (datetime.now(timezone.utc)-datetime.fromisoformat(pulse.last_seen)).total_seconds()<30)
        return {'worker_online':active, 'worker_last_seen':pulse.last_seen if pulse else None,
                'storage':'server', 'max_upload_mb':50, 'automatic_approval':os.getenv('REVIEW_WORKFLOW')=='agent', 'version':'0.3.0'}
