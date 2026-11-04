"""Agent material review with exception-only institutional handling."""
from fastapi import Depends
from sqlalchemy import select
from .db import Submission, AIJob, Decision
from .policy import can_read
from .auto_review import assess


def _reason_label(reason):
    labels = {
        "RULE_INCOMPLETE": "本次审核规则暂不可用，请联系管理员处理",
        "EVIDENCE_INVALID": "审核报告与原件未能对应，请重新审核",
        "PARSE_LIMIT": "材料未完整读取，请学生补充清晰原件",
        "FINDING_BLOCKING": "请学生补充材料后重新提交",
        "FINDING_UNCERTAIN": "有一项内容需要机构核验",
        "CONFIG_ERROR": "审核服务暂时不可用，请联系管理员处理",
        "TRANSIENT_TIMEOUT": "审核服务响应超时，请重新审核",
        "TRANSIENT_SERVICE": "审核服务暂时中断，请重新审核",
        "AGENT_BUSY": "审核任务较多，排队已超时，请重新审核",
        "CLEANUP_FAILED": "本次审核未正常结束，请联系管理员处理",
        "OUTPUT_INVALID": "未获得完整的审核报告，请重新审核",
        "INTERACTION_REQUIRED": "本次审核需要额外信息，请联系管理员处理",
        "AGENT_ABORTED": "本次审核已中止，可以重新审核",
        "LATE": "已记录逾期提交时间",
        "REF_UNRECOGNIZED": "引用成果尚未完成认定，本次仅作提示",
        "AUTH_CHANGED": "提交版本或授权范围发生变化，需要机构核验",
    }
    return labels.get(str(reason or "").split(":", 1)[0], "本次审核未能完成，请重新审核或联系管理员处理")


def material_outcome(job):
    if not job:
        return {'state':'not_started','label':'尚未启动','issues':0}
    if job.config.get('mode') not in ('agent','chat','innoagent') and not (
        job.config.get('mode') == 'disabled' and job.config.get('workflow') == 'agent'
    ):
        return {'state':'not_agent','label':'未执行 Agent 审核','issues':0}
    if job.status != 'succeeded':
        state = job.status
        if state == 'running' and (job.agent_metadata or {}).get('progress', {}).get('state') == 'queued':
            state = 'queued'
        labels={'queued':'排队中','running':'审核中','retrying':'等待重试','failed':'审核异常','cancelled':'已取消'}
        return {'state':state,'label':labels.get(state,'等待审核'),
                'reason':_reason_label(job.error_code) if state == 'failed' else '', 'issues':0}
    from .auto_review import assess
    outcome,reason=assess(job)
    labels = {
        'passed': '审核通过',
        'correction': '待学生补正',
        'exception': _reason_label(reason),
        'waiting': '等待审核完成',
        'unconfigured': '尚未执行审核',
    }
    return {'state':outcome,'label':labels.get(outcome, _reason_label(reason)),
            'reason':_reason_label(reason) if outcome=='exception' else '',
            'issues':sum(c.get('conclusion') in ('non_compliant', 'unable_to_determine')
                         for c in (job.result or {}).get('checks',[]))}


def review_context(session, job, sub):
    """Display context; historical reports never create a current institution task."""
    latest = session.scalar(select(AIJob.id).where(
        AIJob.submission_id == sub.id, AIJob.version_id == sub.current_version_id,
    ).order_by(AIJob.created_at.desc(), AIJob.id.desc()).limit(1))
    used = session.scalar(select(Decision.id).where(Decision.ai_job_id == job.id)) is not None
    historical = sub.current_version_id != job.version_id or (
        not used and (sub.status != 'pending_review' or latest != job.id)
    )
    result = job.result or {}
    rules = job.input_pack.get('snapshot', {}).get('requirements', {}).get('review_rules', [])
    return {
        'material_review': material_outcome(job),
        'institution_required': not historical and sub.status == 'pending_review' and assess(job)[0] == 'exception',
        'business_status': sub.status,
        'historical_only': historical,
        'semantic_reviewed': bool(job.status == 'succeeded' and not result.get('simulation')
                                  and (result.get('agent') or {}).get('agent_session_id')),
        'simulation': bool(result.get('simulation') or job.config.get('simulation')),
        'rule_policies': {rule['id']: {'level': rule.get('level', 'blocking'),
                                     'on_uncertain': rule.get('on_uncertain', 'correction')} for rule in rules},
    }


def register(app,db,auth):
    @app.get('/api/v1/review-queue')
    def queue(user=Depends(auth),session=Depends(db)):
        result=[]
        for sub in session.scalars(select(Submission).where(Submission.current_version_id.is_not(None)).order_by(Submission.created_at.desc())):
            if not can_read(session,user,sub): continue
            job=session.scalar(select(AIJob).where(AIJob.submission_id==sub.id,AIJob.version_id==sub.current_version_id).order_by(AIJob.created_at.desc(),AIJob.id.desc()).limit(1))
            context = review_context(session, job, sub) if job else {}
            result.append({'submission_id':sub.id,'version_id':sub.current_version_id,
                'job_id':job.id if job else None,'job_status':job.status if job else None,
                'simulation':bool(job and job.config.get('simulation')),
                'mode':job.config.get('mode') if job else None,'outcome':material_outcome(job),
                'institution_required':context.get('institution_required', False),
                'error':job.error if job else None,'business_status':sub.status})
        return result
