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


def enqueue_ai(session, sub, version, actor_id, automatic=False):
    files=[]
    for fid in version.snapshot['file_ids']:
        f=session.get(File,fid)
        frozen = next((item for item in version.snapshot.get("files", []) if item["id"] == fid), None)
        files.append({**(frozen or {'id':f.id,'name':f.name,'sha256':f.sha256,'media_type':f.media_type,
                      'role': version.snapshot.get('file_roles', {}).get(f.id, 'other')}),
                      'storage_key': f.storage_key})
    pack={'version_id':version.id,'snapshot':version.snapshot,'files':files}
    pack['input_hash']=hashlib.sha256(json.dumps(pack,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    error=None
    try:
        config=job_config()
    except ValueError:
        if not automatic: raise
        config={'mode':'disabled','workflow':os.getenv('REVIEW_WORKFLOW','manual')};error='Agent 服务待配置或配置无效；材料已保存，配置完成后可重新启动审核'
    job=AIJob(id=uid(),submission_id=sub.id,version_id=version.id,requested_by=actor_id,input_pack=pack,
        input_hash=pack['input_hash'],
        config=config,status='failed' if error else 'queued',error=error)
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
    """One attempt outside DB transaction. Expired leases recover, fenced writes reject late workers."""
    root=root or os.getenv('FILE_ROOT','runtime/files')
    processor=processor or analyze
    with factory.begin() as session:
        candidate=or_(AIJob.status.in_(['queued','retrying']),and_(AIJob.status=='running',AIJob.lease_until<now()))
        job=session.scalar(select(AIJob).where(candidate,AIJob.attempts<3).order_by(AIJob.created_at).limit(1))
        if not job:
            session.execute(update(AIJob).where(AIJob.status=='running',AIJob.lease_until<now(),AIJob.attempts>=3)
                .values(status='failed',error='执行中断超过恢复上限，需人工处理',execution_token=None,finished_at=now()))
            return False
        token=secrets.token_hex(24)
        result=session.execute(update(AIJob).where(AIJob.id==job.id,candidate,AIJob.attempts<3).values(
            status='running',execution_token=token,attempts=AIJob.attempts+1,
            lease_until=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()))
        if result.rowcount!=1: return False
        ident,pack,config=job.id,job.input_pack,job.config
    try:
        result=processor(pack,config,root)
        # Validate processor result even if adapter implementations are replaced later.
        from .agent import Check
        if result.get('automatic_approval') is not False: raise ValueError('Invalid approval field')
        for check in result['checks']: Check.model_validate(check)
        values={'status':'succeeded','result':result,'error':None}
    except Exception as exc:
        # No raw provider exceptions: they can include credentials, endpoints or submitted content.
        transient = isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)) or (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
        )
        retry = transient and (job.attempts + 1) < 3
        values={'status':'retrying' if retry else 'failed','result':None,
                'error_code':'TRANSIENT_TIMEOUT' if isinstance(exc, httpx.TimeoutException) else 'TRANSIENT_SERVICE' if transient else 'OUTPUT_INVALID',
                'error':'初审服务暂时不可用，任务将自动重试' if retry else '初审执行或输出校验失败，请由机构复核'}
    else:
        metadata = result.get('agent') or {}
        values={'status':'succeeded','result':result,'error':None,'error_code':None,
                'agent_session_id':metadata.get('agent_session_id'),
                'skill_version':metadata.get('skill') or metadata.get('rule_version'),
                'response_model':metadata.get('response_model')}
    with factory.begin() as session:
        completed=session.execute(update(AIJob).where(AIJob.id==ident,AIJob.status=='running',AIJob.execution_token==token)
            .values(**values,finished_at=now(),execution_token=None,lease_until=None))
        if completed.rowcount == 1:
            from .auto_review import apply_auto_decision
            completed_job=session.get(AIJob,ident)
            session.refresh(completed_job)
            apply_auto_decision(session,completed_job)
    # Job completion, automatic decision, and outbox are committed together.
    return True
