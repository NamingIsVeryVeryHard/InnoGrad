from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import os
import secrets
import httpx
from sqlalchemy import select, update, or_, and_
from .db import AIJob, File, ExportJob, User, Submission, Archive, Version, Audit, now, uid
from .policy import can_read
from .agent import job_config, analyze


def enqueue_ai(session, sub, version, actor_id, automatic=False, review_package=None):
    files=[]
    for fid in version.snapshot['file_ids']:
        f=session.get(File,fid)
        frozen = next((item for item in version.snapshot.get("files", []) if item["id"] == fid), None)
        files.append({**(frozen or {'id':f.id,'name':f.name,'sha256':f.sha256,'media_type':f.media_type,
                      'role': version.snapshot.get('file_roles', {}).get(f.id, 'other')}),
                      'storage_key': f.storage_key})
    pack={'version_id':version.id,'snapshot':version.snapshot,'files':files}
    if review_package is not None:
        from .agent import ReviewPackage
        normalized = ReviewPackage.model_validate(review_package).model_dump()
        if normalized['version_id'] != version.id or normalized['kind'] != version.snapshot['kind']:
            raise ValueError('审核包版本或类型与提交版本不一致')
        for key, default in (
            ('student', {}), ('form', {}), ('references', []),
            ('requirements', {}), ('period', None), ('late', False),
        ):
            if normalized[key] != version.snapshot.get(key, default):
                raise ValueError('审核包字段与冻结版本不一致：' + key)
        attachments = normalized['attachments']
        supplied_ids = [item['file_id'] for item in attachments]
        if len(set(supplied_ids)) != len(supplied_ids) or set(supplied_ids) != {item['id'] for item in files}:
            raise ValueError('审核包附件与冻结版本不一致')
        by_id = {item['id']: item for item in files}
        for attachment in attachments:
            frozen = by_id[attachment['file_id']]
            if any(attachment[key] != frozen.get(key, 0 if key == 'size' else None)
                   for key in ('name', 'role', 'media_type', 'size', 'sha256')):
                raise ValueError('审核包附件元数据与冻结版本不一致')
        pack['review_package'] = normalized
    hash_input = {
        'version_id': pack['version_id'],
        'snapshot': pack['snapshot'],
        'files': [{key: value for key, value in item.items() if key != 'storage_key'} for item in pack['files']],
        'review_package': pack.get('review_package'),
    }
    pack['input_hash']=hashlib.sha256(json.dumps(hash_input,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    error=None
    try:
        config=job_config()
    except ValueError:
        if not automatic: raise
        config={'mode':'disabled','workflow':os.getenv('REVIEW_WORKFLOW','manual')};error='Agent 服务待配置或配置无效；材料已保存，配置完成后可重新启动审核'
    job=AIJob(id=uid(),submission_id=sub.id,version_id=version.id,requested_by=actor_id,input_pack=pack,
        input_hash=pack['input_hash'],
        config=config,status='failed' if error else 'queued',error=error,
        error_code='CONFIG_ERROR' if error else None, max_attempts=config.get('max_attempts', 3),
        finished_at=now() if error else None)
    session.add(job)
    return job


def process_exports(factory, limit=20):
    count=0
    for _ in range(limit):
        with factory.begin() as session:
            row=session.scalar(select(ExportJob).where(ExportJob.status=='queued').order_by(ExportJob.created_at).limit(1))
            if not row: break
            claimed=session.execute(update(ExportJob).where(ExportJob.id==row.id,ExportJob.status=='queued').values(status='running'))
            if claimed.rowcount!=1: continue
            user=session.get(User,row.requested_by)
            records=[];valid=row.expires_at>now()
            for item in row.manifest:
                sub=session.get(Submission,item['submission_id'])
                if not can_read(session,user,sub): valid=False;break
                archive=session.get(Archive,item['archive_id'])
                version=session.get(Version,archive.version_id) if archive else None
                if not version or version.submission_id!=sub.id: valid=False;break
                files=[]
                for fid in version.snapshot['file_ids']:
                    file=session.get(File,fid)
                    files.append({'file_id':file.id,'name':file.name,'sha256':file.sha256,'size':file.size})
                records.append({'submission_id':sub.id,'archive_id':archive.id,'version_id':version.id,
                    'version_number':version.number,'snapshot':version.snapshot,'files':files})
            row.status='succeeded' if valid else 'cancelled'
            row.result={'schema_version':'1.0','generated_at':now(),'records':records} if valid else None
            row.error=None if valid else '权限已变化或任务过期，请重新申请'
            count+=1
    return count


def run_ai(factory, root=None, processor=None):
    """Execute one due attempt outside a transaction, then apply fenced business routing."""
    from .auto_review import apply_auto_decision
    from .review_errors import ReviewFailure
    root = root or os.getenv('FILE_ROOT', 'runtime/files')
    processor = processor or analyze
    with factory.begin() as session:
        exhausted = session.scalars(select(AIJob).where(
            AIJob.status == 'running', AIJob.lease_until < now(), AIJob.attempts >= AIJob.max_attempts)).all()
        for expired in exhausted:
            expired.status, expired.error_code = 'failed', 'TRANSIENT_SERVICE'
            expired.error, expired.finished_at = '执行中断达到恢复上限', now()
            expired.execution_token, expired.lease_until = None, None
            apply_auto_decision(session, expired)
        due_retry = and_(AIJob.status == 'retrying', or_(AIJob.next_attempt_at.is_(None), AIJob.next_attempt_at <= now()))
        candidate = or_(AIJob.status == 'queued', due_retry,
                        and_(AIJob.status == 'running', AIJob.lease_until < now()))
        job = session.scalar(select(AIJob).where(candidate, AIJob.attempts < AIJob.max_attempts)
                             .order_by(AIJob.created_at, AIJob.id).limit(1))
        if not job:
            return False
        sub = session.get(Submission, job.submission_id)
        if not can_read(session, session.get(User, job.requested_by), sub):
            job.status, job.error_code, job.error = 'failed', 'AUTH_CHANGED', '任务授权已变化'
            job.finished_at = now()
            apply_auto_decision(session, job)
            return True
        token = secrets.token_hex(24)
        attempt = job.attempts + 1
        lease_seconds = max(600, (job.config.get('timeout_seconds') or 60) * 5 + 30)
        changed = session.execute(update(AIJob).where(AIJob.id == job.id, candidate,
            AIJob.attempts < AIJob.max_attempts).values(status='running', execution_token=token,
            attempts=attempt, next_attempt_at=None,
            lease_until=(datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()))
        if changed.rowcount != 1:
            return False
        ident, pack, config, maximum = job.id, job.input_pack, job.config, job.max_attempts
    metadata = {}
    from .agent_contracts import AgentExecution

    def save_progress(progress):
        with factory.begin() as session:
            session.execute(update(AIJob).where(
                AIJob.id == ident, AIJob.status == 'running', AIJob.execution_token == token,
            ).values(agent_metadata={'progress': {
                'state': progress.state, 'attempt': progress.attempt,
                'queue_wait_seconds': progress.queue_wait_seconds,
            }}))

    last_cancel_check, cancelled = 0, False

    def is_cancelled():
        import time
        nonlocal last_cancel_check, cancelled
        if cancelled or time.monotonic() - last_cancel_check < 1:
            return cancelled
        last_cancel_check = time.monotonic()
        with factory() as session:
            row = session.get(AIJob, ident)
            cancelled = not row or row.status != 'running' or row.execution_token != token
        return cancelled

    try:
        execution = AgentExecution(on_progress=save_progress, is_cancelled=is_cancelled)
        result = processor(pack, config, root, execution=execution) if processor is analyze else processor(pack, config, root)
        from .agent import Check
        if result.get('automatic_approval') is not False:
            raise ReviewFailure('OUTPUT_INVALID')
        for check in result['checks']:
            Check.model_validate(check)
        metadata = result.get('agent') or {}
        values = dict(status='succeeded', result=result, error=None, error_code=None, next_attempt_at=None)
    except Exception as exc:
        metadata = getattr(exc, 'metadata', {})
        transient = getattr(exc, 'transient', False) or isinstance(exc, httpx.TransportError) or (
            isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code in (408, 409, 429) or exc.response.status_code >= 500))
        code = exc.code if isinstance(exc, ReviewFailure) else 'TRANSIENT_TIMEOUT' if isinstance(exc, httpx.TimeoutException) else 'TRANSIENT_SERVICE' if transient else 'OUTPUT_INVALID'
        retry = transient and attempt < maximum and metadata.get('cleanup_status') != 'failed'
        delay = config.get('retry_seconds', 10) * 2 ** (attempt - 1)
        values = dict(status='retrying' if retry else 'failed', result=None, error_code=code,
            error='审核服务暂时不可用，将自动重试' if retry else '审核执行失败，详情见原因码',
            next_attempt_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat() if retry else None)
    values.update(agent_metadata=metadata, agent_session_id=metadata.get('agent_session_id'),
        skill_version=metadata.get('skill_version'), response_model=metadata.get('response_model'))
    with factory.begin() as session:
        completed = session.execute(update(AIJob).where(AIJob.id == ident, AIJob.status == 'running',
            AIJob.execution_token == token).values(**values, finished_at=None if values['status'] == 'retrying' else now(),
            execution_token=None, lease_until=None))
        if completed.rowcount == 1:
            completed_job = session.get(AIJob, ident)
            session.refresh(completed_job)
            apply_auto_decision(session, completed_job)
        else:
            session.execute(update(AIJob).where(
                AIJob.id == ident, AIJob.status == 'cancelled', AIJob.attempts == attempt,
            ).values(agent_metadata=metadata))
    return True
