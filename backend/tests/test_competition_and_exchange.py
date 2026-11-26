from pathlib import Path
import json
from sqlalchemy import select
import pytest

from app.achievement_forms import (
    canonicalize_competition_form,
    canonicalize_exchange_form,
)
from app.agent import analyze, invoke_model
from app.auto_review import assess
from app.db import Supervision
from app.jobs import run_ai
from app.worker import drain
from test_workflow import env, post


def _upload_pdf(client, sub_id, name="proof.pdf"):
    resp = client.post(
        f"/api/v1/submissions/{sub_id}/files",
        files={"file": (name, b"%PDF-1.7 synthetic proof", "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _valid_competition_form(**overrides):
    data = {
        "competition_name": "全国研究生数学建模竞赛",
        "organizer": "中国学位与研究生教育学会",
        "award_level": "国家级一等奖",
        "award_date": "2026-10-15",
        "team_members": "张三\n李四",
        "my_role": "队长，负责建模与实验设计",
        "publicity_url": "https://example.org/awards/2026",
        "description": "完成竞赛模型构建与论文撰写",
    }
    data.update(overrides)
    return data


def _valid_exchange_form(mode="attend", **overrides):
    data = {
        "activity_name": "智能教育青年学者论坛",
        "activity_date": "2026-11-10",
        "end_date": "2026-11-12",
        "participation_mode": mode,
        "location_or_organizer": "上海",
        "participation_summary": "全程参与并交流研究方法",
        "reference_url": "https://example.org/forum/2026",
    }
    if mode in ("talk", "poster"):
        data["presentation_title"] = "可追溯研究生成长画像研究"
    if mode == "practice_task":
        data["practice_task_description"] = "负责智能教育试点平台数据清洗与接口验证"
    data.update(overrides)
    return data


def test_canonicalize_competition_form_unit():
    parsed = canonicalize_competition_form(_valid_competition_form())
    assert parsed["competition_metadata_version"] == 1
    assert parsed["title"] == "全国研究生数学建模竞赛"
    assert parsed["team_members"] == [
        {"name": "张三", "order": 1},
        {"name": "李四", "order": 2},
    ]
    assert len(parsed["competition_key"]) == 64

    structured = canonicalize_competition_form(
        _valid_competition_form(
            team_members=[
                {"name": "王五", "order": 2},
                {"name": "赵六", "order": 1},
            ]
        )
    )
    assert structured["team_members"] == [
        {"name": "赵六", "order": 1},
        {"name": "王五", "order": 2},
    ]

    with pytest.raises(ValueError, match="公示链接"):
        canonicalize_competition_form(
            _valid_competition_form(publicity_url="ftp://example.org/bad")
        )
    with pytest.raises(ValueError, match="奖项"):
        canonicalize_competition_form(_valid_competition_form(award_level=""))
    with pytest.raises(ValueError, match="获奖日期"):
        canonicalize_competition_form(_valid_competition_form(award_date="2026/10/15"))
    with pytest.raises(ValueError, match="团队成员顺序"):
        canonicalize_competition_form(
            _valid_competition_form(
                team_members=[
                    {"name": "张三", "order": 1},
                    {"name": "李四", "order": 1},
                ]
            )
        )


def test_canonicalize_exchange_form_unit():
    for mode, label in (
        ("attend", "参会"),
        ("talk", "作报告"),
        ("poster", "展示海报"),
        ("practice_task", "承担具体实践任务"),
    ):
        parsed = canonicalize_exchange_form(_valid_exchange_form(mode))
        assert parsed["exchange_metadata_version"] == 1
        assert parsed["participation_mode"] == mode
        assert parsed["participation_mode_label"] == label
        assert len(parsed["exchange_key"]) == 64

    with pytest.raises(ValueError, match="报告题目"):
        canonicalize_exchange_form(
            _valid_exchange_form("talk", presentation_title="")
        )
    with pytest.raises(ValueError, match="海报题目"):
        canonicalize_exchange_form(
            _valid_exchange_form("poster", presentation_title="")
        )
    with pytest.raises(ValueError, match="承担的具体实践任务"):
        canonicalize_exchange_form(
            _valid_exchange_form("practice_task", practice_task_description="")
        )
    with pytest.raises(ValueError, match="结束日期"):
        canonicalize_exchange_form(
            _valid_exchange_form("attend", end_date="2026-11-01")
        )
    with pytest.raises(ValueError, match="参与方式"):
        canonicalize_exchange_form(_valid_exchange_form("keynote"))
    with pytest.raises(ValueError, match="活动链接"):
        canonicalize_exchange_form(
            _valid_exchange_form("attend", reference_url="not-a-url")
        )


def test_competition_certificate_and_publicity_link_workflow(env):
    app, c, ids = env

    # 1. Certificate-only competition archives cleanly and feeds portrait + growth.
    created = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "competition", "reviewer_id": ids["teacher"]},
    )
    assert created.status_code == 201, created.text
    sub_id = created.json()["id"]
    fid = _upload_pdf(c["student1"], sub_id, "certificate.pdf")
    draft = c["student1"].patch(
        f"/api/v1/submissions/{sub_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": _valid_competition_form(publicity_url=""),
            "file_ids": [fid],
            "file_roles": {fid: "award_certificate"},
        },
    )
    assert draft.status_code == 200, draft.text
    submitted = post(
        c["student1"],
        f"/api/v1/submissions/{sub_id}/submit",
        {"expected_lock_version": draft.json()["lock_version"]},
    )
    assert submitted.status_code == 202, submitted.text
    version_id = submitted.json()["version_id"]

    # Cross-student isolation & invalid task binding checks
    assert c["student2"].get(f"/api/v1/submissions/{sub_id}").status_code == 404
    assert c["student2"].get(f"/api/v1/files/{fid}/download").status_code == 404

    approved = post(
        c["teacher"],
        f"/api/v1/submissions/{sub_id}/decision",
        {
            "expected_lock_version": submitted.json()["lock_version"],
            "version_id": version_id,
            "outcome": "approved",
            "opinion": "证书信息与表单一致",
        },
    )
    assert approved.status_code == 200, approved.text
    drain(app.state.sessions)

    portrait = c["teacher"].get(f"/api/v1/students/{ids['student1']}/portrait").json()
    assert portrait["counts"]["competition_records"] == 1
    assert portrait["records"][0]["kind"] == "competition"

    growth = c["teacher"].get(f"/api/v1/students/{ids['student1']}/growth").json()
    assert growth["counts"]["competitions"] == 1
    assert growth["trend"][0]["competition"] == 1
    dims = {d["key"]: d for d in growth["dimensions"]}
    assert dims["training"]["count"] == 1
    assert dims["contribution"]["count"] == 1

    # Return/resubmit/correction + export work on competition
    detail = c["student1"].get(f"/api/v1/submissions/{sub_id}").json()
    corr = post(
        c["student1"],
        f"/api/v1/submissions/{sub_id}/corrections",
        {"expected_lock_version": detail["lock_version"], "reason": "补充团队成员"},
    )
    assert corr.status_code == 201, corr.text
    handled = post(
        c["manager"],
        f"/api/v1/corrections/{corr.json()['id']}/handle",
        {
            "expected_lock_version": corr.json()["lock_version"],
            "outcome": "approve",
            "opinion": "允许更正",
        },
    )
    assert handled.status_code == 200
    opened = c["student1"].get(f"/api/v1/submissions/{sub_id}").json()
    redraft = c["student1"].patch(
        f"/api/v1/submissions/{sub_id}/draft",
        json={
            "expected_lock_version": opened["lock_version"],
            "form": _valid_competition_form(
                publicity_url="https://example.org/awards/updated",
                team_members="张三\n李四\n王五",
            ),
            "file_ids": [fid],
            "file_roles": {fid: "award_certificate"},
        },
    )
    assert redraft.status_code == 200
    resub = post(
        c["student1"],
        f"/api/v1/submissions/{sub_id}/submit",
        {"expected_lock_version": redraft.json()["lock_version"]},
    )
    assert resub.status_code == 202
    assert (
        post(
            c["teacher"],
            f"/api/v1/submissions/{sub_id}/decision",
            {
                "expected_lock_version": resub.json()["lock_version"],
                "version_id": resub.json()["version_id"],
                "outcome": "approved",
                "opinion": "更正后核验通过",
            },
        ).status_code
        == 200
    )
    drain(app.state.sessions)
    exported = post(c["teacher"], "/api/v1/exports", {"submission_ids": [sub_id]})
    assert exported.status_code == 202

    # 2. Publicity-link-only competition without file attachment is accepted for review,
    # flagged as needing manual verification (not auto-approved), and can be archived.
    link_only = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "competition", "reviewer_id": ids["teacher"]},
    ).json()
    link_sub_id = link_only["id"]
    link_draft = c["student1"].patch(
        f"/api/v1/submissions/{link_sub_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": _valid_competition_form(
                competition_name="华东高校创新赛",
                publicity_url="https://example.org/publicity",
            ),
            "file_ids": [],
            "file_roles": {},
        },
    )
    assert link_draft.status_code == 200
    link_sub = post(
        c["student1"],
        f"/api/v1/submissions/{link_sub_id}/submit",
        {"expected_lock_version": link_draft.json()["lock_version"]},
    )
    assert link_sub.status_code == 202, link_sub.text
    while run_ai(app.state.sessions, app.state.test_file_root):
        pass
    job = c["teacher"].get(f"/api/v1/ai-jobs/{link_sub.json()['ai_job_id']}").json()
    assert job["status"] == "succeeded"
    checks = {ch["rule_id"]: ch for ch in job["result"]["checks"]}
    assert checks["ATTACHMENT_READABILITY"]["conclusion"] == "unable_to_determine"
    assert checks["FORM_COMPLETENESS"]["conclusion"] == "compliant"

    with app.state.sessions() as session:
        from app.db import AIJob

        db_job = session.get(AIJob, link_sub.json()["ai_job_id"])
        db_job.config = {**db_job.config, "mode": "agent"}
        assert assess(db_job)[0] == "exception"

    assert (
        post(
            c["teacher"],
            f"/api/v1/submissions/{link_sub_id}/decision",
            {
                "expected_lock_version": link_sub.json()["lock_version"],
                "version_id": link_sub.json()["version_id"],
                "outcome": "approved",
                "opinion": "已核对公示链接",
            },
        ).status_code
        == 200
    )
    drain(app.state.sessions)
    assert (
        c["teacher"].get(f"/api/v1/submissions/{link_sub_id}").json()["status"]
        == "archived"
    )

    # 3. Revoked supervision hides competition submissions
    with app.state.sessions.begin() as s:
        rel = s.scalar(
            select(Supervision).where(
                Supervision.teacher_id == ids["teacher"],
                Supervision.student_id == ids["student1"],
            )
        )
        rel.valid_to = "2020-01-01T00:00:00+00:00"
    assert c["teacher"].get(f"/api/v1/submissions/{sub_id}").status_code == 404


def test_competition_validation_rejections(env):
    _, c, ids = env
    assert (
        post(
            c["student1"],
            "/api/v1/submissions",
            {"kind": "competition", "task_id": "t1", "reviewer_id": ids["teacher"]},
        ).status_code
        == 422
    )
    sub_id = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "competition", "reviewer_id": ids["teacher"]},
    ).json()["id"]
    fid = _upload_pdf(c["student1"], sub_id)

    # Reject paper attachment role on competition
    bad_role = c["student1"].patch(
        f"/api/v1/submissions/{sub_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": _valid_competition_form(),
            "file_ids": [fid],
            "file_roles": {fid: "paper_fulltext"},
        },
    )
    assert bad_role.status_code == 422

    # Reject neither certificate nor publicity_url on submit
    draft = c["student1"].patch(
        f"/api/v1/submissions/{sub_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": _valid_competition_form(publicity_url=""),
            "file_ids": [],
            "file_roles": {},
        },
    )
    assert draft.status_code == 200
    bad_submit = post(
        c["student1"],
        f"/api/v1/submissions/{sub_id}/submit",
        {"expected_lock_version": draft.json()["lock_version"]},
    )
    assert bad_submit.status_code == 422
    assert "证书" in bad_submit.json()["detail"]
    assert c["student1"].get(f"/api/v1/submissions/{sub_id}").json()["versions"] == []


def test_exchange_modes_workflow_and_growth_mapping(env):
    app, c, ids = env
    modes_and_roles = [
        ("attend", "attendance_proof"),
        ("talk", "presentation_proof"),
        ("poster", "poster_proof"),
        ("practice_task", "practice_task_proof"),
    ]
    created_ids = []
    for mode, file_role in modes_and_roles:
        created = post(
            c["student1"],
            "/api/v1/submissions",
            {"kind": "exchange", "reviewer_id": ids["teacher"]},
        )
        assert created.status_code == 201, created.text
        sub_id = created.json()["id"]
        created_ids.append(sub_id)
        fid = _upload_pdf(c["student1"], sub_id, f"{mode}.pdf")
        draft = c["student1"].patch(
            f"/api/v1/submissions/{sub_id}/draft",
            json={
                "expected_lock_version": 0,
                "form": _valid_exchange_form(
                    mode,
                    activity_name=f"学术活动-{mode}",
                    presentation_title=f"题目-{mode}" if mode in ("talk", "poster") else "",
                ),
                "file_ids": [fid],
                "file_roles": {fid: file_role},
            },
        )
        assert draft.status_code == 200, draft.text
        sub = post(
            c["student1"],
            f"/api/v1/submissions/{sub_id}/submit",
            {"expected_lock_version": draft.json()["lock_version"]},
        )
        assert sub.status_code == 202, sub.text
        detail = c["teacher"].get(f"/api/v1/submissions/{sub_id}").json()
        assert detail["files"][0]["role"] == file_role
        assert detail["versions"][0]["snapshot"]["form"]["participation_mode"] == mode
        assert (
            post(
                c["teacher"],
                f"/api/v1/submissions/{sub_id}/decision",
                {
                    "expected_lock_version": sub.json()["lock_version"],
                    "version_id": sub.json()["version_id"],
                    "outcome": "approved",
                    "opinion": "学术交流材料核验通过",
                },
            ).status_code
            == 200
        )
    drain(app.state.sessions)

    portrait = c["teacher"].get(f"/api/v1/students/{ids['student1']}/portrait").json()
    assert portrait["counts"]["exchange_records"] == 4
    growth = c["teacher"].get(f"/api/v1/students/{ids['student1']}/growth").json()
    assert growth["counts"]["exchanges"] == 4
    assert growth["trend"][0]["exchange"] == 4
    dims = {d["key"]: d for d in growth["dimensions"]}
    assert dims["exchange"]["count"] == 3
    assert dims["practice"]["count"] == 1
    assert c["student2"].get(f"/api/v1/submissions/{created_ids[0]}").status_code == 404


def test_exchange_validation_rejections(env):
    _, c, ids = env
    assert (
        post(
            c["student1"],
            "/api/v1/submissions",
            {"kind": "exchange", "task_id": "t1", "reviewer_id": ids["teacher"]},
        ).status_code
        == 422
    )
    sub_id = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "exchange", "reviewer_id": ids["teacher"]},
    ).json()["id"]
    fid = _upload_pdf(c["student1"], sub_id)

    # Reject competition attachment role on exchange
    assert (
        c["student1"]
        .patch(
            f"/api/v1/submissions/{sub_id}/draft",
            json={
                "expected_lock_version": 0,
                "form": _valid_exchange_form("attend"),
                "file_ids": [fid],
                "file_roles": {fid: "award_certificate"},
            },
        )
        .status_code
        == 422
    )

    # Reject missing attachment on exchange submit
    d1 = c["student1"].patch(
        f"/api/v1/submissions/{sub_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": _valid_exchange_form("attend"),
            "file_ids": [],
            "file_roles": {},
        },
    )
    assert (
        post(
            c["student1"],
            f"/api/v1/submissions/{sub_id}/submit",
            {"expected_lock_version": d1.json()["lock_version"]},
        ).status_code
        == 422
    )

    # Reject missing presentation_title for talk/poster and practice_task_description for practice_task
    for bad_form in (
        _valid_exchange_form("talk", presentation_title=""),
        _valid_exchange_form("poster", presentation_title=""),
        _valid_exchange_form("practice_task", practice_task_description=""),
    ):
        cur = c["student1"].get(f"/api/v1/submissions/{sub_id}").json()
        d = c["student1"].patch(
            f"/api/v1/submissions/{sub_id}/draft",
            json={
                "expected_lock_version": cur["lock_version"],
                "form": bad_form,
                "file_ids": [fid],
                "file_roles": {fid: "attendance_proof"},
            },
        )
        assert (
            post(
                c["student1"],
                f"/api/v1/submissions/{sub_id}/submit",
                {"expected_lock_version": d.json()["lock_version"]},
            ).status_code
            == 422
        )


def test_competition_proof_mode_team_size_and_exchange_stale_cleanup(env):
    app, c, ids = env
    # Single-member competition with certificate + link
    sub_id = post(
        c["student1"],
        "/api/v1/submissions",
        {"kind": "competition", "reviewer_id": ids["teacher"]},
    ).json()["id"]
    fid = _upload_pdf(c["student1"], sub_id, "both.pdf")
    d = c["student1"].patch(
        f"/api/v1/submissions/{sub_id}/draft",
        json={
            "expected_lock_version": 0,
            "form": _valid_competition_form(
                team_members=[{"name": "演示学生一", "order": 1, "is_self": True}]
            ),
            "file_ids": [fid],
            "file_roles": {fid: "award_certificate"},
        },
    )
    assert d.status_code == 200
    sub = post(
        c["student1"],
        f"/api/v1/submissions/{sub_id}/submit",
        {"expected_lock_version": d.json()["lock_version"]},
    )
    assert sub.status_code == 202
    snap_form = c["teacher"].get(f"/api/v1/submissions/{sub_id}").json()["versions"][0][
        "snapshot"
    ]["form"]
    assert snap_form["proof_mode"] == "certificate_and_link"
    assert snap_form["team_size"] == 1
    assert snap_form["is_team"] is False
    assert snap_form["team_members"][0]["is_self"] is True

    assert (
        post(
            c["teacher"],
            f"/api/v1/submissions/{sub_id}/decision",
            {
                "expected_lock_version": sub.json()["lock_version"],
                "version_id": sub.json()["version_id"],
                "outcome": "approved",
                "opinion": "核验通过",
            },
        ).status_code
        == 200
    )
    drain(app.state.sessions)
    portrait = c["teacher"].get(f"/api/v1/students/{ids['student1']}/portrait").json()
    fact_fields = {f["field"]: f["value"] for f in portrait["records"][0]["facts"]}
    assert fact_fields["proof_mode"] == "certificate_and_link"
    assert fact_fields["team_size"] == 1

    # Exchange mode switching clears stale conditional fields
    switched_attend = canonicalize_exchange_form(
        _valid_exchange_form(
            "attend",
            presentation_title="旧报告题目",
            practice_task_description="旧实践任务",
        )
    )
    assert switched_attend["presentation_title"] == ""
    assert switched_attend["practice_task_description"] == ""

    switched_poster = canonicalize_exchange_form(
        _valid_exchange_form(
            "poster",
            presentation_title="新海报题目",
            practice_task_description="旧实践任务",
        )
    )
    assert switched_poster["presentation_title"] == "新海报题目"
    assert switched_poster["practice_task_description"] == ""


def test_agent_analyze_and_instruction_cover_competition_and_exchange(
    tmp_path, monkeypatch
):
    import httpx

    comp_pack = {
        "version_id": "v1",
        "files": [],
        "snapshot": {
            "form": canonicalize_competition_form(_valid_competition_form()),
            "requirements": {
                "version": "competition-1",
                "required_fields": [
                    "competition_name",
                    "organizer",
                    "award_level",
                    "award_date",
                    "my_role",
                ],
            },
        },
    }
    res_comp = analyze(comp_pack, {"mode": "rules"}, tmp_path)
    checks_comp = {c["rule_id"]: c for c in res_comp["checks"]}
    assert checks_comp["FORM_COMPLETENESS"]["conclusion"] == "compliant"
    assert checks_comp["ATTACHMENT_READABILITY"]["conclusion"] == "unable_to_determine"

    bad_comp_pack = {
        "version_id": "v2",
        "files": [],
        "snapshot": {
            "form": {
                "competition_name": "比赛",
                "organizer": "学会",
                "award_level": "一等奖",
                "award_date": "2026-10-15",
                "my_role": "队长",
                "team_members": [],
                "publicity_url": "",
            },
            "requirements": comp_pack["snapshot"]["requirements"],
        },
    }
    res_bad_comp = analyze(bad_comp_pack, {"mode": "rules"}, tmp_path)
    bad_check = next(
        c for c in res_bad_comp["checks"] if c["rule_id"] == "FORM_COMPLETENESS"
    )
    assert bad_check["conclusion"] == "non_compliant"
    assert "team_members" in bad_check["explanation"]
    assert "proof_attachment_or_publicity_url" in bad_check["explanation"]

    bad_exch_pack = {
        "version_id": "v3",
        "files": [],
        "snapshot": {
            "form": {
                "activity_name": "论坛",
                "activity_date": "2026-11-10",
                "participation_mode": "practice_task",
                "practice_task_description": "",
            },
            "requirements": {
                "version": "exchange-1",
                "required_fields": [
                    "activity_name",
                    "activity_date",
                    "participation_mode",
                ],
            },
        },
    }
    res_bad_exch = analyze(bad_exch_pack, {"mode": "rules"}, tmp_path)
    bad_exch_check = next(
        c for c in res_bad_exch["checks"] if c["rule_id"] == "FORM_COMPLETENESS"
    )
    assert bad_exch_check["conclusion"] == "non_compliant"
    assert "practice_task_description" in bad_exch_check["explanation"]

    captured = {}

    class DummyClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, url, json, headers):
            captured["body"] = json
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"checks":[{"rule_id":"CHECK_COMP","conclusion":"unable_to_determine","severity":"info","explanation":"需人工核对链接","evidence":[]}]}'
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("app.agent.httpx.Client", DummyClient)
    invoke_model(
        {"mode": "chat", "base_url": "http://127.0.0.1:9000/v1", "model": "test"},
        {"version_id": "v1", "form": comp_pack["snapshot"]["form"], "blocks": []},
    )
    system_msg = captured["body"]["messages"][0]["content"]
    assert "竞赛与获奖" in system_msg
    assert "学术交流" in system_msg


def test_fixtures_competition_and_exchange_match_validation():
    fixture_dir = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "competition-and-exchange"
    )
    comp_valid = json.loads((fixture_dir / "competition-valid.json").read_text("utf-8"))
    comp_link = json.loads(
        (fixture_dir / "competition-link-only.json").read_text("utf-8")
    )
    assert canonicalize_competition_form(comp_valid)["is_team"] is True
    assert canonicalize_competition_form(comp_link)["is_team"] is False

    for case in json.loads((fixture_dir / "competition-invalid.json").read_text("utf-8")):
        with pytest.raises(ValueError):
            canonicalize_competition_form(case["form"])

    for case in json.loads((fixture_dir / "exchange-modes.json").read_text("utf-8")):
        normalized = canonicalize_exchange_form(case["form"])
        assert normalized["participation_mode"] == case["mode"]

    for case in json.loads((fixture_dir / "exchange-invalid.json").read_text("utf-8")):
        with pytest.raises(ValueError):
            canonicalize_exchange_form(case["form"])
