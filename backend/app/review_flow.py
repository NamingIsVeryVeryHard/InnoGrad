"""Agent material review with exception-only institutional handling."""
from fastapi import Depends
from sqlalchemy import select
from .db import Submission, AIJob
from .policy import can_read
from .auto_review import assess


def material_outcome(job):
    if not job:
        return {'state':'not_started','label':'尚未启动','issues':0}
    if job.config.get('mode') not in ('agent','chat'):
        return {'state':'not_agent','label':'未执行 Agent 审核','issues':0}
    if job.status != 'succeeded':
        labels={'queued':'等待 Agent','running':'Agent 审核中','failed':'Agent 执行失败','cancelled':'已取消'}
        return {'state':job.status,'label':labels.get(job.status,job.status),'issues':0}
    from .auto_review import assess
    outcome,reason=assess(job)
    return {'state':outcome,'label':reason,'issues':sum(c.get('conclusion')!='compliant' for c in (job.result or {}).get('checks',[]))}


def register(app,db,auth):
    @app.get('/api/v1/review-queue')
    def queue(user=Depends(auth),session=Depends(db)):
        result=[]
        for sub in session.scalars(select(Submission).where(Submission.current_version_id.is_not(None)).order_by(Submission.created_at.desc())):
            if not can_read(session,user,sub): continue
            job=session.scalar(select(AIJob).where(AIJob.submission_id==sub.id,AIJob.version_id==sub.current_version_id).order_by(AIJob.created_at.desc(),AIJob.id.desc()).limit(1))
            result.append({'submission_id':sub.id,'version_id':sub.current_version_id,
                'job_id':job.id if job else None,'job_status':job.status if job else None,
                'simulation':bool(job and job.config.get('simulation')),
                'mode':job.config.get('mode') if job else None,'outcome':material_outcome(job),
                'institution_required':assess(job)[0]=='exception' if job else False,
                'error':job.error if job else None,'business_status':sub.status})
        return result
