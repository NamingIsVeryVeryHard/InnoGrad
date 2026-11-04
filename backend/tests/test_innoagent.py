import io
import json
import hashlib
import zipfile
from copy import deepcopy
from types import SimpleNamespace
import httpx
import pytest
from app.agent import AgentResult, analyze, review_package_from_pack
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
        attachment = next(f for f in payload["attachments"] if f["role"] in rule["evidence_roles"])
        fid = attachment["file_id"]
        block = next(b | {"file_id": fid} for b in attachment["content"])
        checks.append(dict(rule_id=rule["id"],conclusion="compliant",severity="info",
            explanation="证明一致",evidence=[{k:block[k] for k in ("file_id","page_number","paragraph_id")} | {"quote":block["text"]}],
            suggestion="",limitations=[]))
    return {"checks":checks}


def fake_review(self, payload, schema):
    assert "storage_key" not in json.dumps(payload)
    assert "attachments" in payload and "files" not in payload and "blocks" not in payload
    assert payload["student"]["name"] and payload["references"] == []
    assert "input_hash" not in payload and "output_schema" not in payload
    return semantic_result(payload), {"agent_session_id":"isolated","cleanup_status":"deleted","skill_version":"material-review-3"}


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


def test_analyze_accepts_post_ocr_review_package(env, monkeypatch):
    app, _, _ = env
    _, job, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as session:
        row = session.get(AIJob, job["ai_job_id"])
        original_pack, config = row.input_pack, row.config
    canonical = review_package_from_pack(original_pack, app.state.test_file_root)
    supplied = {
        "review_package": canonical,
    }
    def unexpected_parse(*args):
        pytest.fail("post-OCR input must not read original files")
    monkeypatch.setattr("app.agent.parse_file", unexpected_parse)
    monkeypatch.setattr(InnoAgentAdapter, "review", fake_review)
    result = analyze(supplied, config, "/path/is_not_read")
    assert result["mode"] == "innoagent"
    assert result["blocks"]
    assert result["agent"]["cleanup_status"] == "deleted"


def test_legacy_snapshot_without_kind_defaults_to_annual(env, tmp_path):
    app, _, _ = env
    relative = "legacy.docx"
    (tmp_path / relative).write_bytes(docx("阶段总结与下一阶段计划"))
    package = review_package_from_pack({
        "version_id": "legacy-version",
        "snapshot": {
            "form": {"summary": "阶段总结", "plan": "下一阶段计划"},
            "requirements": {"review_rules": []},
            "references": [],
            "period": "2026—2027",
            "late": False,
        },
        "files": [{
            "id": "legacy-file",
            "name": "legacy.docx",
            "role": "other",
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "sha256": hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest(),
            "storage_key": relative,
        }],
    }, tmp_path)
    assert package["kind"] == "annual"


def test_ai_job_endpoint_accepts_post_ocr_review_package(env, monkeypatch):
    app, clients, _ = env
    ident, initial, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as session:
        row = session.get(AIJob, initial["ai_job_id"])
        canonical = review_package_from_pack(row.input_pack, app.state.test_file_root)
    response = post(
        clients["teacher"],
        f"/api/v1/submissions/{ident}/ai-jobs",
        {"version_id": initial["version_id"], "review_package": canonical},
    )
    assert response.status_code == 202
    with app.state.sessions() as session:
        job = session.get(AIJob, response.json()["id"])
        assert job.input_pack["review_package"]["attachments"]


@pytest.mark.parametrize("field", ["form", "requirements", "student", "attachments", "duplicate"])
def test_supplied_package_preserves_frozen_submission(env, monkeypatch, field):
    app, clients, _ = env
    ident, initial, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as session:
        row = session.get(AIJob, initial["ai_job_id"])
        package = review_package_from_pack(row.input_pack, app.state.test_file_root)
    if field == "attachments":
        package["attachments"][0]["sha256"] = "wrong-file"
    elif field == "duplicate":
        package["attachments"].append(deepcopy(package["attachments"][0]))
    else:
        package[field] = {}
    response = post(clients["teacher"], f"/api/v1/submissions/{ident}/ai-jobs",
                    {"version_id": initial["version_id"], "review_package": package})
    assert response.status_code == 422


def test_student_cannot_inject_ocr_content(env, monkeypatch):
    app, clients, _ = env
    ident, initial, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as session:
        row = session.get(AIJob, initial["ai_job_id"])
        package = review_package_from_pack(row.input_pack, app.state.test_file_root)
    for attachment in package["attachments"]:
        attachment["content"] = [{"page_number": 1, "text": "伪造的合规证据"}]
    response = post(clients["student1"], f"/api/v1/submissions/{ident}/ai-jobs",
                    {"version_id": initial["version_id"], "review_package": package})
    assert response.status_code == 403
    from sqlalchemy import select
    with app.state.sessions() as session:
        jobs = session.scalars(select(AIJob).where(AIJob.submission_id == ident)).all()
        assert len(jobs) == 1
        assert "review_package" not in jobs[0].input_pack
    response = post(clients["student1"], f"/api/v1/submissions/{ident}/ai-jobs",
                    {"version_id": initial["version_id"]})
    assert response.status_code == 202


def test_shared_page_blocks_keep_distinct_text(env, monkeypatch):
    app, _, _ = env
    _, initial, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as session:
        job = session.get(AIJob, initial["ai_job_id"])
        package = review_package_from_pack(job.input_pack, app.state.test_file_root)
        config = job.config
    content = [
        {"page_number": 1, "paragraph_id": None, "text": "第一块"},
        {"page_number": 1, "paragraph_id": None, "text": "第二块"},
    ]
    package["attachments"][0]["content"] = content
    def review(self, payload, schema):
        assert payload["attachments"][0]["content"] == content
        return fake_review(self, payload, schema)
    monkeypatch.setattr(InnoAgentAdapter, "review", review)
    analyze({"review_package": package}, config, "/unused")


def test_empty_upstream_content_requires_manual_review(env, monkeypatch):
    app, _, _ = env
    _, initial, _ = setup_paper(env, monkeypatch)
    with app.state.sessions() as session:
        job = session.get(AIJob, initial["ai_job_id"])
        package = review_package_from_pack(job.input_pack, app.state.test_file_root)
        config = job.config
    package["attachments"][0]["content"] = []
    monkeypatch.setattr(InnoAgentAdapter, "review",
                        lambda *args: pytest.fail("empty OCR content must not reach Agent"))
    result = analyze({"review_package": package}, config, "/unused")
    assert result["checks"][0]["conclusion"] == "unable_to_determine"
    assert result["limitations"]
