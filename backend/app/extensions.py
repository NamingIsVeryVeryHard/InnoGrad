"""Manual workflow completion and read-only AI review endpoints."""
from datetime import datetime, timezone, timedelta
from typing import Literal
import hashlib
import json
import os
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select, update
from .db import User, Submission, Version, Archive, Correction, ExportJob, AIJob, uid, now
from .policy import relation


def register(app, ctx):
    from .main import Input, Submit
    from .agent import job_config
    db, auth, get_sub, error, audit, cas, replay, finish = (ctx[k] for k in
        ('db', 'authenticated', 'get_sub', 'error', 'audit', 'cas', 'replay', 'finish'))

    class Reassign(Submit):
        reviewer_id: str
        reason: str = Field(min_length=1, max_length=2000)

    class CorrectionInput(Submit):
        reason: str = Field(min_length=1, max_length=2000)

    class CorrectionHandle(Submit):
        outcome: Literal['approve', 'reject']
        opinion: str = Field(min_length=1, max_length=2000)

    class ExportInput(Input):
        submission_ids: list[str] = Field(min_length=1, max_length=100)

    class RunInput(Input):
        version_id: str
        review_package: dict | None = None

    @app.post('/api/v1/submissions/{ident}/reviewer')
    def reassign(ident: str, body: Reassign, request: Request, user=Depends(auth), session=Depends(db)):
        sub = get_sub(session, user, ident)
        if user.role != 'manager' or not relation(session, user.id, sub.student_id):
            error(403, '仅范围内管理教师可调整审核责任')
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        if sub.status not in ('pending_review', 'returned'):
            error(409, '仅待复核或待补正材料可调整复核人')
        teacher = session.get(User, body.reviewer_id)
        if not teacher or not teacher.enabled or teacher.role != 'teacher' or not relation(session, teacher.id, sub.student_id):
            error(422, '复核人不在有效授权范围内')
        cas(session, sub, body.expected_lock_version, reviewer_id=teacher.id)
        # Immutable audit detail, independent of mutable reviewer pointer.
        from .db import ReviewChange
        session.add(ReviewChange(submission_id=sub.id, reviewer_id=teacher.id, actor_id=user.id, reason=body.reason))
        audit(session, user, 'reviewer.reassigned', sub.id)
        return finish(session, idem, {'reviewer_id': sub.reviewer_id, 'lock_version': sub.lock_version})

    @app.post('/api/v1/submissions/{ident}/corrections', status_code=201)
    def request_correction(ident: str, body: CorrectionInput, request: Request, user=Depends(auth), session=Depends(db)):
        sub = get_sub(session, user, ident)
        if user.role not in ('student', 'teacher', 'manager'):
            error(403, '没有更正申请权限')
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        if sub.status != 'archived' or not sub.effective_archive_id:
            error(409, '仅已归档记录可申请更正')
        if session.scalar(select(Correction).where(Correction.submission_id == sub.id, Correction.status.in_(['pending','opened']))):
            error(409, '已有待处理或进行中的更正')
        cas(session, sub, body.expected_lock_version)
        row = Correction(id=uid(), submission_id=sub.id, archive_id=sub.effective_archive_id,
                         requested_by=user.id, reason=body.reason)
        session.add(row)
        audit(session, user, 'correction.requested', row.id)
        return finish(session, idem, {'id': row.id, 'status': 'pending', 'lock_version': sub.lock_version})

    @app.post('/api/v1/corrections/{ident}/handle')
    def handle_correction(ident: str, body: CorrectionHandle, request: Request, user=Depends(auth), session=Depends(db)):
        row = session.get(Correction, ident)
        if not row: error(404, '更正申请不存在')
        sub = get_sub(session, user, row.submission_id)
        if user.role != 'manager' or not relation(session, user.id, sub.student_id):
            error(403, '只有范围内管理教师可处理更正')
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        if row.status != 'pending' or sub.status != 'archived' or sub.effective_archive_id != row.archive_id:
            error(409, '更正或档案状态已变化')
        if body.outcome == 'approve':
            archived = session.get(Archive, row.archive_id)
            original = session.get(Version, archived.version_id).snapshot
            draft = {'form': original['form'], 'file_ids': original['file_ids'],
                     'reference_ids': [r['submission_id'] for r in original.get('references', [])]}
            cas(session, sub, body.expected_lock_version, status='returned', draft=draft)
            row.status = 'opened'
        else:
            cas(session, sub, body.expected_lock_version)
            row.status = 'rejected'
        row.handled_by, row.opinion = user.id, body.opinion
        audit(session, user, 'correction.' + row.status, row.id)
        return finish(session, idem, {'status': row.status, 'lock_version': sub.lock_version})

    @app.post('/api/v1/submissions/{ident}/updates')
    def paper_update(ident: str, body: CorrectionInput, request: Request, user=Depends(auth), session=Depends(db)):
        sub = get_sub(session, user, ident, owner=True)
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        if sub.kind != 'paper' or sub.status != 'archived':
            error(409, '仅已归档论文可发起正常进展更新')
        if session.scalar(select(Correction).where(Correction.submission_id == sub.id, Correction.status.in_(['pending','opened']))):
            error(409, '请先处理进行中的更正')
        original = session.get(Version, session.get(Archive, sub.effective_archive_id).version_id).snapshot
        cas(session, sub, body.expected_lock_version, status='returned',
            draft={'form': original['form'], 'file_ids': original['file_ids'], 'reference_ids': []})
        from .db import ReviewChange
        session.add(ReviewChange(submission_id=sub.id, reviewer_id=sub.reviewer_id, actor_id=user.id, reason='进展更新：'+body.reason))
        audit(session, user, 'paper.update_opened', sub.id)
        return finish(session, idem, {'status': sub.status, 'lock_version': sub.lock_version})

    @app.post('/api/v1/exports', status_code=202)
    def export(body: ExportInput, request: Request, user=Depends(auth), session=Depends(db)):
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        manifest = []
        for ident in dict.fromkeys(body.submission_ids):
            sub = get_sub(session, user, ident)
            if not sub.effective_archive_id: error(422, '仅允许导出有效归档记录')
            manifest.append({'submission_id': sub.id, 'archive_id': sub.effective_archive_id})
        row = ExportJob(id=uid(), requested_by=user.id, manifest=manifest,
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        session.add(row)
        audit(session, user, 'export.requested', row.id)
        return finish(session, idem, {'id': row.id, 'status': 'queued'})

    def export_owned(ident, user, session):
        row = session.get(ExportJob, ident)
        if not row or row.requested_by != user.id: error(404, '导出任务不存在')
        if row.expires_at <= now(): error(410, '导出已过期，请重新生成')
        # Check frozen manifest, not the current newest version.
        for item in row.manifest:
            get_sub(session, user, item['submission_id'])
        return row

    @app.get('/api/v1/exports/{ident}')
    def export_status(ident: str, user=Depends(auth), session=Depends(db)):
        row = export_owned(ident, user, session)
        return {'id': row.id, 'status': row.status, 'error': row.error, 'expires_at': row.expires_at}

    @app.get('/api/v1/exports/{ident}/download')
    def export_download(ident: str, user=Depends(auth), session=Depends(db)):
        row = export_owned(ident, user, session)
        if row.status != 'succeeded': error(409, '导出尚未就绪或已被取消')
        audit(session, user, 'export.downloaded', row.id)
        session.commit()
        return JSONResponse(row.result, headers={'Content-Disposition': f'attachment; filename="archive-{row.id}.json"', 'Cache-Control':'no-store'})

    @app.get('/api/v1/ai/capabilities')
    def ai_capabilities(user=Depends(auth)):
        try:
            config = job_config()
        except ValueError:
            return {'workflow':os.getenv('REVIEW_WORKFLOW','manual'),'mode':'configuration_error', 'model_configured':False, 'automatic_approval':os.getenv('REVIEW_WORKFLOW')=='agent', 'ocr_configured':False}
        return {'workflow':os.getenv('REVIEW_WORKFLOW','manual'),'mode': config['mode'], 'model_configured': config['mode'] in ('agent','chat','innoagent') and bool(config.get('base_url')),
                'automatic_approval': os.getenv('REVIEW_WORKFLOW')=='agent', 'ocr_configured': False}

    @app.post('/api/v1/submissions/{ident}/ai-jobs', status_code=202)
    def ai_run(ident: str, body: RunInput, request: Request, user=Depends(auth), session=Depends(db)):
        sub = get_sub(session, user, ident)
        old, idem = replay(session, request, user, body.model_dump())
        if old is not None: return old
        version = session.get(Version, body.version_id)
        if not version or version.submission_id != sub.id: error(404, '提交版本不存在')
        try:
            config = job_config()
        except ValueError:
            error(422, 'AI 服务配置不完整，请联系管理员')
        cas(session, sub, sub.lock_version)
        from .jobs import enqueue_ai
        try:
            row = enqueue_ai(session, sub, version, user.id, review_package=body.review_package)
        except ValueError as exc:
            error(422, str(exc))
        audit(session, user, 'ai.requested', row.id)
        return finish(session, idem, {'id': row.id, 'status': 'queued'})

    @app.get('/api/v1/ai-jobs/{ident}')
    def ai_status(ident: str, user=Depends(auth), session=Depends(db)):
        row = session.get(AIJob, ident)
        if not row: error(404, '初审任务不存在')
        sub = get_sub(session, user, row.submission_id)
        from .db import Decision
        used_for_archive = session.scalar(select(Decision.id).where(Decision.ai_job_id == row.id)) is not None
        current = sub.current_version_id == row.version_id and (sub.status == 'pending_review' or used_for_archive)
        from .review_flow import material_outcome
        from .auto_review import assess
        return {'institution_required':assess(row)[0]=='exception','material_review':material_outcome(row),'id':row.id, 'version_id':row.version_id, 'status':row.status, 'attempts':row.attempts,
                'mode':row.config['mode'], 'result':row.result, 'error':row.error, 'error_code':row.error_code,
                'agent_session_id':row.agent_session_id, 'skill_version':row.skill_version,
                'response_model':row.response_model, 'next_attempt_at':row.next_attempt_at,
                'historical_only':not current, 'input_hash':row.input_hash}

    @app.get('/api/v1/ai-jobs/{ident}/report')
    def ai_report(ident: str, user=Depends(auth), session=Depends(db)):
        row = session.get(AIJob, ident)
        if not row:
            error(404, '审核任务不存在')
        sub = get_sub(session, user, row.submission_id)
        snapshot = row.input_pack.get('snapshot', {})
        files = [
            {'file_id': item.get('id'), 'name': item.get('name'), 'media_type': item.get('media_type'),
             'role': item.get('role'), 'sha256': item.get('sha256')}
            for item in row.input_pack.get('files', [])
        ]
        result = row.result or {}
        return {
            'schema_version': result.get('schema_version', '1.0'),
            'job_id': row.id, 'submission_id': sub.id, 'version_id': row.version_id,
            'status': row.status, 'input_hash': row.input_hash,
            'rule_version': snapshot.get('requirements', {}).get('version'),
            'skill_version': (result.get('agent') or {}).get('skill'),
            'agent_session_id': row.agent_session_id or (result.get('agent') or {}).get('agent_session_id'),
            'response_model': row.response_model or (result.get('agent') or {}).get('response_model'),
            'files': files, 'checks': result.get('checks', []),
            'blocks': result.get('blocks', []), 'limitations': result.get('limitations', []),
            'routing': result.get('routing'),
            'error': row.error, 'error_code': row.error_code,
        }

    @app.post('/api/v1/ai-jobs/{ident}/cancel')
    def cancel_ai(ident: str, request: Request, user=Depends(auth), session=Depends(db)):
        row = session.get(AIJob, ident)
        if not row: error(404, '初审任务不存在')
        sub = get_sub(session, user, row.submission_id)
        if user.id not in (row.requested_by, sub.reviewer_id) and user.role != 'manager':
            error(403, '无取消权限')
        old, idem = replay(session, request, user, {})
        if old is not None: return old
        changed = session.execute(update(AIJob).where(AIJob.id==ident, AIJob.status.in_(['queued','running','retrying']))
            .values(status='cancelled', execution_token=None, finished_at=now()))
        if not changed.rowcount: error(409, '任务已经结束')
        audit(session, user, 'ai.cancelled', ident)
        return finish(session, idem, {'status':'cancelled'})
