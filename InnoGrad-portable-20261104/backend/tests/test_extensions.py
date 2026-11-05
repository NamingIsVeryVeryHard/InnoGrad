import io
import json
import zipfile
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from test_workflow import env, submitted, post, paper
from app.db import (AIJob, Archive, Correction, Submission, Supervision, User,
                    ExportJob, now)
from app.main import password_hash
from app.worker import drain
from app.jobs import process_exports, run_ai
from app.agent import Check, Evidence, validate_evidence, analyze
import pytest


def archive(env):
    ident,fid,draft,result=submitted(env)
    app,c,ids=env
    r=post(c['teacher'],f'/api/v1/submissions/{ident}/decision',{
        'expected_lock_version':2,'version_id':result['version_id'],'outcome':'approved','opinion':'材料完整'})
    assert r.status_code==200,r.text
    drain(app.state.sessions)
    detail=c['student1'].get(f'/api/v1/submissions/{ident}').json()
    return ident,fid,detail


def test_correction_approve_return_and_new_archive(env):
    app,c,ids=env; ident,fid,original=archive(env);url=f'/api/v1/submissions/{ident}'
    old_archive=original['effective_archive_id']
    correction=post(c['student1'],url+'/corrections',{'expected_lock_version':original['lock_version'],'reason':'题目信息纠正'}).json()
    assert c['student1'].get(url).json()['effective_archive_id']==old_archive
    assert post(c['teacher'],'/api/v1/corrections/'+correction['id']+'/handle',{'expected_lock_version':correction['lock_version'],'outcome':'approve','opinion':'同意'}).status_code==403
    handled=post(c['manager'],'/api/v1/corrections/'+correction['id']+'/handle',{'expected_lock_version':correction['lock_version'],'outcome':'approve','opinion':'请提交准确题目'})
    assert handled.status_code==200,handled.text
    opened=c['student1'].get(url).json()
    assert opened['status']=='returned' and opened['effective_archive_id']==old_archive
    draft=opened['draft'];draft['form']['title']='纠正后的题目'
    assert c['student1'].patch(url+'/draft',json={**draft,'expected_lock_version':opened['lock_version']}).status_code==200
    second=post(c['student1'],url+'/submit',{'expected_lock_version':opened['lock_version']+1}).json()
    # Return again: the already effective original archive remains visible.
    assert post(c['teacher'],url+'/decision',{'expected_lock_version':second['lock_version'],'version_id':second['version_id'],'outcome':'returned','opinion':'继续补充'}).status_code==200
    assert c['student1'].get(url).json()['effective_archive_id']==old_archive
    current=c['student1'].get(url).json()
    third=post(c['student1'],url+'/submit',{'expected_lock_version':current['lock_version']}).json()
    assert post(c['teacher'],url+'/decision',{'expected_lock_version':third['lock_version'],'version_id':third['version_id'],'outcome':'approved','opinion':'更正通过'}).status_code==200
    drain(app.state.sessions)
    final=c['student1'].get(url).json()
    assert final['effective_archive_id']!=old_archive
    assert final['corrections'][0]['status']=='completed'
    assert final['versions'][0]['snapshot']['form']['title']=='测试论文'


def test_correction_reject_and_paper_progress(env):
    app,c,ids=env; ident,_,detail=archive(env);url=f'/api/v1/submissions/{ident}'
    req=post(c['student1'],url+'/corrections',{'expected_lock_version':detail['lock_version'],'reason':'更正原因'}).json()
    assert post(c['student1'],url+'/corrections',{'expected_lock_version':req['lock_version'],'reason':'重复'}).status_code==409
    handled=post(c['manager'],'/api/v1/corrections/'+req['id']+'/handle',{'expected_lock_version':req['lock_version'],'outcome':'reject','opinion':'无需更正'}).json()
    unchanged=c['student1'].get(url).json()
    assert unchanged['status']=='archived' and unchanged['effective_archive_id']==detail['effective_archive_id']
    update=post(c['student1'],url+'/updates',{'expected_lock_version':handled['lock_version'],'reason':'论文已发表'})
    assert update.status_code==200
    assert c['student1'].get(url).json()['effective_archive_id']==detail['effective_archive_id']


def test_reassign_rejects_previous_reviewer(env):
    app,c,ids=env;ident,_,_,result=submitted(env)
    with app.state.sessions.begin() as s:
        user=User(username='teacher2',name='第二位教师',role='teacher',password_hash=password_hash('test-password'))
        s.add(user);s.flush();tid=user.id
        s.add(Supervision(student_id=ids['student1'],teacher_id=tid,valid_from=now()))
    r=post(c['manager'],f'/api/v1/submissions/{ident}/reviewer',{'expected_lock_version':2,'reviewer_id':tid,'reason':'责任调整'})
    assert r.status_code==200,r.text
    assert post(c['teacher'],f'/api/v1/submissions/{ident}/decision',{'expected_lock_version':r.json()['lock_version'],'version_id':result['version_id'],'outcome':'approved','opinion':'旧分配已失效'}).status_code==403
    assert c['manager'].get(f'/api/v1/submissions/{ident}').json()['reviewer_changes'][0]['reason']=='责任调整'
    from fastapi.testclient import TestClient
    teacher=TestClient(app)
    login=teacher.post('/api/v1/auth/login',json={'username':'teacher2','password':'test-password'})
    teacher.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert post(teacher,f'/api/v1/submissions/{ident}/decision',{'expected_lock_version':r.json()['lock_version'],'version_id':result['version_id'],'outcome':'approved','opinion':'新复核人处理'}).status_code==200


def test_export_checks_request_execution_and_download(env):
    app,c,ids=env;ident,_,detail=archive(env)
    assert post(c['student2'],'/api/v1/exports',{'submission_ids':[ident]}).status_code==404
    job=post(c['teacher'],'/api/v1/exports',{'submission_ids':[ident]}).json()
    assert c['teacher'].get('/api/v1/exports/'+job['id']+'/download').status_code==409
    process_exports(app.state.sessions)
    data=c['teacher'].get('/api/v1/exports/'+job['id']+'/download')
    assert data.status_code==200
    assert data.json()['records'][0]['archive_id']==detail['effective_archive_id']
    assert c['student1'].get('/api/v1/exports/'+job['id']+'/download').status_code==404
    with app.state.sessions.begin() as s:
        rel=s.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        rel.valid_to='2000-01-01T00:00:00+00:00'
    assert c['teacher'].get('/api/v1/exports/'+job['id']+'/download').status_code==404


def test_export_revoked_before_processing(env):
    app,c,ids=env;ident,_,_=archive(env)
    job=post(c['teacher'],'/api/v1/exports',{'submission_ids':[ident]}).json()
    with app.state.sessions.begin() as s:
        rel=s.scalar(select(Supervision).where(Supervision.teacher_id==ids['teacher'],Supervision.student_id==ids['student1']))
        rel.valid_to='2000-01-01T00:00:00+00:00'
    process_exports(app.state.sessions)
    with app.state.sessions() as s:
        row=s.get(ExportJob,job['id']);assert row.status=='cancelled' and row.result is None


def test_ai_auto_rules_no_approval_and_history(env,tmp_path):
    app,c,ids=env;ident,_,_,result=submitted(env)
    job=result['ai_job_id']
    assert run_ai(app.state.sessions,tmp_path/'files')
    data=c['teacher'].get('/api/v1/ai-jobs/'+job).json()
    assert data['status']=='succeeded' and data['result']['mode']=='rules'
    assert data['result']['automatic_approval'] is False
    assert data['result']['checks'][1]['conclusion']=='unable_to_determine'
    assert c['student1'].get(f'/api/v1/submissions/{ident}').json()['status']=='pending_review'
    post(c['teacher'],f'/api/v1/submissions/{ident}/decision',{'expected_lock_version':2,'version_id':result['version_id'],'outcome':'returned','opinion':'人工补正'})
    assert c['teacher'].get('/api/v1/ai-jobs/'+job).json()['historical_only']
    assert c['student2'].get('/api/v1/ai-jobs/'+job).status_code==404


def test_cancelled_ai_rejects_late_result(env,tmp_path):
    app,c,ids=env;ident,_,_,result=submitted(env);jid=result['ai_job_id']
    def processor(pack,config,root):
        assert post(c['student1'],'/api/v1/ai-jobs/'+jid+'/cancel',{}).status_code==200
        return {'checks':[],'automatic_approval':False}
    assert run_ai(app.state.sessions,tmp_path/'files',processor)
    data=c['student1'].get('/api/v1/ai-jobs/'+jid).json()
    assert data['status']=='cancelled' and data['result'] is None


def test_ai_failure_keeps_manual_available(env,tmp_path):
    app,c,ids=env;ident,_,_,result=submitted(env)
    def broken(*args):raise RuntimeError('sensitive provider response')
    run_ai(app.state.sessions,tmp_path/'files',broken)
    status=c['student1'].get('/api/v1/ai-jobs/'+result['ai_job_id']).json()
    assert status['status']=='failed' and 'sensitive' not in status['error']
    assert post(c['teacher'],f'/api/v1/submissions/{ident}/decision',{'expected_lock_version':2,'version_id':result['version_id'],'outcome':'approved','opinion':'人工审核'}).status_code==200


def test_docx_native_parse_and_evidence_validation(env,tmp_path):
    app,c,ids=env;ident,_,draft=paper(env)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>论文已录用</w:t></w:r></w:p></w:body></w:document>')
    fid=c['student1'].post(f'/api/v1/submissions/{ident}/files',files={'file':('proof.docx',buf.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}).json()['id']
    draft['file_ids']=[fid];draft['expected_lock_version']=1
    c['student1'].patch(f'/api/v1/submissions/{ident}/draft',json=draft)
    result=post(c['student1'],f'/api/v1/submissions/{ident}/submit',{'expected_lock_version':2}).json()
    run_ai(app.state.sessions,tmp_path/'files')
    parsed=c['student1'].get('/api/v1/ai-jobs/'+result['ai_job_id']).json()['result']
    block=parsed['blocks'][0]
    assert block['paragraph_id']=='p-1' and block['text']=='论文已录用'
    valid=Check(rule_id='state',conclusion='compliant',severity='info',explanation='可定位',evidence=[Evidence(file_id=fid,paragraph_id='p-1',quote='已录用')])
    validate_evidence([valid],parsed['blocks'])
    invalid=valid.model_copy(update={'evidence':[Evidence(file_id='outside',paragraph_id='p-1',quote='已录用')]})
    with pytest.raises(ValueError):validate_evidence([invalid],parsed['blocks'])


def test_expired_export_not_downloadable(env):
    app,c,ids=env;ident,_,_=archive(env)
    job=post(c['student1'],'/api/v1/exports',{'submission_ids':[ident]}).json()
    process_exports(app.state.sessions)
    with app.state.sessions.begin() as s:s.get(ExportJob,job['id']).expires_at='2000-01-01T00:00:00+00:00'
    assert c['student1'].get('/api/v1/exports/'+job['id']+'/download').status_code==410


def test_local_backup_restore_checks_database_and_files(env,tmp_path):
    from app.backup import backup,restore
    archive(env)
    bundle=tmp_path/'bundle';target=tmp_path/'restored'
    report=backup(tmp_path/'test.db',tmp_path/'files',bundle)
    assert report['archives']==1 and report['files']==1
    assert restore(bundle,target)==report
    with pytest.raises(ValueError):restore(bundle,target)
    first=next((bundle/'files').iterdir());first.write_bytes(b'corrupted')
    with pytest.raises(ValueError):restore(bundle,tmp_path/'bad-restore')


def test_model_adapter_contract_and_invalid_evidence(monkeypatch):
    from app.agent import invoke_model
    import httpx
    captured={}
    output={'checks':[{'rule_id':'PAPER_SEMANTIC','conclusion':'compliant','severity':'info',
        'explanation':'录用证明包含对应文字','evidence':[{'file_id':'f1','page_number':1,'quote':'已录用'}]}]}
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json,headers):
            captured.update(url=url,body=json)
            return httpx.Response(200,json={'choices':[{'message':{'content':__import__('json').dumps(output)}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr('app.agent.httpx.Client',Client)
    payload={'version_id':'v1','form':{'title':'测试'},'blocks':[{'file_id':'f1','page_number':1,'paragraph_id':None,'text':'论文已录用'}]}
    result=invoke_model({'mode':'chat','base_url':'http://127.0.0.1:9000/v1','model':'school-model'},payload)
    assert result[0]['evidence'][0]['file_id']=='f1'
    assert captured['url'].endswith('/v1/chat/completions')
    assert 'storage_key' not in str(captured['body'])
    output['checks'][0]['evidence'][0]['file_id']='unauthorized-file'
    with pytest.raises(ValueError):invoke_model({'mode':'chat','base_url':'http://127.0.0.1:9000/v1','model':'school-model'},payload)


def test_expired_ai_lease_recovers(env,tmp_path):
    app,c,ids=env;ident,_,_,result=submitted(env)
    with app.state.sessions.begin() as s:
        job=s.get(AIJob,result['ai_job_id'])
        job.status='running';job.attempts=1;job.lease_until='2000-01-01T00:00:00+00:00';job.execution_token='expired-worker'
    assert run_ai(app.state.sessions,tmp_path/'files')
    status=c['student1'].get('/api/v1/ai-jobs/'+result['ai_job_id']).json()
    assert status['status']=='succeeded' and status['attempts']==2


def test_ai_after_resubmission_is_historical(env,tmp_path):
    app,c,ids=env;ident,_,_,result=submitted(env)
    post(c['teacher'],f'/api/v1/submissions/{ident}/decision',{'expected_lock_version':2,'version_id':result['version_id'],'outcome':'returned','opinion':'补正'})
    second=post(c['student1'],f'/api/v1/submissions/{ident}/submit',{'expected_lock_version':3}).json()
    assert run_ai(app.state.sessions,tmp_path/'files')
    original=c['student1'].get('/api/v1/ai-jobs/'+result['ai_job_id']).json()
    current=c['student1'].get(f'/api/v1/submissions/{ident}').json()
    assert original['historical_only'] and current['current_version_id']==second['version_id']
    assert current['status']=='pending_review'
