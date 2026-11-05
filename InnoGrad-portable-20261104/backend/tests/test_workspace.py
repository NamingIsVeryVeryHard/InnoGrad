from sqlalchemy import select
from fastapi.testclient import TestClient
from app.db import User, StudentProfile, StudentImport, Supervision, RuleTemplate
from test_workflow import env, post, submitted


def student_body(ids, number='20260001'):
    return dict(name='新增学生', number=number, year='2026级', major='通信', direction='网络', teacher_id=ids['teacher'])


def test_student_creation_persists_and_can_login(env):
    app,c,ids=env
    data=post(c['manager'],'/api/v1/students',student_body(ids))
    assert data.status_code==201, data.text
    account=data.json()
    client=TestClient(app)
    login=client.post('/api/v1/auth/login',json={'username':account['username'],'password':account['initial_password']})
    assert login.status_code==200
    assert len(client.get('/api/v1/students').json())==1
    assert client.get('/api/v1/students').json()[0]['number']=='20260001'
    assert len(c['teacher'].get('/api/v1/students').json())==3
    assert len(c['student2'].get('/api/v1/students').json())==1
    assert c['operator'].get('/api/v1/students').json()==[]
    assert post(c['student1'],'/api/v1/students',student_body(ids,'bad')).status_code==403
    assert post(c['manager'],'/api/v1/students',student_body(ids)).status_code==409


def test_import_preview_revalidate_rollback_and_duplicate_commit(env):
    app,c,ids=env
    rows=[student_body(ids,'20260011'),student_body(ids,'20260012')]
    preview=post(c['manager'],'/api/v1/student-imports',{'rows':rows}).json()
    assert preview['valid']
    # Another transaction claims a number after preview; the entire batch must roll back.
    assert post(c['manager'],'/api/v1/students',rows[1]).status_code==201
    assert post(c['manager'],f"/api/v1/student-imports/{preview['id']}/commit",{}).status_code==409
    with app.state.sessions() as s:
        assert s.scalar(select(User).where(User.username=='20260011')) is None
        assert s.get(StudentImport,preview['id']).status=='preview'
    valid=post(c['manager'],'/api/v1/student-imports',{'rows':[rows[0]]}).json()
    url=f"/api/v1/student-imports/{valid['id']}/commit"
    assert post(c['teacher'],url,{}).status_code==403
    assert post(c['manager'],url,{}).status_code==200
    assert post(c['manager'],url,{}).status_code==409


def test_rules_are_frozen_and_enforced_by_submit(env):
    app,c,ids=env
    rule=post(c['manager'],'/api/v1/rules',{'title':'年度规则','content':'必须填写计划','required_fields':['summary','plan']}).json()
    t=post(c['manager'],'/api/v1/cultivation-tasks',dict(title='年度考核',period='2026',deadline='2026-12-31T00:00:00Z',reviewer_id=ids['teacher'],student_ids=[ids['student1']],rule_id=rule['id']))
    assert t.status_code==201,t.text
    task=t.json()['id']
    r=post(c['student1'],'/api/v1/submissions',{'kind':'annual','task_id':task}).json()
    ident=r['id'];url='/api/v1/submissions/'+ident
    f=c['student1'].post(url+'/files',files={'file':('proof.pdf',b'%PDF-1.7 fixture','application/pdf')}).json()
    body={'expected_lock_version':0,'form':{'summary':'已有研究总结'},'file_ids':[f['id']]}
    assert c['student1'].patch(url+'/draft',json=body).status_code==200
    assert post(c['student1'],url+'/submit',{'expected_lock_version':1}).status_code==422
    body['expected_lock_version']=1;body['form']['plan']='下一阶段实验计划'
    assert c['student1'].patch(url+'/draft',json=body).status_code==200
    assert post(c['student1'],url+'/submit',{'expected_lock_version':2}).status_code==202
    post(c['manager'],'/api/v1/rules',{'title':'另一版本','content':'新说明','required_fields':['summary']})
    assert c['student1'].get(url).json()['versions'][0]['snapshot']['requirements']['version']==rule['id']
    assert c['teacher'].get('/api/v1/me/tasks').json()[0]['student_ids']==[ids['student1']]
    assert c['student2'].get('/api/v1/me/tasks').json()==[]


def test_followup_scope_lock_and_persistence(env):
    app,c,ids=env
    data=post(c['teacher'],'/api/v1/alerts',{'student_id':ids['student1'],'title':'研究进展','text':'请更新报告'})
    assert data.status_code==201
    url='/api/v1/alerts/'+data.json()['id']
    assert c['student2'].get('/api/v1/alerts').json()==[]
    assert c['student2'].patch(url,json={'note':'x','status':'done','expected_lock_version':0}).status_code==404
    assert c['student1'].patch(url,json={'note':'已反馈','status':'done','expected_lock_version':0}).status_code==200
    assert c['teacher'].patch(url,json={'note':'迟到操作','status':'open','expected_lock_version':0}).status_code==409
    assert c['manager'].get('/api/v1/alerts').json()[0]['note']=='已反馈'


def test_revoked_scope_hides_profiles_tasks_and_alerts(env):
    app,c,ids=env
    post(c['manager'],'/api/v1/cultivation-tasks',dict(title='任务',period='2026',deadline='2026-12-31T00:00:00Z',reviewer_id=ids['teacher'],student_ids=[ids['student1']]))
    post(c['teacher'],'/api/v1/alerts',{'student_id':ids['student1'],'title':'提醒','text':'待补充'})
    with app.state.sessions.begin() as s:
        relation=s.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        relation.valid_to='2000-01-01T00:00:00+00:00'
    assert all(s['id']!=ids['student1'] for s in c['teacher'].get('/api/v1/students').json())
    assert c['teacher'].get('/api/v1/me/tasks').json()==[]
    assert c['teacher'].get('/api/v1/alerts').json()==[]


def test_submissions_file_metadata_and_archive_are_server_owned(env):
    app,c,ids=env
    ident,fid,_,result=submitted(env)
    row=c['teacher'].get('/api/v1/submissions/'+ident).json()
    assert row['draft'] is None
    assert row['files'][0]['id']==fid
    assert 'storage_key' not in row['files'][0]
    assert c['student2'].get('/api/v1/submissions/'+ident).status_code==404
    assert c['student1'].get('/api/v1/submissions?limit=0').status_code==422


def test_workspace_requires_session_and_csrf(env):
    app,c,ids=env
    for route in ('/students','/rules','/alerts','/audit-logs','/workspace/status'):
        assert TestClient(app).get('/api/v1'+route).status_code==401
    c['manager'].headers.pop('X-CSRF-Token')
    assert post(c['manager'],'/api/v1/students',student_body(ids)).status_code==403


def test_existing_student_profile_can_be_completed_without_changing_account(env):
    app,c,ids=env
    payload={'year':'2026级','major':'通信工程','direction':'卫星通信','stage':'课题研究'}
    url='/api/v1/students/'+ids['student1']+'/profile'
    assert c['teacher'].patch(url,json=payload).status_code==403
    assert c['manager'].patch(url,json=payload).status_code==200
    row=c['student1'].get('/api/v1/students').json()[0]
    assert row['major']=='通信工程' and row['number']=='student1'


def test_degree_exposed_validated_and_preserved_on_legacy_profile_update(env):
    app,c,ids=env
    row=c['student1'].get('/api/v1/students').json()[0]
    assert row['degree']=='博士' and row['major']=='智能教育'
    payload={'year':'2026级','major':'智能教育','direction':'学习分析','stage':'研究训练'}
    assert c['manager'].patch('/api/v1/students/'+ids['student1']+'/profile',json=payload).status_code==200
    assert c['student1'].get('/api/v1/students').json()[0]['degree']=='博士'
    assert c['manager'].patch('/api/v1/students/'+ids['student1']+'/profile',json={**payload,'degree':'任意值'}).status_code==422
    assert c['student2'].get('/api/v1/students').json()[0]['major']=='人工智能'
