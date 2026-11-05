"""Evidence-linked growth observations and scoped, actionable workflow warnings."""
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
import hashlib
from typing import Literal
from fastapi import Depends, Request
from pydantic import Field
from sqlalchemy import select, update
from .db import (User, Submission, Version, Archive, PortraitSnapshot, Task, Assignment,
                 Decision, AIJob, GrowthEntry, WarningAction, uid, now)
from .workspace import scope_ids
from .policy import relation
from .review_flow import review_context

DIMENSIONS = [
    ('goals','年度目标','研究计划、年度总结与下一阶段安排'),
    ('training','科研训练','论文研究与实验训练记录'),
    ('contribution','课题与贡献','本人承担的方法、实验和研究贡献'),
    ('education','教育契合','研究与教育问题、教学场景的联系'),
    ('exchange','学术交流','组会、报告、讲座及交流反思'),
    ('practice','实践落地','原型、系统、数据与应用验证')]


def authorized(session,user,student_id):
    student=session.get(User,student_id)
    return bool(student and student.role=='student' and student_id in scope_ids(session,user))


def warning_candidates(session, student_ids, instant=None):
    instant=instant or datetime.now(timezone.utc)
    results=[]
    def emit(sid,kind,obj,revision,title,description,severity,source_type,source_id):
        key=hashlib.sha256(f'{sid}|{kind}|{obj}|{revision}'.encode()).hexdigest()
        results.append(dict(id=key,student=sid,kind=kind,title=title,text=description,severity=severity,
            source_type=source_type,source_id=source_id,rule_version='growth-alerts-1',status='open',active=True))
    assignments=session.execute(select(Assignment,Task).join(Task,Assignment.task_id==Task.id).where(Assignment.student_id.in_(student_ids))).all()
    subs=session.scalars(select(Submission).where(Submission.student_id.in_(student_ids))).all()
    for assignment,task in assignments:
        sub=next((s for s in subs if s.student_id==assignment.student_id and s.task_id==task.id),None)
        if sub and sub.current_version_id: continue
        deadline=datetime.fromisoformat(task.deadline)
        days=(deadline-instant).total_seconds()/86400
        if days<0:
            emit(assignment.student_id,'overdue',task.id,task.deadline,'年度材料已逾期',f'任务「{task.title}」截止后仍未正式提交。请确认材料准备情况并安排支持。','high','task',task.id)
        elif days<=7:
            emit(assignment.student_id,'due_soon',task.id,task.deadline,'培养任务即将截止',f'任务「{task.title}」将在 7 天内截止，当前尚无正式提交。','medium','task',task.id)
    for sub in subs:
        if sub.status=='returned':
            emit(sub.student_id,'returned',sub.id,sub.current_version_id,'材料需要补充', '材料已退回或重开，请根据处理意见补充后重新提交。','medium','submission',sub.id)
        if sub.status=='pending_review':
            job=session.scalar(select(AIJob).where(AIJob.submission_id==sub.id,AIJob.version_id==sub.current_version_id).order_by(AIJob.created_at.desc(),AIJob.id.desc()).limit(1))
            context = review_context(session, job, sub) if job else {}
            if context.get('institution_required'):
                outcome = context['material_review']
                emit(sub.student_id,'agent_exception',sub.id,job.id,'审核异常待核验',
                     (outcome.get('reason') or outcome['label'])+'。请查看审核报告与原件，记录下一步处理。','high','submission',sub.id)
    today=instant.astimezone(ZoneInfo('Asia/Shanghai')).date()
    for entry in session.scalars(select(GrowthEntry).where(GrowthEntry.student_id.in_(student_ids),GrowthEntry.kind.in_(['goal','milestone']),GrowthEntry.status=='planned')):
        if entry.due_date and date.fromisoformat(entry.due_date)<today:
            emit(entry.student_id,'goal_overdue',entry.id,entry.due_date,'研究计划需要跟进',f'计划「{entry.title}」已到约定日期，尚未记录完成。请确认进展或调整安排。','medium','growth',entry.id)
    return results


def warnings_for(session,user,instant=None):
    ids=scope_ids(session,user)
    candidates={w['id']:w for w in warning_candidates(session,ids,instant)}
    history={}
    for a in session.scalars(select(WarningAction).where(WarningAction.student_id.in_(ids)).order_by(WarningAction.created_at,WarningAction.id)):
        history.setdefault(a.warning_key,[]).append(a)
    output=[]
    for key in candidates.keys()|history.keys():
        actions=history.get(key,[])
        item=dict(candidates[key]) if key in candidates else {**actions[-1].payload,'active':False}
        item.update(status=actions[-1].status if actions and item['active'] else 'open' if item['active'] else 'cleared',
            revision=actions[-1].id if actions else '',note=actions[-1].note if actions else '',
            history=[dict(id=a.id,status=a.status,note=a.note,actor=session.get(User,a.actor_id).name,time=a.created_at) for a in actions])
        output.append(item)
    return sorted(output,key=lambda w:(w['status'] not in ('open','tracking'),w['severity']!='high',w['title'],w['id']))


def serialize_entry(session,row):
    version=session.get(Version,row.source_version_id) if row.source_version_id else None
    sub=session.get(Submission,version.submission_id) if version else None
    archive=session.get(Archive,sub.effective_archive_id) if sub and sub.effective_archive_id else None
    return dict(id=row.id,student_id=row.student_id,created_by=row.created_by,author=session.get(User,row.created_by).name,
        kind=row.kind,title=row.title,body=row.body,period=row.period,dimension=row.dimension,due_date=row.due_date,
        status=row.status,lock_version=row.lock_version,created_at=row.created_at,updated_at=row.updated_at,
        source=dict(submission_id=sub.id,version_id=version.id,number=version.number,field=row.source_field,quote=row.source_quote,
                    current=bool(archive and archive.version_id==version.id)) if version else None)


def dashboard_data(session,user,student_id,period=None):
    entries=[serialize_entry(session,e) for e in session.scalars(select(GrowthEntry).where(GrowthEntry.student_id==student_id).order_by(GrowthEntry.created_at.desc(),GrowthEntry.id))]
    rows=session.execute(select(Submission,Archive,Version).join(Archive,Submission.effective_archive_id==Archive.id)
        .join(Version,Archive.version_id==Version.id).where(Submission.student_id==student_id)).all()
    periods={e['period'] for e in entries}
    periods.update(v.snapshot.get('period') for _,_,v in rows if v.snapshot.get('period'))
    periods.update(session.scalars(select(Task.period).join(Assignment).where(Assignment.student_id==student_id)))
    selected_entries=[e for e in entries if not period or e['period']==period]
    selected_rows=[r for r in rows if not period or r[2].snapshot.get('period')==period]
    sources=[]
    for sub,archive,version in selected_rows:
        sources.append(dict(submission_id=sub.id,archive_id=archive.id,version_id=version.id,number=version.number,kind=sub.kind,
            title=version.snapshot['form'].get('title') or '年度培养报告',form=version.snapshot['form'],period=version.snapshot.get('period'),
            archived_at=archive.created_at,files=version.snapshot.get('file_ids',[]),rule_version=version.snapshot['requirements'].get('version')))
    dimensions=[]
    for key,label,description in DIMENSIONS:
        evidence=[]
        for source in sources:
            form=source['form']
            field='plan' if key=='goals' and form.get('plan') else 'summary' if key=='goals' and source['kind']=='annual' else 'publication_status' if key=='training' and source['kind']=='paper' else 'contribution' if key=='contribution' and source['kind']=='paper' else None
            if field and form.get(field): evidence.append(dict(submission_id=source['submission_id'],version_id=source['version_id'],field=field,quote=form[field],title=source['title'],origin='archive'))
        for entry in selected_entries:
            if entry['dimension']==key and entry['source'] and entry['source']['current']:
                ref=entry['source']
                evidence.append(dict(submission_id=ref['submission_id'],version_id=ref['version_id'],field=ref['field'],quote=ref['quote'],title=entry['title'],origin='observation'))
        unique={ (e['version_id'],e['field'],e['quote']):e for e in evidence }
        dimensions.append(dict(key=key,label=label,description=description,count=len(unique),score=None,evidence=list(unique.values()),status='有材料依据' if unique else '待关联材料'))
    # Counts describe effective records grouped by their real archive month, not inferred ability growth.
    months={}
    for source in sources:
        month=datetime.fromisoformat(source['archived_at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m')
        months.setdefault(month,{'month':month,'paper':0,'annual':0})[source['kind']]+=1
    visible_subs=session.scalars(select(Submission).where(Submission.student_id==student_id)).all()
    if user.id!=student_id: visible_subs=[s for s in visible_subs if s.current_version_id]
    if period:
        task_ids=set(session.scalars(select(Task.id).where(Task.period==period)))
        def in_period(sub):
            if sub.task_id in task_ids:return True
            if sub.kind!='paper':return False
            archive=session.get(Archive,sub.effective_archive_id) if sub.effective_archive_id else None
            version=session.get(Version,archive.version_id if archive else sub.current_version_id) if archive or sub.current_version_id else None
            return bool(version and version.snapshot.get('period')==period)
        visible_subs=[s for s in visible_subs if in_period(s)]
    assignments=session.execute(select(Task,Assignment).join(Assignment,Assignment.task_id==Task.id).where(Assignment.student_id==student_id)).all()
    if period: assignments=[r for r in assignments if r[0].period==period]
    return dict(student_id=student_id,period=period,periods=sorted(periods,reverse=True),sources=sources,entries=selected_entries,dimensions=dimensions,
        coverage=sum(d['count']>0 for d in dimensions),dimension_count=6,trend=sorted(months.values(),key=lambda m:m['month']),
        counts=dict(materials=len(visible_subs),archives=len(sources),papers=sum(s['kind']=='paper' for s in sources),annual=sum(s['kind']=='annual' for s in sources),
                    pending=sum(s.status=='pending_review' for s in visible_subs),returned=sum(s.status=='returned' for s in visible_subs),tasks=len(assignments)),
        unassigned_period_count=sum(not v.snapshot.get('period') for _,_,v in rows),
        notice='六类方向用于材料观察，与历史八维初评分及隐性能力量表分开。显示实际来源数量，不计算能力分或排名。',
        warnings=[w for w in warnings_for(session,user) if w['student']==student_id])


def register(app,ctx):
    from .main import Input
    db,auth,error,audit,replay,finish=(ctx[k] for k in ('db','authenticated','error','audit','replay','finish'))
    class EntryInput(Input):
        kind: Literal['goal','milestone','reflection','feedback','observation']
        title: str=Field(min_length=1,max_length=200)
        body: str=Field(min_length=1,max_length=6000)
        period: str=Field(min_length=1,max_length=80)
        dimension: Literal['goals','training','contribution','education','exchange','practice']|None=None
        due_date: date|None=None
        source_submission_id: str|None=None
        source_field: str|None=None
        source_quote: str|None=Field(default=None,max_length=4000)
    class CompleteInput(Input):
        expected_lock_version:int=Field(ge=0)
        status:Literal['planned','done']
    class PlanInput(Input):
        expected_lock_version:int=Field(ge=0)
        title:str=Field(min_length=1,max_length=200)
        body:str=Field(min_length=1,max_length=6000)
        due_date:date|None=None

    class WarningInput(Input):
        expected_revision:str=''
        status:Literal['tracking','resolved','dismissed']
        note:str=Field(min_length=1,max_length=4000)

    @app.get('/api/v1/students/{student_id}/growth')
    def growth(student_id:str,period:str|None=None,user=Depends(auth),session=Depends(db)):
        if not authorized(session,user,student_id):error(404,'学生不存在或无权访问')
        return dashboard_data(session,user,student_id,period)

    @app.post('/api/v1/students/{student_id}/growth',status_code=201)
    def create_entry(student_id:str,body:EntryInput,request:Request,user=Depends(auth),session=Depends(db)):
        if not authorized(session,user,student_id):error(404,'学生不存在或无权访问')
        if body.kind in ('feedback','observation') and user.role not in ('teacher','manager'):error(403,'此类记录由授权教师创建')
        old,idem=replay(session,request,user,body.model_dump(mode='json'))
        if old is not None:return old
        source_version=None
        if body.source_submission_id:
            sub=session.get(Submission,body.source_submission_id)
            if not sub or sub.student_id!=student_id or not sub.effective_archive_id:error(422,'只能关联本学生当前有效档案')
            archive=session.get(Archive,sub.effective_archive_id)
            source_version=session.get(Version,archive.version_id)
            value=source_version.snapshot['form'].get(body.source_field)
            if not isinstance(value,str) or not body.source_quote or body.source_quote not in value:error(422,'引用文字必须来自所选档案字段原文')
        elif body.source_field or body.source_quote:error(422,'请先选择来源材料')
        if body.kind=='observation' and (not source_version or not body.dimension):error(422,'材料观察需要维度和有效档案依据')
        row=GrowthEntry(id=uid(),student_id=student_id,created_by=user.id,kind=body.kind,title=body.title,body=body.body,
            period=body.period,dimension=body.dimension,due_date=body.due_date.isoformat() if body.due_date else None,
            source_version_id=source_version.id if source_version else None,source_field=body.source_field,source_quote=body.source_quote,
            status='planned' if body.kind in ('goal','milestone') else 'done')
        session.add(row);audit(session,user,'growth.'+body.kind,row.id)
        return finish(session,idem,{'id':row.id})

    @app.patch('/api/v1/growth/{ident}')
    def complete(ident:str,body:CompleteInput,user=Depends(auth),session=Depends(db)):
        row=session.get(GrowthEntry,ident)
        if not row or not authorized(session,user,row.student_id):error(404,'记录不存在')
        if user.id not in (row.created_by,row.student_id) or row.kind not in ('goal','milestone'):error(403,'只能更新本人计划或自己的研究目标')
        changed=session.execute(update(GrowthEntry).where(GrowthEntry.id==ident,GrowthEntry.lock_version==body.expected_lock_version)
            .values(status=body.status,lock_version=body.expected_lock_version+1,updated_at=now()))
        if not changed.rowcount:error(409,'记录已更新，请刷新重试')
        audit(session,user,'growth.status_updated',row.id);session.commit()
        return {'ok':True}

    @app.patch('/api/v1/growth/{ident}/plan')
    def revise_plan(ident:str,body:PlanInput,user=Depends(auth),session=Depends(db)):
        row=session.get(GrowthEntry,ident)
        if not row or not authorized(session,user,row.student_id):error(404,'记录不存在')
        if user.id not in (row.created_by,row.student_id) or row.kind not in ('goal','milestone'):error(403,'只能调整本人创建或本人的研究计划')
        changed=session.execute(update(GrowthEntry).where(GrowthEntry.id==ident,GrowthEntry.lock_version==body.expected_lock_version)
            .values(title=body.title,body=body.body,due_date=body.due_date.isoformat() if body.due_date else None,
                lock_version=body.expected_lock_version+1,updated_at=now()))
        if not changed.rowcount:error(409,'记录已更新，请刷新重试')
        audit(session,user,'growth.plan_revised',ident);session.commit()
        return {'ok':True}

    @app.get('/api/v1/growth-overview')
    def overview(period:str|None=None,user=Depends(auth),session=Depends(db)):
        items=[]
        for sid in scope_ids(session,user):
            person=session.get(User,sid)
            if not person or person.role!='student':continue
            data=dashboard_data(session,user,sid,period)
            items.append(dict(student_id=sid,name=person.name,counts=data['counts'],coverage=data['coverage'],
                dimensions=[dict(key=d['key'],label=d['label'],count=d['count'],score=None) for d in data['dimensions']],
                warnings=sum(w['status'] in ('open','tracking') for w in data['warnings'])))
        return {'items':items,'dimensions':[dict(key=k,label=l) for k,l,_ in DIMENSIONS],
                'notice':'展示授权范围内的材料依据数量，不计算能力均分、排名或把缺失记录填成零分。'}

    @app.get('/api/v1/warnings')
    def warnings(user=Depends(auth),session=Depends(db)):
        return warnings_for(session,user)

    @app.post('/api/v1/warnings/{ident}/actions')
    def warning_action(ident:str,body:WarningInput,request:Request,user=Depends(auth),session=Depends(db)):
        if user.role not in ('teacher','manager'):error(403,'预警处理由授权教师记录；学生可通过站内提醒反馈')
        old,idem=replay(session,request,user,body.model_dump())
        if old is not None:return old
        candidate=next((w for w in warnings_for(session,user) if w['id']==ident),None)
        if not candidate or not candidate['active']:error(404,'预警已消除或无权处理')
        # Serialize competing action writes on the student's row before re-reading revision.
        session.execute(update(User).where(User.id==candidate['student']).values(enabled=User.enabled))
        candidate=next(w for w in warnings_for(session,user) if w['id']==ident)
        if candidate['revision']!=body.expected_revision:error(409,'跟进记录已变化，请刷新重试')
        row=WarningAction(id=uid(),warning_key=ident,student_id=candidate['student'],actor_id=user.id,status=body.status,note=body.note,
            payload={k:v for k,v in candidate.items() if k not in ('history','revision','note')})
        session.add(row);audit(session,user,'warning.'+body.status,row.id)
        return finish(session,idem,{'id':row.id})
