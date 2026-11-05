import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.innoagent import InnoAgentAdapter
from app.agent import Check, analyze, validate_evidence
from app.auto_review import assess_material
from app.material_rules import freeze_requirements
from app.review_errors import ReviewFailure
from app.review_execution import align_evidence


def block(text, page=1, file_id="report"):
    return {"file_id": file_id, "page_number": page, "paragraph_id": None, "text": text}


def check(quote, page=1, file_id="report", conclusion="compliant"):
    return Check(
        rule_id="ANNUAL_PLAN_PRESENT", conclusion=conclusion, severity="info",
        explanation="核对下一阶段计划",
        evidence=[{"file_id": file_id, "page_number": page, "quote": quote}],
    )


@pytest.mark.parametrize("quote,page,original,actual_page", [
    ("复杂背景 遮挡", 1, "研究复杂背景遮挡", 1),
    ("co -\nregulate", 1, "Students co -regulate their learning.", 1),
    ("下一学年开展验证实验", 28, "下一学年开展验证实验", 30),
])
def test_unambiguous_citations_are_restored_to_exact_source(quote, page, original, actual_page):
    checks = [check(quote, page)]
    blocks = [block(original, actual_page)]
    changes = align_evidence(checks, blocks)
    validate_evidence(checks, blocks)
    assert len(changes) == 1
    assert checks[0].evidence[0].page_number == actual_page
    assert checks[0].evidence[0].quote in original
    assert changes[0]["supplied"]["quote"] == quote


@pytest.mark.parametrize("blocks,quote,page", [
    ([block("进行了实验")], "没有进行实验", 1),
    ([block("采用 方案A")], "采用方案B", 1),
    ([block("A B", 2), block("A\nB", 3)], "AB", 99),
    ([block("A B", 2), block("AB", 3)], "A B", 99),
    ([block("相同引文", 2), block("相同引文", 3)], "相同引文", 99),
    ([block("引用原文", file_id="another-file")], "引用原文", 1),
])
def test_unverifiable_or_ambiguous_evidence_is_still_rejected(blocks, quote, page):
    with pytest.raises(ReviewFailure, match="EVIDENCE_INVALID"):
        align_evidence([check(quote, page)], blocks)


def test_evidence_validator_itself_remains_exact():
    with pytest.raises(ValueError):
        validate_evidence([check("co -\nregulate")], [block("co -regulate")])


@pytest.mark.parametrize("text", [
    '{"checks":[]}',
    '核对完成。\n```json\n{"checks":[]}\n```\n结果见上。',
    '审核结果：{"checks":[]} 已完成。',
])
def test_single_complete_report_is_extracted_from_assistant_text(text):
    events = [
        'data: ' + json.dumps({"event": {"type": "thinking_delta", "delta": '{"checks":[{}]}'}}),
        'data: ' + json.dumps({"event": {"type": "text_delta", "delta": text}}),
    ]
    assert InnoAgentAdapter._last_json(events) == {"checks": []}


@pytest.mark.parametrize("text", [
    '{"checks":[',
    '{"checks":[]} {"checks":[{}]}',
    '{"checks":[]} {"checks":[',
    '{"checks":[],"approval":true}',
    '{"rule_id":"ANNUAL_PLAN_PRESENT"}',
])
def test_parser_rejects_malformed_or_ambiguous_reports(text):
    with pytest.raises(ReviewFailure, match="OUTPUT_INVALID"):
        InnoAgentAdapter._report(text)


def test_permission_event_does_not_wait_for_stream_completion(monkeypatch):
    class InterruptedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield 'data: {"event":{"type":"permission_request"}}'
            pytest.fail("headless review must stop before waiting for another event")

    class Client(InterruptedResponse):
        def stream(self, *args, **kwargs):
            return InterruptedResponse()

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: Client())
    with pytest.raises(ReviewFailure, match="INTERACTION_REQUIRED"):
        InnoAgentAdapter({"base_url": "http://local"})._stream({})


def package_with_pages(count=7):
    requirements = freeze_requirements("annual", {"review_rules": [
        {"id": "ANNUAL_PLAN_PRESENT", "evidence_roles": ["annual_report"],
         "instruction": "定位下一学年计划；缺少证据时无法判断。"}
    ]})
    return {
        "schema_version": "1.0", "version_id": "v", "kind": "annual",
        "student": {"name": "测试学生"}, "form": {"summary": "本学年总结"},
        "attachments": [{
            "file_id": "report", "name": "report.pdf", "role": "annual_report",
            "media_type": "application/pdf", "size": 1, "sha256": "source-hash",
            "content": [
                {"page_number": page, "paragraph_id": None,
                 "text": f"第{page}页 " + "正文" * 4990 + ("下一学年开展验证实验" if page == count else "")}
                for page in range(1, count + 1)
            ],
        }],
        "references": [], "requirements": requirements,
    }



def test_long_material_is_sent_once_without_splitting(monkeypatch):
    package = package_with_pages(23)
    original = deepcopy(package)
    calls = []
    def review(adapter, payload, schema):
        calls.append(payload)
        assert payload["attachments"][0]["content"] == original["attachments"][0]["content"]
        return {"checks": [check("下一学年开展验证实验", 23).model_dump()]}, {
            "agent_session_id": "single-session", "cleanup_status": "deleted",
        }
    monkeypatch.setattr(InnoAgentAdapter, "review", review)
    result = analyze({"review_package": package}, {"mode": "innoagent", "base_url": "http://local"}, "/unused")
    assert len(calls) == 1 and len(result["blocks"]) == 23
    assert not result["limitations"] and package == original


def _make_innoagent_job(kind="annual", overrides=None, references=None, late=False, proof_required=False):
    from types import SimpleNamespace
    req = {"proof_attachments_required": True} if proof_required else {}
    requirements = freeze_requirements(kind, req)
    role = "annual_report" if kind == "annual" else "paper_fulltext"
    snapshot = {
        "kind": kind,
        "form": {"title": "测试标题", "publication_status": "submitted"} if kind == "paper" else {"summary": "年度总结"},
        "requirements": requirements,
        "references": references or [],
        "late": late,
    }
    files = [{"id": "f1", "role": role}]
    blocks = [{"file_id": "f1", "page_number": 1, "paragraph_id": None, "text": "原文内容支持核验"}]
    checks = [
        {"rule_id": "ATTACHMENT_READABILITY", "conclusion": "compliant", "severity": "info", "explanation": "ok", "evidence": [], "limitations": []},
        {"rule_id": "FORM_COMPLETENESS", "conclusion": "compliant", "severity": "info", "explanation": "ok", "evidence": [], "limitations": []},
        {"rule_id": "ATTACHMENT_ROLES", "conclusion": "compliant", "severity": "info", "explanation": "ok", "evidence": [], "limitations": []},
    ]
    overrides = overrides or {}
    for rule in requirements["review_rules"]:
        rid = rule["id"]
        if rid == "ANNUAL_ACHIEVEMENT_REF_CONSISTENCY" and not references:
            default = {"conclusion": "not_applicable", "explanation": "无引用成果", "evidence": []}
        elif rid == "ANNUAL_ATTACHMENT_ROLES" and not proof_required:
            default = {"conclusion": "not_applicable", "explanation": "任务未开启证明附件要求", "evidence": []}
        elif rule.get("not_applicable_when") == "submitted" and kind == "paper":
            default = {"conclusion": "not_applicable", "explanation": "投稿状态不适用", "evidence": []}
        else:
            default = {
                "conclusion": "compliant",
                "explanation": "符合要求",
                "evidence": [{"file_id": "f1", "page_number": 1, "paragraph_id": None, "quote": "原文内容支持核验"}],
            }
        item = {
            "rule_id": rid,
            "severity": "info",
            "suggestion": "",
            "limitations": [],
            **default,
            **overrides.get(rid, {}),
        }
        checks.append(item)
    return SimpleNamespace(
        status="succeeded",
        error_code=None,
        config={"mode": "innoagent"},
        input_pack={"snapshot": snapshot, "files": files},
        result={
            "checks": checks,
            "blocks": blocks,
            "limitations": [],
            "agent": {"agent_session_id": "sess-1", "cleanup_status": "deleted"},
        },
    )


def test_annual_proofs_not_required_and_unverified_refs_auto_pass_with_hints():
    from app.auto_review import material_findings
    job = _make_innoagent_job(
        kind="annual",
        references=[{"id": "ref-1", "recognition": "unverified"}],
        late=True,
        overrides={
            "ANNUAL_DATE_COVERAGE": {
                "conclusion": "unable_to_determine",
                "explanation": "报告日期已脱敏",
                "evidence": [],
                "limitations": ["具体日期脱敏"],
            },
        },
    )
    outcome, reason = assess_material(job)
    corrections, hints = material_findings(job)
    assert outcome == "passed"
    assert not corrections
    assert len(hints) == 3
    assert "提示" in reason


def test_blocking_rule_uncertainty_with_correction_routes_to_student():
    from app.auto_review import material_findings
    job = _make_innoagent_job(
        kind="annual",
        overrides={
            "ANNUAL_PLAN_PRESENT": {
                "conclusion": "unable_to_determine",
                "explanation": "未找到下一阶段计划页",
                "evidence": [],
                "limitations": ["缺少第2页计划栏目"],
                "suggestion": "请补充包含下一阶段计划的完整报告",
            },
        },
    )
    outcome, reason = assess_material(job)
    corrections, _ = material_findings(job)
    assert outcome == "correction"
    assert reason.startswith("FINDING_BLOCKING:")
    assert len(corrections) == 1 and "ANNUAL_PLAN_PRESENT" in corrections[0]


def test_advisory_rule_non_compliant_becomes_hint_without_blocking():
    from app.auto_review import material_findings
    job = _make_innoagent_job(kind="annual")
    job.input_pack["snapshot"]["requirements"]["review_rules"].append({
        "id": "ANNUAL_EVIDENCE_SUFFICIENCY",
        "level": "advisory",
        "evidence_roles": ["annual_report"],
        "instruction": "提示自述成果与独立证明差异",
    })
    from app.material_rules import canonical_hash
    job.input_pack["snapshot"]["requirements"]["rules_hash"] = canonical_hash(
        job.input_pack["snapshot"]["requirements"]["review_rules"]
    )
    job.result["checks"].append({
        "rule_id": "ANNUAL_EVIDENCE_SUFFICIENCY",
        "conclusion": "non_compliant",
        "severity": "suggestion",
        "explanation": "自述3篇会议论文但仅列出2篇标题",
        "evidence": [{"file_id": "f1", "page_number": 1, "paragraph_id": None, "quote": "原文内容支持核验"}],
        "suggestion": "可补充第3篇论文题目",
        "limitations": [],
    })
    outcome, _ = assess_material(job)
    corrections, hints = material_findings(job)
    assert outcome == "passed"
    assert not corrections
    assert len(hints) == 1 and "ANNUAL_EVIDENCE_SUFFICIENCY" in hints[0]
