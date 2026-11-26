"""Unit, API workflow, and MLPS-3 security tests for research project stage forms (Issue #26)."""

from __future__ import annotations

import pytest
from test_workflow import post

from app.achievement_forms import submission_display_title, validate_submission_form
from app.jobs import run_ai
from app.paper_materials import normalize_file_roles
from app.research_project_form import (
    canonicalize_research_project_form,
    missing_research_project_fields,
)
from app.worker import drain


def _minimal_project_form() -> dict:
    return {
        "metadata_version": 1,
        "project_name": "基于多智能体的自适应学习诊断研究",
        "student_role": "core_member",
        "role_description": "负责实验设计与评测基线实现",
        "stage_deliverables": "完成 3 组对照实验与误差分析报告初稿。",
        "completion_date": "2026-11-10",
        "period": "2026—2027学年",
    }


def _project_form_with_artifacts(file_id: str) -> dict:
    return {
        **_minimal_project_form(),
        "linked_artifacts": [
            {
                "artifact_type": "experiment_report",
                "name": "第 1 阶段消融实验报告",
                "file_id": file_id,
                "description": "含对照组指标汇总",
            },
            {
                "artifact_type": "dataset",
                "name": "合成学习行为基准集 v1",
                "url": "https://example.org/datasets/edu-bench-v1",
                "description": "脱敏合成数据",
            },
            {
                "artifact_type": "code",
                "name": "诊断模型训练仓库",
                "url": "https://github.com/example/edu-diag",
            },
            {
                "artifact_type": "prototype",
                "name": "教师端诊断可视化原型",
                "url": "https://example.org/demo/prototype",
            },
        ],
    }


def test_canonicalize_research_project_minimal_and_full():
    minimal = canonicalize_research_project_form(_minimal_project_form())
    assert minimal["title"] == "基于多智能体的自适应学习诊断研究"
    assert minimal["linked_artifacts"] == []
    assert len(minimal["research_project_key"]) == 64

    full = canonicalize_research_project_form(
        _project_form_with_artifacts("f-101"), allowed_file_ids={"f-101"}
    )
    assert len(full["linked_artifacts"]) == 4
    assert full["linked_artifacts"][0]["file_id"] == "f-101"
    assert full["linked_artifacts"][2]["artifact_type"] == "code"


@pytest.mark.parametrize(
    ("overrides", "expected_msg"),
    [
        ({"project_name": ""}, "项目或课题名称"),
        ({"student_role": "boss"}, "学生本人角色"),
        ({"student_role": "other", "role_description": ""}, "其他角色说明"),
        ({"stage_deliverables": "   "}, "本阶段完成的具体事项"),
        ({"completion_date": "2026-13-01"}, "有效日期"),
        ({"completion_date": "2026/11/10"}, "格式无效"),
        ({"metadata_version": 2}, "版本无效"),
        ({"extra_key": "nope"}, "未定义字段"),
        (
            {"linked_artifacts": [{"artifact_type": "paper", "name": "非法类别"}]},
            "关联材料类型",
        ),
        (
            {
                "linked_artifacts": [
                    {
                        "artifact_type": "code",
                        "name": "XSS链接",
                        "url": "javascript:alert(1)",
                    }
                ]
            },
            "http:// 或 https://",
        ),
        (
            {
                "linked_artifacts": [
                    {
                        "artifact_type": "dataset",
                        "name": "凭据链接",
                        "url": "https://user:secret@example.org/data",
                    }
                ]
            },
            "账号或口令凭据",
        ),
        (
            {
                "linked_artifacts": [
                    {"artifact_type": "code", "name": f"repo-{i}"}
                    for i in range(21)
                ]
            },
            "最多关联 20 项",
        ),
    ],
)
def test_research_project_validation_rejects_invalid_and_unsafe_inputs(
    overrides, expected_msg
):
    payload = {**_minimal_project_form(), **overrides}
    with pytest.raises(ValueError, match=expected_msg):
        canonicalize_research_project_form(payload)


def test_research_project_rejects_wrong_types_and_unowned_file_id():
    with pytest.raises(TypeError, match="表单格式无效"):
        canonicalize_research_project_form([])
    with pytest.raises(TypeError, match="列表格式无效"):
        canonicalize_research_project_form(
            {**_minimal_project_form(), "linked_artifacts": "not-a-list"}
        )
    with pytest.raises(TypeError, match="条目格式无效"):
        canonicalize_research_project_form(
            {**_minimal_project_form(), "linked_artifacts": ["bad-item"]}
        )
    with pytest.raises(ValueError, match="本次提交已上传的文件"):
        canonicalize_research_project_form(
            _project_form_with_artifacts("foreign-file-id"),
            allowed_file_ids={"owned-file-id"},
        )
    with pytest.raises(ValueError, match="不支持的材料类型"):
        validate_submission_form("unknown", {}, [])
    with pytest.raises(ValueError, match="只能设置给本次提交"):
        normalize_file_roles(["f1"], {"f2": "other_proof"}, kind="research_project")
    assert submission_display_title("research_project", {}) == "科研项目阶段成果"


def test_missing_research_project_fields_helper():
    assert missing_research_project_fields(_minimal_project_form()) == []
    assert missing_research_project_fields(
        {**_minimal_project_form(), "student_role": "other", "role_description": ""}
    ) == ["role_description"]


def test_research_project_allows_submit_without_attachments_or_artifacts(app_env):
    """Issue #26 explicitly requires linked materials to remain optional."""
    app, c, ids = app_env
    created = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "research_project", "reviewer_id": ids["teacher"]},
    )
    assert created.status_code == 201, created.text
    ident = created.json()["id"]

    saved = c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={"expected_lock_version": 0, "form": _minimal_project_form()},
    )
    assert saved.status_code == 200

    submitted = post(
        c["student1"],
        f"/api/v1/submissions/{ident}/submit",
        {"expected_lock_version": 1},
    )
    assert submitted.status_code == 202, submitted.text
    assert run_ai(app.state.sessions, app.state.test_file_root)
    ai_res = c["teacher"].get(f"/api/v1/ai-jobs/{submitted.json()['ai_job_id']}").json()
    assert ai_res["status"] == "succeeded"
    checks = {chk["rule_id"]: chk["conclusion"] for chk in ai_res["result"]["checks"]}
    assert checks["ATTACHMENT_READABILITY"] == "not_applicable"
    assert checks["FORM_COMPLETENESS"] == "compliant"

    decision = post(
        c["teacher"],
        f"/api/v1/submissions/{ident}/decision",
        {
            "expected_lock_version": 2,
            "version_id": submitted.json()["version_id"],
            "outcome": "approved",
            "opinion": "阶段科研项目事项清晰，确认归档",
        },
    )
    assert decision.status_code == 200
    drain(app.state.sessions)

    portrait = c["teacher"].get(f"/api/v1/students/{ids['student1']}/portrait").json()
    assert portrait["counts"]["research_project_records"] == 1
    growth = c["teacher"].get(f"/api/v1/students/{ids['student1']}/growth").json()
    assert growth["counts"]["research_projects"] == 1
    assert growth["trend"][0]["research_project"] == 1


def test_research_project_with_artifacts_prevents_cross_submission_idor(app_env):
    _app, c, ids = app_env
    other_sub = post(
        c["student2"],
        "/api/v1/submissions",
        {"kind": "research_project", "reviewer_id": ids["teacher"]},
    ).json()["id"]
    foreign_fid = (
        c["student2"]
        .post(
            f"/api/v1/submissions/{other_sub}/files",
            files={"file": ("secret.pdf", b"%PDF-1.7 private", "application/pdf")},
        )
        .json()["id"]
    )

    ident = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "research_project", "reviewer_id": ids["teacher"]},
    ).json()["id"]
    own_fid = (
        c["student1"]
        .post(
            f"/api/v1/submissions/{ident}/files",
            files={"file": ("exp.pdf", b"%PDF-1.7 exp report", "application/pdf")},
        )
        .json()["id"]
    )

    c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={
            "expected_lock_version": 0,
            "form": _project_form_with_artifacts(foreign_fid),
            "file_ids": [own_fid],
            "file_roles": {own_fid: "experiment_report"},
        },
    )
    assert (
        post(
            c["student1"],
            f"/api/v1/submissions/{ident}/submit",
            {"expected_lock_version": 1},
        ).status_code
        == 422
    )

    c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={
            "expected_lock_version": 1,
            "form": _project_form_with_artifacts(own_fid),
            "file_ids": [own_fid],
            "file_roles": {own_fid: "experiment_report"},
        },
    )
    submitted = post(
        c["student1"],
        f"/api/v1/submissions/{ident}/submit",
        {"expected_lock_version": 2},
    )
    assert submitted.status_code == 202, submitted.text
    detail = c["teacher"].get(f"/api/v1/submissions/{ident}").json()
    assert detail["files"][0]["role"] == "experiment_report"
    assert len(detail["versions"][0]["snapshot"]["form"]["linked_artifacts"]) == 4

    task_id = post(
        c["manager"],
        "/api/v1/cultivation-tasks",
        {
            "title": "2026年度报告",
            "period": "2026—2027学年",
            "deadline": "2026-12-31T23:59:59+08:00",
            "reviewer_id": ids["teacher"],
            "student_ids": [ids["student1"]],
        },
    ).json()["id"]
    annual_id = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "annual", "task_id": task_id},
    ).json()["id"]
    ann_fid = (
        c["student1"]
        .post(
            f"/api/v1/submissions/{annual_id}/files",
            files={"file": ("annual.pdf", b"%PDF-1.7 annual", "application/pdf")},
        )
        .json()["id"]
    )
    c["student1"].patch(
        f"/api/v1/submissions/{annual_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": {"summary": "本年度完成了多智能体学习诊断阶段成果"},
            "file_ids": [ann_fid],
            "reference_ids": [ident],
        },
    )
    ann_sub = post(
        c["student1"],
        f"/api/v1/submissions/{annual_id}/submit",
        {"expected_lock_version": 1},
    )
    assert ann_sub.status_code == 202, ann_sub.text
    ann_refs = (
        c["teacher"]
        .get(f"/api/v1/submissions/{annual_id}")
        .json()["versions"][0]["snapshot"]["references"]
    )
    assert ann_refs[0]["kind"] == "research_project"
