"""Unit, API workflow, and MLPS-3 security tests for software copyright submissions (Issue #25)."""

from __future__ import annotations

import pytest
from test_workflow import post

from app.jobs import run_ai
from app.software_copyright_form import (
    canonicalize_software_copyright_form,
    missing_software_copyright_fields,
)
from app.worker import drain


def _valid_registered_form() -> dict:
    return {
        "metadata_version": 1,
        "software_name": "InnoGrad 研究生培养智能审核辅助系统",
        "version": "V1.2.0",
        "copyright_holders": "华东师范大学\n张三，李四",
        "development_work": "负责软件著作权与科研项目表单校验模块设计、后端接口开发与安全测试。",
        "registration_status": "registered",
        "registration_number": "2026SR1234567",
        "registration_date": "2026-10-15",
        "period": "2026—2027学年",
    }


def _valid_unregistered_form() -> dict:
    return {
        "metadata_version": 1,
        "software_name": "智能教育多模态评测工具",
        "version": "V0.9-beta",
        "copyright_holders": ["华东师范大学", "张三", "张三"],
        "development_work": "负责数据清洗管线与指标计算引擎编写。",
        "registration_status": "unregistered",
    }


def test_canonicalize_registered_and_unregistered_software_copyright():
    reg = canonicalize_software_copyright_form(_valid_registered_form())
    assert reg["title"] == "InnoGrad 研究生培养智能审核辅助系统"
    assert reg["copyright_holders"] == ["华东师范大学", "张三", "李四"]
    assert reg["registration_number"] == "2026SR1234567"
    assert reg["registration_date"] == "2026-10-15"
    assert len(reg["software_copyright_key"]) == 64

    cn_reg = canonicalize_software_copyright_form(
        {**_valid_registered_form(), "registration_number": "软著登字第12345678号"}
    )
    assert cn_reg["registration_number"] == "软著登字第12345678号"

    unreg = canonicalize_software_copyright_form(_valid_unregistered_form())
    assert unreg["copyright_holders"] == ["华东师范大学", "张三"]
    assert unreg["registration_number"] == ""
    assert unreg["registration_date"] == ""


@pytest.mark.parametrize(
    ("overrides", "expected_msg"),
    [
        ({"registration_number": ""}, "登记号"),
        ({"registration_date": ""}, "登记日期"),
        ({"registration_date": "2026-02-30"}, "有效日期"),
        ({"registration_date": "1960-01-01"}, "年份超出合理范围"),
        ({"registration_number": "12"}, "登记号格式无效"),
        ({"version": "V1.0 <script>"}, "版本号格式无效"),
        ({"software_name": "   "}, "软件全称"),
        ({"software_name": "bad\x00name"}, "非法控制字符"),
        ({"software_name": "x" * 201}, "不能超过 200"),
        ({"development_work": ""}, "学生承担的开发工作"),
        ({"registration_status": "unknown_state"}, "登记状态"),
        ({"metadata_version": 99}, "版本无效"),
        ({"unexpected_field": "x"}, "未定义字段"),
        ({"copyright_holders": None}, "请填写著作权人"),
        ({"copyright_holders": [f"人{i}" for i in range(51)]}, "著作权人数量"),
        ({"period": "y" * 41}, "不能超过 40"),
    ],
)
def test_software_copyright_validation_rejects_invalid_inputs(overrides, expected_msg):
    payload = {**_valid_registered_form(), **overrides}
    with pytest.raises(ValueError, match=expected_msg):
        canonicalize_software_copyright_form(payload)


def test_software_copyright_rejects_wrong_types():
    with pytest.raises(TypeError, match="表单格式无效"):
        canonicalize_software_copyright_form("not-a-dict")
    with pytest.raises(TypeError, match="著作权人格式无效"):
        canonicalize_software_copyright_form(
            {**_valid_unregistered_form(), "copyright_holders": 12345}
        )
    with pytest.raises(TypeError, match="软件全称格式无效"):
        canonicalize_software_copyright_form(
            {**_valid_unregistered_form(), "software_name": 12345}
        )
    with pytest.raises(TypeError, match="所属学年格式无效"):
        canonicalize_software_copyright_form(
            {**_valid_unregistered_form(), "period": 2026}
        )


@pytest.mark.parametrize("status", ["unregistered", "applying"])
def test_non_registered_software_copyright_rejects_registration_fields(status):
    payload = {
        **_valid_unregistered_form(),
        "registration_status": status,
        "registration_number": "2026SR0000001",
    }
    with pytest.raises(ValueError, match="仅登记状态为已登记"):
        canonicalize_software_copyright_form(payload)

    payload_date = {
        **_valid_unregistered_form(),
        "registration_status": status,
        "registration_date": "2026-10-01",
    }
    with pytest.raises(ValueError, match="仅登记状态为已登记"):
        canonicalize_software_copyright_form(payload_date)


def test_missing_software_copyright_fields_checks_conditional_rules():
    assert (
        missing_software_copyright_fields(
            {
                "software_name": "S",
                "version": "V1.0",
                "copyright_holders": ["A"],
                "development_work": "dev",
                "registration_status": "unregistered",
            }
        )
        == []
    )
    assert set(
        missing_software_copyright_fields(
            {
                "software_name": "",
                "version": "V1.0",
                "copyright_holders": [],
                "development_work": "dev",
                "registration_status": "registered",
            }
        )
    ) == {"software_name", "copyright_holders", "registration_number", "registration_date"}


def test_registered_software_copyright_end_to_end_archive_portrait_and_growth(app_env):
    app, c, ids = app_env
    created = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "software_copyright", "reviewer_id": ids["teacher"]},
    )
    assert created.status_code == 201, created.text
    assert created.headers.get("X-Content-Type-Options") == "nosniff"
    assert created.headers.get("Cache-Control") == "no-store"
    ident = created.json()["id"]

    draft_no_file = c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={"expected_lock_version": 0, "form": _valid_registered_form()},
    )
    assert draft_no_file.status_code == 200
    assert (
        post(
            c["student1"],
            f"/api/v1/submissions/{ident}/submit",
            {"expected_lock_version": 1},
        ).status_code
        == 422
    )

    uploaded = c["student1"].post(
        f"/api/v1/submissions/{ident}/files",
        files={"file": ("cert.pdf", b"%PDF-1.7 synthetic cert", "application/pdf")},
    )
    assert uploaded.status_code == 201
    fid = uploaded.json()["id"]
    bad_role = c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={
            "expected_lock_version": 1,
            "form": _valid_registered_form(),
            "file_ids": [fid],
            "file_roles": {fid: "paper_fulltext"},
        },
    )
    assert bad_role.status_code == 422

    saved = c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={
            "expected_lock_version": 1,
            "form": _valid_registered_form(),
            "file_ids": [fid],
            "file_roles": {fid: "copyright_certificate"},
        },
    )
    assert saved.status_code == 200

    assert c["teacher"].get(f"/api/v1/submissions/{ident}").status_code == 404
    assert c["student2"].get(f"/api/v1/submissions/{ident}").status_code == 404

    submitted = post(
        c["student1"],
        f"/api/v1/submissions/{ident}/submit",
        {"expected_lock_version": 2},
    )
    assert submitted.status_code == 202, submitted.text
    ver_id = submitted.json()["version_id"]
    ai_job_id = submitted.json()["ai_job_id"]

    assert run_ai(app.state.sessions, app.state.test_file_root)
    ai_res = c["teacher"].get(f"/api/v1/ai-jobs/{ai_job_id}").json()
    assert ai_res["status"] == "succeeded"
    completeness = next(
        chk
        for chk in ai_res["result"]["checks"]
        if chk["rule_id"] == "FORM_COMPLETENESS"
    )
    assert completeness["conclusion"] == "compliant"

    for actor in ("student2", "operator"):
        assert c[actor].get(f"/api/v1/submissions/{ident}").status_code == 404
        assert c[actor].get(f"/api/v1/files/{fid}/download").status_code == 404

    decision = post(
        c["teacher"],
        f"/api/v1/submissions/{ident}/decision",
        {
            "expected_lock_version": 3,
            "version_id": ver_id,
            "outcome": "approved",
            "opinion": "软著登记证书与开发工作核对无误",
        },
    )
    assert decision.status_code == 200, decision.text
    drain(app.state.sessions)

    portrait = c["teacher"].get(f"/api/v1/students/{ids['student1']}/portrait").json()
    assert portrait["counts"]["software_copyright_records"] == 1
    assert portrait["records"][0]["kind"] == "software_copyright"

    growth = c["teacher"].get(f"/api/v1/students/{ids['student1']}/growth").json()
    assert growth["counts"]["software_copyrights"] == 1
    assert growth["coverage"] >= 2
    assert growth["trend"][0]["software_copyright"] == 1

    logs = c["student1"].get("/api/v1/audit-logs").json()
    actions = {row["action"] for row in logs}
    assert {"submission.created", "draft.saved", "version.submitted"} <= actions


def test_unregistered_software_copyright_can_submit_without_file_and_upgrade_later(
    app_env,
):
    app, c, ids = app_env
    assert (
        post(
            c["student1"],
            "/api/v1/submissions",
            {
                "kind": "software_copyright",
                "task_id": "t1",
                "reviewer_id": ids["teacher"],
            },
        ).status_code
        == 422
    )
    created = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "software_copyright", "reviewer_id": ids["teacher"]},
    )
    ident = created.json()["id"]
    c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={"expected_lock_version": 0, "form": _valid_unregistered_form()},
    )
    submitted = post(
        c["student1"],
        f"/api/v1/submissions/{ident}/submit",
        {"expected_lock_version": 1},
    )
    assert submitted.status_code == 202, submitted.text
    assert run_ai(app.state.sessions, app.state.test_file_root)
    ai_res = c["teacher"].get(f"/api/v1/ai-jobs/{submitted.json()['ai_job_id']}").json()
    readability = next(
        chk
        for chk in ai_res["result"]["checks"]
        if chk["rule_id"] == "ATTACHMENT_READABILITY"
    )
    assert readability["conclusion"] == "not_applicable"

    post(
        c["teacher"],
        f"/api/v1/submissions/{ident}/decision",
        {
            "expected_lock_version": 2,
            "version_id": submitted.json()["version_id"],
            "outcome": "approved",
            "opinion": "阶段软著开发记录确认通过",
        },
    )
    drain(app.state.sessions)
    archived = c["student1"].get(f"/api/v1/submissions/{ident}").json()
    assert archived["status"] == "archived"

    upd = post(
        c["student1"],
        f"/api/v1/submissions/{ident}/updates",
        {"expected_lock_version": archived["lock_version"], "reason": "已获得软著登记证书"},
    )
    assert upd.status_code == 200, upd.text
    fid = (
        c["student1"]
        .post(
            f"/api/v1/submissions/{ident}/files",
            files={"file": ("cert.pdf", b"%PDF-1.7 cert", "application/pdf")},
        )
        .json()["id"]
    )
    c["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={
            "expected_lock_version": upd.json()["lock_version"],
            "form": _valid_registered_form(),
            "file_ids": [fid],
            "file_roles": {fid: "copyright_certificate"},
        },
    )
    resub = post(
        c["student1"],
        f"/api/v1/submissions/{ident}/submit",
        {"expected_lock_version": upd.json()["lock_version"] + 1},
    )
    assert resub.status_code == 202
    assert resub.json()["number"] == 2
