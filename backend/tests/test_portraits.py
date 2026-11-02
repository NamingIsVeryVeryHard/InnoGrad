"""Synthetic API/worker end-to-end checks; no external model requests."""
import io
import zipfile
from sqlalchemy import select, func
from test_workflow import env, post, paper
from test_extensions import archive
from app.db import PortraitSnapshot, Outbox, Supervision, Archive
from app.jobs import run_ai
from app.worker import drain


def test_full_synthetic_loop(env):
    app, clients, ids = env
    student, teacher = clients['student1'], clients['teacher']
    ident, _, draft = paper(env)
    url = '/api/v1/submissions/' + ident
    doc = io.BytesIO()
    with zipfile.ZipFile(doc, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>合成演示材料：完成实验设计，不对应真实学生。</w:t></w:r></w:p></w:body></w:document>')
    fid = student.post(url+'/files', files={'file': ('合成演示.docx', doc.getvalue())}).json()['id']
    draft.update(expected_lock_version=1, file_ids=[fid])
    assert student.patch(url+'/draft', json=draft).status_code == 200
    first = post(student, url+'/submit', {'expected_lock_version': 2}).json()
    assert run_ai(app.state.sessions, app.state.test_file_root)
    result = student.get('/api/v1/ai-jobs/'+first['ai_job_id']).json()
    assert result['status'] == 'succeeded' and result['mode'] == 'rules'
    assert '合成演示材料' in result['result']['blocks'][0]['text']
    assert result['result']['automatic_approval'] is False
    assert post(teacher, url+'/decision', {'expected_lock_version':3,'version_id':first['version_id'], 'outcome':'returned','opinion':'合成测试：补充个人贡献'}).status_code == 200
    draft['expected_lock_version'] = 4
    draft['form']['contribution'] = '合成测试：补充后的贡献'
    assert student.patch(url+'/draft',json=draft).status_code == 200
    second = post(student,url+'/submit',{'expected_lock_version':5}).json()
    assert post(teacher,url+'/decision',{'expected_lock_version':6,'version_id':second['version_id'],'outcome':'approved','opinion':'合成材料人工复核通过'}).status_code == 200
    drain(app.state.sessions)
    portrait = student.get('/api/v1/students/'+ids['student1']+'/portrait').json()
    assert len(portrait['records']) == 1 and portrait['ability_assessment'] == '待评价'
    record = portrait['records'][0]
    assert record['version_id'] == second['version_id']
    assert next(f for f in record['facts'] if f['field']=='contribution')['value'] == draft['form']['contribution']
    assert record['files'][0]['file_id'] == fid and record['inferences'] == []
    assert run_ai(app.state.sessions, app.state.test_file_root)
    assert student.get('/api/v1/ai-jobs/'+second['ai_job_id']).json()['historical_only']
    assert student.get('/api/v1/students/'+ids['student1']+'/portrait').json() == portrait


def test_portrait_permissions_and_revocation(env):
    app,c,ids = env
    archive(env)
    path = '/api/v1/students/'+ids['student1']+'/portrait'
    for actor in ('student1','teacher','manager'):
        assert c[actor].get(path).status_code == 200
    for actor in ('student2','operator'):
        assert c[actor].get(path).status_code == 404
    with app.state.sessions.begin() as session:
        rel=session.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        rel.valid_to='2020-01-01T00:00:00+00:00'
    assert c['teacher'].get(path).status_code == 404


def test_correction_preserves_old_snapshot_and_duplicate_event(env):
    app,c,ids = env
    ident,_,original = archive(env)
    path='/api/v1/students/'+ids['student1']+'/portrait'
    before=c['student1'].get(path).json()
    url='/api/v1/submissions/'+ident
    assert post(c['student1'],url+'/updates',{'expected_lock_version':original['lock_version'],'reason':'合成测试：论文进展更新'}).status_code==200
    opened=c['student1'].get(url).json()
    draft=opened['draft']; draft['form']['title']='合成测试：更新标题'
    assert c['student1'].patch(url+'/draft',json={**draft,'expected_lock_version':opened['lock_version']}).status_code==200
    current=c['student1'].get(url).json()
    submitted=post(c['student1'],url+'/submit',{'expected_lock_version':current['lock_version']}).json()
    assert c['student1'].get(path).json()==before
    assert post(c['teacher'],url+'/decision',{'expected_lock_version':submitted['lock_version'],'version_id':submitted['version_id'],'outcome':'approved','opinion':'合成测试通过'}).status_code==200
    drain(app.state.sessions)
    after=c['student1'].get(path).json()
    assert len(after['records'])==1 and after['records'][0]['archive_id']!=before['records'][0]['archive_id']
    with app.state.sessions.begin() as session:
        old=session.get(Archive,before['records'][0]['archive_id'])
        session.add(Outbox(kind='review.approved',aggregate_id=ident,payload={'version_id':old.version_id,'decision_id':old.decision_id}))
    drain(app.state.sessions)
    assert c['student1'].get(path).json()==after
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PortraitSnapshot))==2


def test_portrait_failure_rolls_back_archive(env, monkeypatch):
    from test_workflow import submitted
    from app import portraits
    app,c,ids=env
    ident,_,_,result=submitted(env)
    post(c['teacher'],f'/api/v1/submissions/{ident}/decision',{'expected_lock_version':2,'version_id':result['version_id'],'outcome':'approved','opinion':'合成测试通过'})
    original=portraits.ensure_snapshot
    def broken(*args): raise RuntimeError('synthetic failure')
    monkeypatch.setattr('app.portraits.ensure_snapshot',broken)
    assert drain(app.state.sessions) == 1
    assert c['student1'].get(f'/api/v1/submissions/{ident}').json()['status']=='approved'
    with app.state.sessions() as s:
        event=s.scalar(select(Outbox).where(Outbox.aggregate_id==ident, Outbox.kind=='review.approved'))
        assert event.status=='pending' and event.error_code=='ARCHIVE_RETRY'
    with app.state.sessions.begin() as s:
        s.scalar(select(Outbox).where(Outbox.aggregate_id==ident, Outbox.kind=='review.approved')).next_attempt_at=None
    monkeypatch.setattr('app.portraits.ensure_snapshot',original)
    drain(app.state.sessions)
    assert c['student1'].get(f'/api/v1/submissions/{ident}').json()['status']=='archived'
