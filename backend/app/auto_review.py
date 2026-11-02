"""Deterministic routing of validated material reports, fenced to the current version."""
from sqlalchemy import select, update
from .db import User, AIJob, Submission, Decision, Outbox, Audit, uid
from .agent import Check, validate_evidence
import json
from pathlib import Path


def required_rules(job):
    if job.config.get('mode') != 'innoagent':
        return set()
    kind = job.input_pack.get('snapshot', {}).get('kind')
    filename = 'paper-v1.json' if kind == 'paper' else 'annual-v1.json'
    path = Path(__file__).resolve().parents[3] / 'agent-skills' / 'material-review' / 'references' / 'rules' / filename
    try:
        return {item['id'] for item in json.loads(path.read_text(encoding='utf-8'))['rules']}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def assess(job):
    if job.config.get('mode') not in ('agent','chat','innoagent'):
        return 'unconfigured', '未执行 Agent 审核'
    if job.status in ('failed','cancelled'):
        return 'exception', 'Agent 执行失败或取消，需机构处理'
    if job.status != 'succeeded':
        return 'waiting', 'Agent 审核尚未完成'
    result=job.result or {}
    if result.get('routing',{}).get('state')=='exception':
        return 'exception',result['routing']['reason']
    checks=result.get('checks',[])
    if not checks:
        return 'exception', 'OUTPUT_INVALID:报告缺失'
    if result.get('limitations'):
        return 'exception', 'PARSE_LIMIT:存在解析限制'
    local={'ATTACHMENT_READABILITY','FORM_COMPLETENESS'}
    if len({c.get('rule_id') for c in checks}) != len(checks):
        return 'exception','OUTPUT_INVALID:报告包含重复检查项'
    if not all(any(c.get('rule_id')==key and c.get('conclusion')=='compliant' for c in checks) for key in local):
        return 'exception','RULE_INCOMPLETE:缺少完整的解析与必填检查'
    semantic=[c for c in checks if c.get('rule_id') not in local]
    expected = required_rules(job)
    actual = {c.get('rule_id') for c in semantic}
    if expected and actual != expected:
        return 'exception','RULE_INCOMPLETE:规则覆盖不完整'
    if not semantic:
        return 'exception','RULE_INCOMPLETE:没有 Agent 审核结论'
    try:
        validate_evidence([Check.model_validate(c) for c in semantic],result.get('blocks',[]))
    except (ValueError,KeyError,TypeError):
        return 'exception','EVIDENCE_INVALID:Agent 证据无法核验'
    required=set(job.input_pack['snapshot'].get('file_ids',[]))
    covered={e.get('file_id') for c in semantic if c.get('conclusion')=='compliant' for e in c.get('evidence',[])}
    if not required or not required.issubset(covered) or not covered.issubset(required):
        return 'exception','EVIDENCE_INVALID:原件证据覆盖不完整或引用了包外原件'
    if any(ref.get('recognition')!='archived' for ref in job.input_pack['snapshot'].get('references',[])):
        return 'exception','REF_UNRECOGNIZED:引用成果尚未认定'
    if job.input_pack['snapshot'].get('late'):
        return 'exception','LATE:逾期提交需机构核验'
    non_compliant = [c for c in semantic if c.get('conclusion') == 'non_compliant']
    uncertain = [c for c in semantic if c.get('conclusion') == 'unable_to_determine']
    if uncertain:
        return 'exception','FINDING_UNCERTAIN:存在无法安全判断的规则'
    if non_compliant:
        if all(c.get('suggestion') and c.get('severity') == 'blocking' for c in non_compliant):
            return 'correction','FINDING_BLOCKING:存在可明确补正的问题'
        return 'exception','FINDING_UNCERTAIN:存在无法安全路由的问题'
    if not all(c.get('conclusion') in ('compliant','not_applicable') for c in semantic):
        return 'exception','OUTPUT_INVALID:规则结论无效'
    return 'passed','Agent 材料审核通过'


def apply_auto_decision(session,job):
    if job.config.get('workflow')!='agent': return
    sub=session.get(Submission,job.submission_id)
    if not sub or sub.current_version_id!=job.version_id or sub.status!='pending_review': return
    latest=session.scalar(select(AIJob.id).where(AIJob.submission_id==sub.id,AIJob.version_id==job.version_id)
        .order_by(AIJob.created_at.desc(),AIJob.id.desc()).limit(1))
    if latest!=job.id: return
    outcome,reason=assess(job)
    job.result={**(job.result or {}),'routing':{'state':outcome,'reason':reason}}
    if outcome == 'correction':
        changed = session.execute(update(Submission).where(
            Submission.id == sub.id, Submission.lock_version == sub.lock_version,
            Submission.current_version_id == job.version_id, Submission.status == 'pending_review'
        ).values(status='returned', lock_version=Submission.lock_version + 1))
        if changed.rowcount == 1:
            job.result = {**job.result, 'routing': {'state': outcome, 'reason': reason}}
        return
    if outcome!='passed': return
    from .policy import relation
    student=session.get(User,sub.student_id)
    reviewer=session.get(User,sub.reviewer_id)
    if not student or not student.enabled or not reviewer or not reviewer.enabled or not relation(session,sub.reviewer_id,sub.student_id):
        job.result={**job.result,'routing':{'state':'exception','reason':'账号或指导授权已变化，需机构核验'}}
        return
    changed=session.execute(update(Submission).where(Submission.id==sub.id,Submission.lock_version==sub.lock_version,
        Submission.current_version_id==job.version_id,Submission.status=='pending_review')
        .values(status='approved',lock_version=Submission.lock_version+1))
    if changed.rowcount!=1: return
    agent=session.scalar(select(User).where(User.username=='__innograd_agent__'))
    if not agent:
        agent=User(id=uid(),username='__innograd_agent__',name='InnoGrad 审核 Agent',role='service',enabled=0,password_hash='disabled$disabled')
        session.add(agent);session.flush()
    if agent.role!='service' or agent.enabled: raise ValueError('Invalid Agent service identity')
    decision=Decision(id=uid(),version_id=job.version_id,reviewer_id=agent.id,outcome='approved',
        opinion='Agent 审核通过：材料检查完整，证据可追溯。报告 '+job.id,actor_type='agent',ai_job_id=job.id)
    session.add(decision);session.flush()
    session.add(Outbox(kind='review.approved',aggregate_id=sub.id,payload={'version_id':job.version_id,'decision_id':decision.id,'ai_job_id':job.id}))
    session.add(Audit(actor_id=agent.id,action='agent.review_approved',object_id=job.version_id))
