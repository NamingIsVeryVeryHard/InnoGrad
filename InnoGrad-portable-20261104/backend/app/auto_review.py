"""Deterministic routing of validated material reports, fenced to the current version."""
from sqlalchemy import select, update
from .db import User, AIJob, Submission, Decision, Outbox, Audit, uid
from .agent import Check, validate_evidence
from .material_rules import requires_correction, validate_rule_checks

LOCAL_IDS = {"ATTACHMENT_READABILITY", "FORM_COMPLETENESS", "ATTACHMENT_ROLES"}


def required_rules(job):
    return {r["id"] for r in job.input_pack["snapshot"].get("requirements", {}).get("review_rules", [])}


def _feedback(check):
    if check.suggestion.strip():
        return check.suggestion.strip()
    if check.conclusion == "unable_to_determine" and check.limitations:
        return "请补充或更正：" + "；".join(check.limitations)
    return check.explanation.strip()


def material_findings(job):
    """Split findings into student corrections and non-blocking hints by each frozen rule's level."""
    snapshot = job.input_pack["snapshot"]
    rules = {r["id"]: r for r in snapshot.get("requirements", {}).get("review_rules", [])}
    corrections, hints = [], []
    for check in (Check.model_validate(c) for c in (job.result or {}).get("checks", [])):
        if check.conclusion not in ("non_compliant", "unable_to_determine"):
            continue
        blocking = check.rule_id in LOCAL_IDS or requires_correction(rules.get(check.rule_id, {}), check.conclusion)
        (corrections if blocking else hints).append(f"{check.rule_id}：{_feedback(check)}")
    if any(ref.get("recognition") != "archived" for ref in snapshot.get("references", [])):
        hints.append("REF_UNRECOGNIZED：引用成果仍由成果认定流程确认，本次通过不代表成果已认定")
    if snapshot.get("late"):
        hints.append("LATE：逾期提交，已记录提交时间")
    return corrections, hints


def assess_material(job):
    if job.status in ("failed", "cancelled"):
        return "exception", (job.error_code or "OUTPUT_INVALID") + ":审核未成功执行"
    if job.status != "succeeded":
        return "waiting", "等待审核执行"
    result = job.result or {}
    if not required_rules(job):
        return "exception", "RULE_INCOMPLETE:提交版本没有冻结规则"
    if result.get("routing", {}).get("reason", "").startswith("AUTH_CHANGED"):
        return "exception", result["routing"]["reason"]
    checks = result.get("checks", [])
    try:
        parsed = [Check.model_validate(c) for c in checks]
    except ValueError:
        return "exception", "OUTPUT_INVALID:审核格式无效"
    if len({c.rule_id for c in parsed}) != len(parsed):
        return "exception", "RULE_INCOMPLETE:重复检查"
    local = {c.rule_id: c for c in parsed if c.rule_id in LOCAL_IDS}
    if set(local) != LOCAL_IDS:
        return "exception", "RULE_INCOMPLETE:缺少确定性检查"
    if result.get("limitations") or local["ATTACHMENT_READABILITY"].conclusion != "compliant":
        return "correction", "PARSE_LIMIT:请重新上传可读取的原件"
    if any(local[key].conclusion == "non_compliant" for key in ("FORM_COMPLETENESS", "ATTACHMENT_ROLES")):
        return "correction", "FINDING_BLOCKING:请补齐表单或必需附件"
    semantic = [c for c in parsed if c.rule_id not in LOCAL_IDS]
    try:
        validate_rule_checks(semantic, job.input_pack["snapshot"], job.input_pack["files"])
        validate_evidence(semantic, result.get("blocks", []))
    except (ValueError, KeyError, TypeError) as exc:
        code = str(exc) if str(exc) in ("RULE_INCOMPLETE", "EVIDENCE_INVALID") else "EVIDENCE_INVALID"
        return "exception", code + ":规则或证据无法核验"
    agent = result.get("agent") or {}
    if not agent.get("agent_session_id") or agent.get("cleanup_status") != "deleted":
        return "exception", "CONFIG_ERROR:Agent 会话或清理状态无法确认"
    # Material content never routes to institution review: blocking findings go back to the
    # student, everything else (advisory rules, uncertainty, caveats) is attached as hints.
    corrections, hints = material_findings(job)
    if corrections:
        return "correction", "FINDING_BLOCKING:存在需学生补正的阻断项"
    if hints:
        return "passed", f"阻断项全部通过；另有 {len(hints)} 条提示"
    return "passed", "全部规则与证据检查通过"


def assess(job):
    if job.config.get('mode') == 'disabled' and job.config.get('workflow') == 'agent':
        return 'exception', 'CONFIG_ERROR:审核服务未就绪'
    if job.config.get('mode') == 'innoagent':
        return assess_material(job)
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
    local={'ATTACHMENT_READABILITY','FORM_COMPLETENESS'}
    if len({c.get('rule_id') for c in checks}) != len(checks):
        return 'exception','OUTPUT_INVALID:报告包含重复检查项'
    if not all(any(c.get('rule_id')==key and c.get('conclusion')=='compliant' for c in checks) for key in local):
        return 'exception','RULE_INCOMPLETE:缺少完整的解析与必填检查'
    if result.get('limitations'):
        return 'correction', 'PARSE_LIMIT:请重新上传可读取的原件'
    semantic=[c for c in checks if c.get('rule_id') not in local]
    expected = required_rules(job) if job.config.get('mode') == 'innoagent' else set()
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
    if outcome not in ('passed', 'correction'): return
    from .policy import relation
    student=session.get(User,sub.student_id)
    reviewer=session.get(User,sub.reviewer_id)
    if not student or not student.enabled or not reviewer or not reviewer.enabled or not relation(session,sub.reviewer_id,sub.student_id):
        job.result={**job.result,'routing':{'state':'exception','reason':'AUTH_CHANGED:账号或指导授权已变化'}}
        return
    target = 'approved' if outcome == 'passed' else 'returned'
    changed=session.execute(update(Submission).where(Submission.id==sub.id,Submission.lock_version==sub.lock_version,
        Submission.current_version_id==job.version_id,Submission.status=='pending_review')
        .values(status=target,lock_version=Submission.lock_version+1))
    if changed.rowcount!=1:
        job.result={**job.result,'routing':{'state':'exception','reason':'AUTH_CHANGED:版本或提交状态已变化'}}
        return
    agent=session.scalar(select(User).where(User.username=='__innograd_agent__'))
    if not agent:
        agent=User(id=uid(),username='__innograd_agent__',name='InnoGrad 审核 Agent',role='service',enabled=0,password_hash='disabled$disabled')
        session.add(agent);session.flush()
    if agent.role!='service' or agent.enabled: raise ValueError('Invalid Agent service identity')
    if job.config.get('mode') == 'innoagent':
        corrections, hints = material_findings(job)
        parts = (['需补正：' + '；'.join(corrections)] if target == 'returned' and corrections else []) \
            + (['提示：' + '；'.join(hints)] if hints else [])
        suggestions = '；'.join(parts)
    else:
        suggestions = "；".join(c.get("suggestion", "") for c in job.result.get("checks", []) if c.get("suggestion"))
    decision=Decision(id=uid(),version_id=job.version_id,reviewer_id=agent.id,outcome=target,
        opinion=(reason + "；" + suggestions + "。报告 " + job.id)[:5000],actor_type='agent',ai_job_id=job.id)
    session.add(decision);session.flush()
    if target == 'approved':
        session.add(Outbox(kind='review.approved',aggregate_id=sub.id,payload={'version_id':job.version_id,'decision_id':decision.id,'ai_job_id':job.id}))
    session.add(Audit(actor_id=agent.id,action='agent.review_' + target,object_id=job.version_id))
