from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import create_app
from app.db import Base, Version, Archive, Supervision
from app.seed import seed
from app.worker import drain

@pytest.fixture
def env(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}", tmp_path / 'files')
    app.state.test_file_root = tmp_path / 'files'
    Base.metadata.create_all(app.state.engine)
    clients, ids = {}, {}
    for username, password in seed(app.state.sessions).items():
        client = TestClient(app)
        r = client.post('/api/v1/auth/login', json={'username': username, 'password': password})
        assert r.status_code == 200
        client.headers['X-CSRF-Token'] = r.json()['csrf_token']
        clients[username], ids[username] = client, r.json()['user']['id']
    yield app, clients, ids
    app.state.engine.dispose()

def post(c, path, body, key=None):
    return c.post(path, json=body, headers={'Idempotency-Key': key or str(uuid4())})

def paper(env):
    app,c,ids = env
    r = post(c['student1'], '/api/v1/submissions', {'kind':'paper','reviewer_id':ids['teacher']})
    assert r.status_code == 201, r.text
    ident = r.json()['id']
    f = c['student1'].post(f'/api/v1/submissions/{ident}/files', files={'file':('proof.pdf',b'%PDF-1.7 synthetic','application/pdf')})
    assert f.status_code == 201
    body = {'expected_lock_version':0,'form':{'title':'测试论文','contribution':'实验设计','publication_status':'accepted','acceptance_date':'2026-10-20'},'file_ids':[f.json()['id']]}
    assert c['student1'].patch(f'/api/v1/submissions/{ident}/draft',json=body).status_code == 200
    return ident,f.json()['id'],body

def submitted(env):
    ident,fid,draft = paper(env)
    r = post(env[1]['student1'],f'/api/v1/submissions/{ident}/submit',{'expected_lock_version':1})
    assert r.status_code == 202,r.text
    return ident,fid,draft,r.json()

def test_return_resubmit_archive(env):
    app,c,ids = env
    ident,_,draft,first = submitted(env)
    url=f'/api/v1/submissions/{ident}'
    r=post(c['teacher'],url+'/decision',{'expected_lock_version':2,'version_id':first['version_id'],'outcome':'returned','opinion':'请补充贡献'})
    assert r.status_code == 200,r.text
    draft['expected_lock_version']=3
    draft['form']['contribution']='补正后的贡献'
    assert c['student1'].patch(url+'/draft',json=draft).status_code==200
    second=post(c['student1'],url+'/submit',{'expected_lock_version':4}).json()
    assert second['number']==2
    assert post(c['teacher'],url+'/decision',{'expected_lock_version':5,'version_id':second['version_id'],'outcome':'approved','opinion':'材料完整'}).status_code==200
    assert c['student1'].get(url).json()['status']=='approved'
    assert drain(app.state.sessions)==3
    assert drain(app.state.sessions)==0
    detail=c['student1'].get(url).json()
    assert detail['status']=='archived' and detail['effective_archive_id']
    assert detail['versions'][0]['snapshot']['form']['contribution']=='实验设计'
    with app.state.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Archive))==1

def test_submit_idempotency(env):
    ident,_,_=paper(env)
    client=env[1]['student1'];url=f'/api/v1/submissions/{ident}/submit'
    a=post(client,url,{'expected_lock_version':1},'same')
    b=post(client,url,{'expected_lock_version':1},'same')
    assert a.json()==b.json()
    assert post(client,url,{'expected_lock_version':2},'same').status_code==409
    with env[0].state.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Version))==1

def test_cross_student_and_operator(env):
    ident,fid,_,result=submitted(env)
    for actor in ('student2','operator'):
        c=env[1][actor]
        assert c.get(f'/api/v1/submissions/{ident}').status_code==404
        assert c.get(f'/api/v1/files/{fid}/download').status_code==404
        assert c.get(f'/api/v1/events/{result["event_id"]}').status_code==404
    assert env[1]['operator'].get('/api/v1/submissions').json()==[]

def test_auth_csrf_and_origin(env):
    app,c,ids=env
    assert TestClient(app).get('/api/v1/submissions').status_code==401
    c['student1'].headers.pop('X-CSRF-Token')
    assert post(c['student1'],'/api/v1/submissions',{'kind':'paper','reviewer_id':ids['teacher']}).status_code==403
    assert TestClient(app).post('/api/v1/auth/login',json={'username':'student1','password':'bad'},headers={'Origin':'https://evil.test'}).status_code==403

def test_private_draft_hidden(env):
    ident,fid,_=paper(env);c=env[1]
    assert c['teacher'].get(f'/api/v1/submissions/{ident}').status_code==404
    assert c['teacher'].get(f'/api/v1/files/{fid}/download').status_code==404
    post(c['student1'],f'/api/v1/submissions/{ident}/submit',{'expected_lock_version':1})
    assert c['teacher'].get(f'/api/v1/submissions/{ident}').json()['draft'] is None

def test_revoked_relation(env):
    ident,fid,_,_=submitted(env);app,c,ids=env
    with app.state.sessions.begin() as s:
        rel=s.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        rel.valid_to='2020-01-01T00:00:00+00:00'
    assert c['teacher'].get(f'/api/v1/files/{fid}/download').status_code==404
    assert c['teacher'].get('/api/v1/submissions').json()==[]

def test_validation_and_stale_lock(env):
    ident,_,draft=paper(env);c=env[1]['student1'];url=f'/api/v1/submissions/{ident}'
    assert c.patch(url+'/draft',json=draft).status_code==409
    assert c.post(url+'/files',files={'file':('fake.pdf',b'fake','application/pdf')}).status_code==422
    draft['expected_lock_version']=1;draft['file_ids']=[]
    assert c.patch(url+'/draft',json=draft).status_code==200
    assert post(c,url+'/submit',{'expected_lock_version':2}).status_code==422

def test_annual_assignment_and_manual_routing(env):
    app,c,ids=env
    r=post(c['manager'],'/api/v1/cultivation-tasks',{'title':'年度报告','period':'2025—2026学年','deadline':'2026-10-01T00:00:00+08:00','reviewer_id':ids['teacher'],'student_ids':[ids['student1']]})
    assert r.status_code==201,r.text
    task=r.json()['id']
    assert c['student2'].get('/api/v1/me/tasks').json()==[]
    body={'kind':'annual','task_id':task}
    assert post(c['student2'],'/api/v1/submissions',body).status_code==404
    ident=post(c['student1'],'/api/v1/submissions',body).json()['id']
    assert post(c['student1'],'/api/v1/submissions',body).status_code==409
    fid=c['student1'].post(f'/api/v1/submissions/{ident}/files',files={'file':('report.pdf',b'%PDF-1.7 synthetic','application/pdf')}).json()['id']
    c['student1'].patch(f'/api/v1/submissions/{ident}/draft',json={'expected_lock_version':0,'form':{'summary':'完成实验'},'file_ids':[fid]})
    result=post(c['student1'],f'/api/v1/submissions/{ident}/submit',{'expected_lock_version':1})
    assert result.status_code==202 and result.json()['status']=='pending_review'
    snapshot=c['teacher'].get(f'/api/v1/submissions/{ident}').json()['versions'][0]['snapshot']
    assert snapshot['late'] and snapshot['requirements']['review_policy']=='manual_all'

def test_concurrent_decisions(env):
    ident,_,_,result=submitted(env);app,c,ids=env
    body={'expected_lock_version':2,'version_id':result['version_id'],'outcome':'approved','opinion':'通过'}
    def decide(_):
        return post(c['teacher'],f'/api/v1/submissions/{ident}/decision',body).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(decide,range(2)))
    assert sorted(statuses)==[200,409]
    drain(app.state.sessions)
    with app.state.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Archive))==1

def test_manager_can_select_scoped_reviewer(env):
    app,c,ids=env
    people=c['manager'].get('/api/v1/people').json()
    assert any(p['id']==ids['teacher'] for p in people)
    assert not any(p['id']==ids['operator'] for p in people)
