import json
import hashlib
from datetime import date,datetime,timezone
from sqlalchemy import select,func
from app.seed_scenarios import seed_scenarios,STUDENTS,ident
from app.db import User,Submission,File,Archive,GrowthEntry,WarningAction,StudentProfile
from app.growth import dashboard_data,warnings_for
from app.main import verify
from test_workflow import env


def test_seeded_cohort_is_complete_scoped_and_idempotent(env,tmp_path):
    app,c,ids=env;root=app.state.test_file_root;bundle=tmp_path/'cohort'
    before=c['student1'].get('/api/v1/submissions').json()
    result=seed_scenarios(app.state.sessions,root,bundle,date(2026,11,2))
    assert result['students']==12 and result['files']>=35
    accounts=json.loads((bundle/'accounts.json').read_text())
    assert (bundle/'accounts.json').stat().st_mode&0o777==0o600
    with app.state.sessions() as s:
        profiles=s.scalars(select(StudentProfile).where(StudentProfile.user_id.in_([ident(f's{i+1:02}') for i in range(12)]))).all()
        assert sum(p.degree=='博士' for p in profiles)==6
        assert sum(p.degree=='硕士' for p in profiles)==6
        assert all(p.major==('智能教育' if p.degree=='博士' else '人工智能') for p in profiles)
        manager=s.get(User,ids['manager']);student=s.get(User,ident('s01'))
        assert verify(accounts[0]['password'],student.password_hash)
        overview=dashboard_data(s,manager,student.id)
        assert overview['coverage']==6 and overview['counts']['archives']>=3
        filtered=dashboard_data(s,manager,student.id,'2026—2027')
        assert filtered['counts']['materials']>=filtered['counts']['archives']
        assert len(overview['trend'])>=3
        warnings=warnings_for(s,manager,datetime(2026,11,2,4,tzinfo=timezone.utc))
        assert {'overdue','due_soon','returned','agent_exception','goal_overdue'} <= {w['kind'] for w in warnings}
        assert {'open','tracking','dismissed','cleared'} <= {w['status'] for w in warnings}
        for file in s.scalars(select(File).where(File.owner_id.in_([ident(f's{i+1:02}') for i in range(12)]))):
            assert hashlib.sha256((root/file.storage_key).read_bytes()).hexdigest()==file.sha256
        hashes={u.username:u.password_hash for u in s.scalars(select(User))}
        archive_count=s.scalar(select(func.count()).select_from(Archive))
    assert seed_scenarios(app.state.sessions,root,bundle,date(2026,11,2))['status']=='already_loaded'
    with app.state.sessions() as s:
        assert hashes=={u.username:u.password_hash for u in s.scalars(select(User))}
        assert s.scalar(select(func.count()).select_from(Archive))==archive_count
    assert c['student1'].get('/api/v1/submissions').json()==before
    from fastapi.testclient import TestClient
    new_client=TestClient(app)
    response=new_client.post('/api/v1/auth/login',json={'username':accounts[0]['username'],'password':accounts[0]['password']})
    assert response.status_code==200
    assert len(new_client.get('/api/v1/students').json())==1
    assert new_client.get('/api/v1/students/'+ident('s02')+'/growth').status_code==404
    assert new_client.get('/api/v1/students/'+ident('s01')+'/growth').json()['coverage']==6


def test_seed_failure_rolls_back_database_and_files(env,tmp_path,monkeypatch):
    from app import seed_scenarios as mod
    app,c,ids=env;root=app.state.test_file_root;bundle=tmp_path/'failed'
    def broken(*args):raise RuntimeError('fixture failure')
    monkeypatch.setattr(mod,'ensure_snapshot',broken)
    import pytest
    with pytest.raises(RuntimeError):mod.seed_scenarios(app.state.sessions,root,bundle,date(2026,11,2))
    with app.state.sessions() as s:
        assert s.get(User,ident('s01')) is None
        assert s.scalar(select(func.count()).select_from(Submission))==0
    assert not bundle.exists() and list(root.iterdir())==[]
