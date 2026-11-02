from datetime import datetime,timezone,timedelta
from sqlalchemy import select,func
from test_workflow import env,post
from test_extensions import archive
from app.db import GrowthEntry,WarningAction,Supervision
from app.growth import warning_candidates,warnings_for


def entry(kind='goal',**extra):
    return dict(kind=kind,title='阶段研究计划',body='完善研究材料与对照实验',period='2026—2027',**extra)


def test_growth_persistence_scope_and_stale_update(env):
    app,c,ids=env;url='/api/v1/students/'+ids['student1']+'/growth'
    created=post(c['student1'],url,entry()).json()
    assert c['teacher'].get(url).json()['entries'][0]['title']=='阶段研究计划'
    assert c['student2'].get(url).status_code==404
    assert c['operator'].get(url).status_code==404
    update_url='/api/v1/growth/'+created['id']
    assert c['student2'].patch(update_url,json={'expected_lock_version':0,'status':'done'}).status_code==404
    assert c['student1'].patch(update_url,json={'expected_lock_version':0,'status':'done'}).status_code==200
    assert c['student1'].patch(update_url,json={'expected_lock_version':0,'status':'planned'}).status_code==409
    assert c['student1'].get(url).json()['entries'][0]['status']=='done'
    assert post(c['student1'],url,entry('feedback')).status_code==403


def test_evidence_mapping_deduplication_and_period_boundaries(env):
    app,c,ids=env;ident,_,_=archive(env)
    url='/api/v1/students/'+ids['student1']+'/growth'
    baseline=c['teacher'].get(url).json()
    assert baseline['coverage']==2
    assert all(d['score'] is None for d in baseline['dimensions'])
    body=entry('observation',dimension='contribution',source_submission_id=ident,source_field='contribution',source_quote='实验设计')
    assert post(c['teacher'],url,body).status_code==201
    assert post(c['teacher'],url,body).status_code==201
    data=c['teacher'].get(url).json()
    assert next(d for d in data['dimensions'] if d['key']=='contribution')['count']==1
    assert c['teacher'].get(url+'?period=2026—2027').json()['counts']['papers']==0
    assert c['teacher'].get(url+'?period=2026—2027').json()['unassigned_period_count']==1
    assert post(c['teacher'],url,{**body,'source_quote':'不存在的证据'}).status_code==422
    assert post(c['teacher'],'/api/v1/students/'+ids['student2']+'/growth',body).status_code==422


def test_deadlines_generate_no_duplicate_and_private_draft_not_exposed(env):
    app,c,ids=env
    deadline='2026-11-10T00:00:00+00:00'
    task=post(c['manager'],'/api/v1/cultivation-tasks',dict(title='阶段报告',period='2026',deadline=deadline,reviewer_id=ids['teacher'],student_ids=[ids['student1']])).json()
    sub=post(c['student1'],'/api/v1/submissions',{'kind':'annual','task_id':task['id']}).json()
    c['student1'].patch('/api/v1/submissions/'+sub['id']+'/draft',json={'expected_lock_version':0,'form':{'summary':'PRIVATE DRAFT'}})
    with app.state.sessions() as s:
        soon=warning_candidates(s,[ids['student1']],datetime(2026,11,5,tzinfo=timezone.utc))
        late=warning_candidates(s,[ids['student1']],datetime(2026,11,11,tzinfo=timezone.utc))
        assert soon[0]['kind']=='due_soon' and late[0]['kind']=='overdue'
        assert 'PRIVATE' not in str(soon)
        assert warning_candidates(s,[ids['student2']],datetime(2026,11,11,tzinfo=timezone.utc))==[]
        assert late==warning_candidates(s,[ids['student1']],datetime(2026,11,11,tzinfo=timezone.utc))
    assert not c['teacher'].get('/api/v1/students/'+ids['student1']+'/growth').json()['counts']['materials']


def test_warning_followup_history_natural_resolution_and_locks(env):
    app,c,ids=env;url='/api/v1/students/'+ids['student1']+'/growth'
    created=post(c['student1'],url,entry(due_date='2000-01-01')).json()
    warning=c['teacher'].get('/api/v1/warnings').json()[0]
    endpoint='/api/v1/warnings/'+warning['id']+'/actions'
    body={'expected_revision':'','status':'tracking','note':'已沟通，补充进展'}
    assert post(c['student1'],endpoint,body).status_code==403
    assert post(c['manager'],endpoint,body).status_code==200
    assert post(c['teacher'],endpoint,body).status_code==409
    updated=c['student1'].get('/api/v1/warnings').json()[0]
    assert updated['status']=='tracking' and len(updated['history'])==1
    assert c['student2'].get('/api/v1/warnings').json()==[]
    c['student1'].patch('/api/v1/growth/'+created['id'],json={'expected_lock_version':0,'status':'done'})
    cleared=c['teacher'].get('/api/v1/warnings').json()[0]
    assert cleared['status']=='cleared' and not cleared['active'] and len(cleared['history'])==1
    assert post(c['teacher'],endpoint,{'expected_revision':updated['revision'],'status':'resolved','note':'x'}).status_code==404


def test_growth_revocation_and_group_scope(env):
    app,c,ids=env
    post(c['student1'],'/api/v1/students/'+ids['student1']+'/growth',entry(due_date='2000-01-01'))
    assert len(c['manager'].get('/api/v1/growth-overview').json()['items'])==2
    assert len(c['student2'].get('/api/v1/growth-overview').json()['items'])==1
    with app.state.sessions.begin() as s:
        rel=s.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        rel.valid_to='2000-01-01T00:00:00+00:00'
    assert c['teacher'].get('/api/v1/students/'+ids['student1']+'/growth').status_code==404
    assert c['teacher'].get('/api/v1/warnings').json()==[]
    assert len(c['teacher'].get('/api/v1/growth-overview').json()['items'])==1


def test_obsolete_observation_does_not_count_as_current_evidence(env):
    app,c,ids=env;ident,_,original=archive(env)
    url='/api/v1/students/'+ids['student1']+'/growth'
    post(c['teacher'],url,entry('observation',dimension='education',source_submission_id=ident,source_field='contribution',source_quote='实验设计'))
    assert c['teacher'].get(url).json()['coverage']==3
    # Existing archive continues to count while a newer draft is under preparation.
    post(c['student1'],'/api/v1/submissions/'+ident+'/updates',{'expected_lock_version':original['lock_version'],'reason':'更新'})
    assert c['teacher'].get(url).json()['coverage']==3
    from app.db import Archive,Version,Decision,uid,Submission
    with app.state.sessions.begin() as s:
        sub=s.get(Submission,ident);old=s.get(Version,sub.current_version_id)
        v=Version(id=uid(),submission_id=ident,number=2,snapshot=old.snapshot)
        s.add(v);s.flush()
        d=Decision(id=uid(),version_id=v.id,reviewer_id=ids['teacher'],outcome='approved',opinion='test');s.add(d);s.flush()
        a=Archive(id=uid(),version_id=v.id,decision_id=d.id);s.add(a);s.flush();sub.effective_archive_id=a.id
    data=c['teacher'].get(url).json()
    assert data['coverage']==2
    assert data['entries'][0]['source']['current'] is False


def test_plan_revision_recalculates_due_warning(env):
    app,c,ids=env
    r=post(c['student1'],'/api/v1/students/'+ids['student1']+'/growth',entry(due_date='2000-01-01')).json()
    assert len(c['student1'].get('/api/v1/warnings').json())==1
    payload={'expected_lock_version':0,'title':'调整后的计划','body':'下阶段完成','due_date':'2099-01-01'}
    assert c['student2'].patch('/api/v1/growth/'+r['id']+'/plan',json=payload).status_code==404
    assert c['student1'].patch('/api/v1/growth/'+r['id']+'/plan',json=payload).status_code==200
    assert c['student1'].get('/api/v1/warnings').json()==[]
    assert c['student1'].patch('/api/v1/growth/'+r['id']+'/plan',json=payload).status_code==409
