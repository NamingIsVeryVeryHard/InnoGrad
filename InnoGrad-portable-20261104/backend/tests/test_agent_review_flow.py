from types import SimpleNamespace
from app.review_flow import material_outcome
from test_workflow import env, post, submitted


def test_material_outcome_distinguishes_rules_uncertainty_and_findings():
    job=SimpleNamespace(error_code=None, agent_metadata={}, config={'mode':'rules'},status='succeeded',result={'checks':[{'conclusion':'compliant'}]})
    assert material_outcome(job)['state']=='not_agent'
    job.config={'mode':'agent'};job.status='failed'
    assert material_outcome(job)['state']=='failed'
    job.status='succeeded';job.result={'checks':[{'conclusion':'unable_to_determine'}]}
    assert material_outcome(job)['state']=='exception'
    job.result={'checks':[{'conclusion':'non_compliant'}]}
    assert material_outcome(job)['state']=='exception'
    job.result={'checks':[{'conclusion':'compliant'}]}
    assert material_outcome(job)['state']=='exception'


def test_agent_workflow_requires_current_agent_report(env,monkeypatch):
    app,c,ids=env
    ident,_,_,version=submitted(env)
    monkeypatch.setenv('REVIEW_WORKFLOW','agent')
    response=post(c['teacher'],'/api/v1/submissions/'+ident+'/decision',{
        'expected_lock_version':2,'version_id':version['version_id'],'outcome':'approved','opinion':'机构确认'})
    assert response.status_code==409
    assert c['student1'].get('/api/v1/submissions/'+ident).json()['status']=='pending_review'


def test_agent_queue_scope_and_pending_configuration(env,monkeypatch):
    app,c,ids=env
    ident,_,_,version=submitted(env)
    rows=c['teacher'].get('/api/v1/review-queue').json()
    assert rows[0]['submission_id']==ident and rows[0]['outcome']['state']=='not_agent'
    assert c['student2'].get('/api/v1/review-queue').json()==[]
    assert c['operator'].get('/api/v1/review-queue').json()==[]
    monkeypatch.setenv('AI_MODE','agent');monkeypatch.setenv('REVIEW_WORKFLOW','agent')
    cap=c['teacher'].get('/api/v1/ai/capabilities').json()
    assert cap['model_configured'] is False and cap['workflow']=='agent'
    assert post(c['teacher'],'/api/v1/submissions/'+ident+'/ai-jobs',{'version_id':version['version_id']}).status_code==422


def test_agent_endpoint_needs_no_chat_model_name(env,monkeypatch):
    monkeypatch.setenv('AI_MODE','agent');monkeypatch.setenv('AI_BASE_URL','https://school-agent.example')
    assert env[1]['teacher'].get('/api/v1/ai/capabilities').json()['model_configured'] is True
