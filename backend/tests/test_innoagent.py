import io
import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace
import httpx
import pytest
from app.agent import AgentResult, analyze
from app.adapters.innoagent import InnoAgentAdapter
from app.auto_review import assess
from app.db import AIJob
from app.material_rules import SKILL_ROOT, freeze_requirements
from app.review_errors import ReviewFailure
from test_workflow import env, post


def docx(text):
    from xml.sax.saxutils import escape
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("[Content_Types].xml", "<Types/>")
        out.writestr("word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:body></w:document>')
    return buffer.getvalue()


def setup_paper(env, monkeypatch, missing=False):
    monkeypatch.setenv("AI_MODE", "innoagent")
    monkeypatch.setenv("AI_BASE_URL", "http://127.0.0.1:3107")
    monkeypatch.setenv("REVIEW_WORKFLOW", "agent")
    app, clients, ids = env
    client = clients["student1"]
    ident = post(client, "/api/v1/submissions", {"kind":"paper","reviewer_id":ids["teacher"]}).json()["id"]
    roles = ["paper_fulltext"] if missing else ["paper_fulltext", "acceptance_notice"]
    files = {}
    for role in roles:
        r = client.post(f"/api/v1/submissions/{ident}/files",
                        files={"file":(role+".docx", docx("研究论文 已录用 2026-10-20"), "application/octet-stream")})
        assert r.status_code == 201
        files[r.json()["id"]] = role
    draft = {"expected_lock_version":0,
             "form":{"title":"研究论文","contribution":"实验设计","publication_status":"accepted",
                     "acceptance_date":"2026-10-20","journal":"测试期刊"},
             "file_ids":list(files),"file_roles":files}
    assert client.patch(f"/api/v1/submissions/{ident}/draft",json=draft).status_code == 200
    job = post(client,f"/api/v1/submissions/{ident}/submit",{"expected_lock_version":1}).json()
    return ident, job, draft


def semantic_result(payload):
    checks = []
    for rule in payload["requirements"]["review_rules"]:
        fid = next(f["id"] for f in payload["files"] if f["role"] in rule["evidence_roles"])
        block = next(b for b in payload["blocks"] if b["file_id"] == fid)
        checks.append(dict(rule_id=rule["id"],conclusion="compliant",severity="info",
            explanation="证明一致",evidence=[{k:block[k] for k in ("file_id","page_number","paragraph_id")} | {"quote":block["text"]}],
            suggestion="",limitations=[]))
    return {"checks":checks}


def fake_review(self, payload, schema):
    assert "storage_key" not in json.dumps(payload)
    assert payload["student"]["name"] and payload["references"] == []
    assert payload["input_hash"]
    return semantic_result(payload), {"agent_session_id":"isolated","cleanup_status":"deleted","skill_version":"material-review-2"}


def test_real_analysis_routes_to_archive(env, monkeypatch):
    from app.jobs import run_ai
    from app.worker import drain
    app, clients, _ = env
    ident, job, _ = setup_paper(env, monkeypatch)
    monkeypatch.setattr(InnoAgentAdapter, "review", fake_review)
    run_ai(app.state.sessions, app.state.test_file_root)
    drain(app.state.sessions)
    result = clients["student1"].get("/api/v1/submissions/"+ident).json()
    assert result["status"] == "archived"
    assert result["decisions"][0]["ai_job_id"] == job["ai_job_id"]


def test_missing_notice_returns_and_resubmit_uses_new_version(env, monkeypatch):
    from app.jobs import run_ai
    app, clients, _ = env
    ident, job, draft = setup_paper(env, monkeypatch, missing=True)
    run_ai(app.state.sessions, app.state.test_file_root)
    client = clients["student1"]
    row = client.get("/api/v1/submissions/"+ident).json()
    assert row["status"] == "returned" and not row["effective_archive_id"]
    assert row["decisions"][0]["outcome"] == "returned"
    uploaded = client.post(f"/api/v1/submissions/{ident}/files",
        files={"file":("notice.docx",docx("已录用 2026-10-20"),"application/octet-stream")}).json()
    draft["file_ids"].append(uploaded["id"]); draft["file_roles"][uploaded["id"]] = "acceptance_notice"
    draft["expected_lock_version"] = row["lock_version"]
    saved = client.patch(f"/api/v1/submissions/{ident}/draft",json=draft).json()
    newer = post(client,f"/api/v1/submissions/{ident}/submit",{"expected_lock_version":saved["lock_version"]}).json()
    assert newer["number"] == 2 and newer["version_id"] != job["version_id"]


def test_all_not_applicable_is_rejected(env, monkeypatch):
    app, _, _ = env
    _, job, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as s:
        row = s.get(AIJob,job["ai_job_id"])
        pack,config = row.input_pack,row.config
    def wrong(self, payload, schema):
        result, metadata = fake_review(self,payload,schema)
        for c in result["checks"]:
            c.update(conclusion="not_applicable",evidence=[])
        return result, metadata
    monkeypatch.setattr(InnoAgentAdapter,"review",wrong)
    with pytest.raises(ReviewFailure,match="RULE_INCOMPLETE"):
        analyze(pack,config,app.state.test_file_root)


def test_adapter_uses_actual_protocol_and_cleans_workspace(monkeypatch):
    captured = {}
    content = (SKILL_ROOT/"SKILL.md").read_text()
    original_client = httpx.Client
    def handle(request):
        path = request.url.path
        if path == "/api/health": data = {"status":"ok"}
        elif path == "/api/skills": data = [{"name":"material-review"}]
        elif path.endswith("/file"): data = {"content":content}
        elif path == "/api/sessions":
            captured["new"] = json.loads(request.content); data = {"id":"session","workspaceId":"workspace"}
        elif path == "/api/chat/stream":
            captured["chat"] = json.loads(request.content)
            text = json.dumps({"checks":[]})
            events = [{"event":{"type":"text_delta","delta":text[:6]}},
                      {"event":{"type":"thinking_delta","delta":"ignore"}},
                      {"event":{"type":"text_delta","delta":text[6:]}},
                      {"event":{"type":"done"}}]
            return httpx.Response(200,text="".join("data: "+json.dumps(e)+"\n\n" for e in events))
        elif request.method == "DELETE":
            captured["delete"] = path; data = {"deleted":True}
        else: data = {"messages":[{"role":"assistant","model":"actual-model","provider":"local"}]}
        return httpx.Response(200,json=data)
    monkeypatch.setattr(httpx,"Client",lambda **kwargs: original_client(transport=httpx.MockTransport(handle),**kwargs))
    adapter = InnoAgentAdapter({"base_url":"http://test"})
    result,meta = adapter.review({"version_id":"v","input_hash":"hash"},AgentResult.model_json_schema())
    assert result == {"checks":[]}
    assert captured["new"]["newWorkspace"]["isTemp"] is True
    assert captured["chat"]["sessionId"] == "session"
    assert captured["chat"]["prompt"].startswith("/skill:material-review")
    assert captured["delete"] == "/api/sessions/session"
    assert meta["response_model"] == "actual-model" and meta["cleanup_status"] == "deleted"


def test_truncated_stream_is_invalid():
    with pytest.raises(ReviewFailure,match="OUTPUT_INVALID"):
        InnoAgentAdapter._last_json(['data: {"event":{"type":"text_delta","delta":"{"}}'])
