import json
from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Audit, LoginSession, QueryRun, User
from app.policy import relation
from app.seed_scenarios import ident, seed_scenarios
from test_workflow import env


@pytest.fixture
def cohort(env, tmp_path):
    app, clients, _ = env
    seed_scenarios(app.state.sessions, app.state.test_file_root, tmp_path / "bundle", date(2026, 11, 19))
    with TestClient(app) as teacher:
        teacher.headers["Authorization"] = "Bearer " + clients["teacher"].cookies["session"]
        yield teacher


def rpc(client, method, *, params=None, headers=None):
    return client.post("/api/v1/teacher-agent/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
    })


def call(client, tool, arguments, *, is_error=False):
    response = rpc(client, "tools/call", params={"name": tool, "arguments": arguments})
    assert response.status_code == 200, response.text
    packet = response.json()
    assert "result" in packet, packet
    result = packet["result"]
    assert result.get("isError", False) is is_error, result
    payload = result["structuredContent"]
    assert json.loads(result["content"][0]["text"]) == payload
    return payload


def totals(summary):
    assert summary["status"] == "ok"
    metrics = {metric["key"]: metric["value"] for metric in summary["metrics"]}
    return metrics["paper_record_count"], metrics["paper_student_count"]


def test_teacher_discovers_three_tools_and_follows_2026_papers_to_original(cohort, env):
    handshake = rpc(cohort, "initialize", params={
        "protocolVersion": "2025-06-18", "clientInfo": {"name": "acceptance", "version": "1"}, "capabilities": {},
    })
    assert handshake.status_code == 200, handshake.text
    cohort.headers["MCP-Protocol-Version"] = handshake.json()["result"]["protocolVersion"]
    discovery = rpc(cohort, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in discovery} == {"summarize_papers", "list_papers", "get_student_portrait"}

    overview = call(cohort, "summarize_papers", {"year": 2026, "group_by": "publication_status"})
    assert totals(overview) == (18, 12)
    assert {row["group_key"]["publication_status"]: (row["record_count"], row["student_count"])
            for row in overview["breakdown"]} == {"published": (3, 3), "submitted": (3, 3), "accepted": (12, 9)}
    doctoral = {"year": 2026, "degree": "博士"}
    filtered = call(cohort, "summarize_papers", {**doctoral, "group_by": "publication_status"})
    assert totals(filtered) == (9, 6)
    accepted = next(row for row in filtered["breakdown"] if row["group_key"]["publication_status"] == "accepted")
    drilldown = accepted["drilldown"]
    assert drilldown["tool"] == "list_papers"
    assert drilldown["arguments"] == {**doctoral, "publication_status": "accepted", "subject": "paper"}
    accepted_list = call(cohort, drilldown["tool"], drilldown["arguments"])
    assert accepted_list["pagination"]["total"] == accepted["record_count"] == 6
    assert all(item["publication_status"] == "accepted" for item in accepted_list["items"])
    assert totals(call(cohort, "summarize_papers", {**doctoral, "year": 2025})) == (0, 0)
    assert call(cohort, "list_papers", {**doctoral, "year": 2025})["items"] == []

    expected_records = {
        ident(f"submission/{student}/paper{index}"): ident(student)
        for student, count in (("s01", 2), ("s03", 2), ("s05", 2), ("s07", 1), ("s09", 1), ("s11", 1))
        for index in range(count)
    }
    records = []
    for page in (1, 2):
        listing = call(cohort, "list_papers", {**doctoral, "subject": "paper", "page": page, "page_size": 5})
        assert listing["pagination"] == {"total": 9, "page": page, "page_size": 5, "has_more": page == 1}
        assert len(listing["items"]) == (5 if page == 1 else 4)
        records.extend(listing["items"])
    assert {row["submission_id"]: row["student_id"] for row in records} == expected_records
    students = call(cohort, "list_papers", {**doctoral, "subject": "student"})
    assert students["pagination"]["total"] == len(students["items"]) == 6
    assert {row["student_id"]: row["matched_record_count"] for row in students["items"]} == Counter(
        expected_records.values())

    chosen = next(row for row in records if row["submission_id"] == ident("submission/s01/paper0"))
    portrait = call(cohort, "get_student_portrait", {"student_id": chosen["student_id"]})["portrait"]
    assert portrait["student_id"] == ident("s01")
    assert portrait["student_number"] == "SIM20230001"
    assert {row["submission_id"] for row in portrait["records"]} == {
        ident("submission/s01/paper0"), ident("submission/s01/paper1"),
    }
    original = next(record for record in portrait["records"] if record["submission_id"] == chosen["submission_id"])
    url = original["files"][0]["download_url"]
    assert url == chosen["files"][0]["download_url"]
    assert url == f"http://testserver/api/v1/files/{ident('file/s01/paper0')}/download"
    for row in [*records, *students["items"], *portrait["records"]]:
        for file in row["files"]:
            assert file["download_url"] == f"http://testserver/api/v1/files/{file['file_id']}/download"
    expected_bytes = (env[0].state.test_file_root / ident("storage/s01/paper0")).read_bytes()
    assert expected_bytes
    for teacher in (cohort, env[1]["teacher"]):
        download = teacher.get(url)
        assert download.status_code == 200, download.text
        assert download.content == expected_bytes
    with TestClient(env[0]) as anonymous:
        assert anonymous.get(url).status_code == 401


def test_name_candidates_and_originals_follow_live_teacher_scope(cohort, env):
    app, _, ids = env
    outsider = ident("s02")
    visible = ident("s01")
    with app.state.sessions.begin() as session:
        shared_name = session.get(User, visible).name
        session.get(User, ids["student1"]).name = shared_name
        session.get(User, outsider).name = shared_name
    previous = call(cohort, "get_student_portrait", {"student_id": outsider})["portrait"]
    file_url = previous["records"][0]["files"][0]["download_url"]
    assert cohort.get(file_url).status_code == 200
    with app.state.sessions.begin() as session:
        relation(session, ids["teacher"], outsider).valid_to = "2000-01-01"

    ambiguous = call(cohort, "get_student_portrait", {"student_name": shared_name})
    assert ambiguous["status"] == "clarification_needed"
    candidates = {candidate["student_id"] for candidate in ambiguous["candidates"]}
    assert candidates == {visible, ids["student1"]}
    assert len({candidate["student_number"] for candidate in ambiguous["candidates"]}) == 2
    assert not ambiguous.get("portrait")
    for candidate in candidates:
        selected = call(cohort, "get_student_portrait", {"student_id": candidate})
        assert selected["portrait"]["student_id"] == candidate
    assert totals(call(cohort, "summarize_papers", {"year": 2026})) == (16, 11)
    assert cohort.get(file_url).status_code == 404
    hidden = call(cohort, "get_student_portrait", {"student_id": outsider}, is_error=True)
    missing = call(cohort, "get_student_portrait", {"student_id": ident("absent")}, is_error=True)
    assert hidden["code"] == "NOT_FOUND"
    assert hidden == missing
    with app.state.sessions() as session:
        actions = Counter(session.scalars(select(Audit.action).where(Audit.actor_id == ids["teacher"])))
        assert actions["teacher_agent.query.clarification"] == 1
        assert actions["teacher_agent.query.error"] == 2


def test_tool_calls_require_current_teacher_login_and_write_audit(env):
    app, clients, ids = env
    args = {"name": "summarize_papers", "arguments": {"year": 2026}}
    with TestClient(app) as client:
        assert rpc(client, "tools/call", params=args).status_code == 401
        for authorization, status in (
            ("Bearer invalid", 401),
            ("Bearer " + clients["student1"].cookies["session"], 403),
        ):
            denied = rpc(client, "tools/call", params=args, headers={"Authorization": authorization})
            assert denied.status_code == status, denied.text
        client.headers["Authorization"] = "Bearer " + clients["teacher"].cookies["session"]
        assert totals(call(client, args["name"], args["arguments"])) == (0, 0)
        with app.state.sessions.begin() as session:
            audit = session.scalars(select(Audit).where(
                Audit.actor_id == ids["teacher"], Audit.action == "teacher_agent.query",
            )).one()
            run = session.get(QueryRun, audit.object_id)
            assert run.teacher_id == ids["teacher"] and run.operation == "aggregate"
            assert run.conversation_id is None and run.turn_id is None
            login = session.scalars(select(LoginSession).where(LoginSession.user_id == ids["teacher"])).one()
            login.expires_at = "2000-01-01T00:00:00+00:00"
        expired = rpc(client, "tools/call", params=args)
        assert expired.status_code == 401, expired.text
