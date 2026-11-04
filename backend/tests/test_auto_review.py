from sqlalchemy import select,func
import pytest
from app.db import AIJob,Submission,Decision,Archive,PortraitSnapshot,Supervision
from app.jobs import run_ai
from app.worker import drain
from test_workflow import env,post,submitted


def prepare(env,monkeypatch):
    monkeypatch.setenv('AI_MODE','agent');monkeypatch.setenv('AI_BASE_URL','https://test-agent.invalid')
    monkeypatch.setenv('REVIEW_WORKFLOW','agent')
    return submitted(env)


def report(pack,config,root):
    fid=pack['snapshot']['file_ids'][0]
    def check(rule,conclusion='compliant',evidence=None):
        return dict(rule_id=rule,conclusion=conclusion,severity='info',explanation='fixture',evidence=evidence or [],limitations=[])
    return {'automatic_approval':False,'checks':[check('ATTACHMENT_READABILITY'),check('FORM_COMPLETENESS'),
        check('MATERIAL_EVIDENCE',evidence=[{'file_id':fid,'page_number':1,'paragraph_id':None,'quote':'verified text'}])],
        'blocks':[{'file_id':fid,'page_number':1,'paragraph_id':None,'text':'verified text'}],'limitations':[]}


def test_pass_auto_archives_and_updates_portrait_once(env,monkeypatch):
    app,c,ids=env;ident,fid,draft,result=prepare(env,monkeypatch)
    assert run_ai(app.state.sessions,processor=report)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='approved'
    drain(app.state.sessions);drain(app.state.sessions)
    row=c['student1'].get('/api/v1/submissions/'+ident).json()
    assert row['status']=='archived'
    assert row['decisions'][0]['actor_type']=='agent'
    assert row['decisions'][0]['ai_job_id']==result['ai_job_id']
    portrait=c['student1'].get('/api/v1/students/'+ids['student1']+'/portrait').json()
    assert portrait['records'][0]['facts'][0]['verification']=='agent_approved_submission'
    assert portrait['records'][0]['ai_job_id']==result['ai_job_id']
    assert not run_ai(app.state.sessions,processor=report)
    with app.state.sessions() as s:
        for model in (Decision,Archive,PortraitSnapshot): assert s.scalar(select(func.count()).select_from(model))==1


@pytest.mark.parametrize('case',['uncertain','missing_evidence','limits','failed','empty','all_na'])
def test_exceptions_do_not_archive_and_can_be_handled_by_institution(env,monkeypatch,case):
    app,c,ids=env;ident,_,_,result=prepare(env,monkeypatch)
    def process(pack,config,root):
        r=report(pack,config,root)
        if case=='failed':raise RuntimeError('model unavailable')
        if case=='uncertain':r['checks'][-1]['conclusion']='unable_to_determine'
        if case=='missing_evidence':r['checks'][-1]['evidence']=[]
        if case=='limits':r['limitations']=['truncated document']
        if case=='empty':r['checks']=[]
        if case=='all_na':r['checks'][-1]['conclusion']='not_applicable'
        return r
    run_ai(app.state.sessions,processor=process);drain(app.state.sessions)
    row=c['student1'].get('/api/v1/submissions/'+ident).json()
    if case == 'limits':
        assert row['status'] == 'returned' and not row['effective_archive_id']
        assert c['manager'].get('/api/v1/review-queue').json()[0]['institution_required'] is False
        return
    assert row['status']=='pending_review' and not row['effective_archive_id']
    assert c['manager'].get('/api/v1/review-queue').json()[0]['institution_required']
    response=post(c['manager'],'/api/v1/submissions/'+ident+'/decision',{'expected_lock_version':row['lock_version'],
        'version_id':result['version_id'],'outcome':'returned','opinion':'请补充证据'})
    assert response.status_code==200,response.text


def test_cancelled_response_cannot_approve(env,monkeypatch):
    app,c,ids=env;ident,_,_,result=prepare(env,monkeypatch)
    def process(pack,config,root):
        assert post(c['student1'],'/api/v1/ai-jobs/'+result['ai_job_id']+'/cancel',{}).status_code==200
        return report(pack,config,root)
    run_ai(app.state.sessions,processor=process);drain(app.state.sessions)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='pending_review'
    with app.state.sessions() as s: assert s.scalar(select(func.count()).select_from(Decision))==0


def test_superseded_job_cannot_approve(env,monkeypatch):
    app,c,ids=env;ident,_,_,result=prepare(env,monkeypatch)
    def process(pack,config,root):
        assert post(c['teacher'],'/api/v1/submissions/'+ident+'/ai-jobs',{'version_id':result['version_id']}).status_code==202
        return report(pack,config,root)
    run_ai(app.state.sessions,processor=process)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='pending_review'
    run_ai(app.state.sessions,processor=report);drain(app.state.sessions)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='archived'


def test_revoked_authorization_transfers_to_institution(env,monkeypatch):
    app,c,ids=env;ident,_,_,result=prepare(env,monkeypatch)
    with app.state.sessions.begin() as s:
        rel=s.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        rel.valid_to='2000-01-01T00:00:00+00:00'
    run_ai(app.state.sessions,processor=report)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='pending_review'
    assert c['manager'].get('/api/v1/review-queue').json()[0]['institution_required']


def test_obsolete_version_cannot_approve_current_submission(env,monkeypatch):
    from app.db import Version,uid
    app,c,ids=env;ident,_,_,result=prepare(env,monkeypatch)
    with app.state.sessions.begin() as s:
        old=s.get(Version,result['version_id'])
        newer=Version(id=uid(),submission_id=ident,number=2,snapshot=old.snapshot)
        s.add(newer);s.flush()
        sub=s.get(Submission,ident);sub.current_version_id=newer.id;sub.lock_version+=1
    run_ai(app.state.sessions,processor=report);drain(app.state.sessions)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='pending_review'
    with app.state.sessions() as s:assert s.scalar(select(func.count()).select_from(Decision))==0


def test_decision_failure_rolls_back_job_completion(env,monkeypatch):
    from app import auto_review
    app,c,ids=env;ident,_,_,result=prepare(env,monkeypatch)
    original=auto_review.apply_auto_decision
    def broken(session,job):
        original(session,job)
        raise RuntimeError('simulated commit path failure')
    monkeypatch.setattr(auto_review,'apply_auto_decision',broken)
    with pytest.raises(RuntimeError):run_ai(app.state.sessions,processor=report)
    with app.state.sessions.begin() as s:
        job=s.get(AIJob,result['ai_job_id'])
        assert job.status=='running' and job.result is None
        assert s.get(Submission,ident).status=='pending_review'
        assert s.scalar(select(func.count()).select_from(Decision))==0
        job.lease_until='2000-01-01T00:00:00+00:00'
    monkeypatch.setattr(auto_review,'apply_auto_decision',original)
    run_ai(app.state.sessions,processor=report);drain(app.state.sessions)
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='archived'
