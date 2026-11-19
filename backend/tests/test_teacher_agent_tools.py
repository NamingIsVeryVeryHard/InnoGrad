from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import Audit, Idempotency, QueryConversation, QueryRun, StudentProfile, Supervision, User
from app.teacher_agent.api import _ConfiguredPlanner
from app.teacher_agent.budget import TurnBudget
from app.teacher_agent.engine import TeacherQueryEngine
from app.teacher_agent.errors import (
    ConcurrencyConflictError, PlannerConfigError, PlannerInvalidOutputError, PlannerUnavailableError,
    ResourceNotFoundError,
)
from app.teacher_agent.grants import ActiveTurnGrant, InMemoryTurnGrantStore
from test_teacher_agent_conversations import CONVERSATIONS, ROOT, question
from test_workflow import env, post


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    grants = InMemoryTurnGrantStore(clock=lambda: clock.now)
    monkeypatch.setattr("app.teacher_agent.engine.InMemoryTurnGrantStore", lambda: grants)
    return clock


@pytest.fixture
def agent(clock, env, monkeypatch):
    app, clients, ids = env
    transport = TestClient(app)
    teacher = clients["teacher"]
    conversation = post(teacher, CONVERSATIONS, {}).json()["id"]
    monkeypatch.setattr(_ConfiguredPlanner, "mode", "innoagent")

    def ask(callback, key="ask", *, message="请比较今年和去年的论文数量", version=0):
        monkeypatch.setattr(_ConfiguredPlanner, "analyze", lambda self, request, issue_token: callback(issue_token()))
        return post(teacher, f"{CONVERSATIONS}/{conversation}/turns",
                    question(message, version), key)

    def query(token, *, call_id=None, request_id=None, **body):
        params = {"name": "query_papers", "arguments": body}
        if call_id is not None:
            params["_meta"] = {"pi-mcp-adapter/toolCallId": call_id}
        return transport.post(f"{ROOT}/mcp", headers={
            "Authorization": f"Bearer {token}", "MCP-Protocol-Version": "2025-11-25",
        }, json={"jsonrpc": "2.0", "id": str(uuid4()) if request_id is None else request_id,
                 "method": "tools/call", "params": params})

    return SimpleNamespace(ask=ask, query=query, sessions=app.state.sessions, conversation=conversation,
                           clients=clients, teacher=teacher, ids=ids)


def tool_result(response, *, is_error=False):
    assert response.status_code == 200, response.text
    payload = response.json()["result"]
    assert payload["isError"] is is_error
    return payload["structuredContent"]


def assert_persisted(agent, *, turns, runs):
    with agent.sessions() as session:
        conversation = session.get(QueryConversation, agent.conversation)
        assert conversation.turn_count == len(conversation.turns_json) == turns
        assert session.scalar(select(func.count()).select_from(QueryRun)) == runs
        for action, expected in (("teacher_agent.turn", turns), ("teacher_agent.query", runs)):
            assert session.scalar(select(func.count()).select_from(Audit).where(Audit.action == action)) == expected
        receipt_count = session.scalar(select(func.count()).select_from(Idempotency).where(
            Idempotency.operation == f"teacher_agent.turn/{agent.conversation}"))
        assert receipt_count == turns


def test_tool_input_correction_uses_last_successful_query(agent):
    def analyze(token):
        first = agent.query(token, spec={"group_by": ["degree"]})
        view = tool_result(first)
        failure = agent.query(token, spec={"filters": [{"field": "degree", "value": "PhD-private"}]})
        error = tool_result(failure, is_error=True)
        assert error["code"] == "RETRYABLE_TOOL_INPUT"
        assert all(candidate in error["message"] for candidate in ("degree", "博士", "硕士"))
        assert "PhD-private" not in failure.text
        corrected = agent.query(token, patch={"set_filters": [{"field": "degree", "value": "博士"}]})
        tool_result(corrected)
        return f"论文共 {view['metric_refs']['paper_record_count']} 篇。"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [result["query_run_id"] for result in body["results"]] == body["turn"]["run_ids"]
    assert body["result"]["applied_query"]["group_by"] == ["degree"]
    assert body["result"]["applied_query"]["filters"] == [{"field": "degree", "operator": "eq", "value": "博士"}]
    assert_persisted(agent, turns=1, runs=2)


def test_outside_and_nonexistent_names_are_indistinguishable_and_correctable(agent):
    outside_name, missing_name = "组外合成学生", "未登记合成学生"
    with agent.sessions.begin() as session:
        session.add(User(username="out_of_scope", name=outside_name, role="student", password_hash="unused"))
        visible_name = session.get(User, agent.ids["student1"]).name

    def analyze(token):
        def portrait(name):
            return agent.query(token, spec={"operation": "portrait", "filters": [
                {"field": "student_name", "operator": "eq", "value": name},
            ]})

        outside, missing = portrait(outside_name), portrait(missing_name)
        error = tool_result(outside, is_error=True)
        assert error == tool_result(missing, is_error=True)
        assert error["code"] == "RETRYABLE_TOOL_INPUT"
        for response in (outside, missing):
            assert outside_name not in response.text and missing_name not in response.text
        view = tool_result(portrait(visible_name))
        assert view["portrait"]["student_id"] == agent.ids["student1"]
        return f"论文共 {view['metric_refs']['paper_record_count']} 篇。"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]
    assert_persisted(agent, turns=1, runs=1)


def test_third_tool_input_failure_discards_previews_and_stops_turn(agent):
    def analyze(token):
        tool_result(agent.query(token, spec={}))
        for body in ({"spec": {}, "patch": {}}, {"patch": {"operation": "portrait"}}):
            response = agent.query(token, **body)
            assert tool_result(response, is_error=True)["code"] == "RETRYABLE_TOOL_INPUT"
        exhausted = agent.query(token)
        assert exhausted.status_code == 502, exhausted.text
        assert agent.query(token, spec={}).status_code == 502
        return "查询已结束"

    assert agent.query("invalid").status_code == 404
    response = agent.ask(analyze)
    assert response.status_code == 502
    assert response.json()["code"] == "INVALID_PLANNER_OUTPUT"
    assert_persisted(agent, turns=0, runs=0)


def test_call_ids_are_unique_within_a_grant_for_standard_and_pi_clients(agent):
    def analyze(token):
        standard = tool_result(agent.query(token, request_id=7, spec={}))
        assert agent.query(token, request_id=7, spec={}).status_code == 502
        pi = tool_result(agent.query(token, call_id="pi-call", spec={}))
        assert agent.query(token, call_id="pi-call", spec={}).status_code == 502
        assert standard["query_run_id"] != pi["query_run_id"]
        return f"论文共 {standard['metric_refs']['paper_record_count']} 篇。"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    assert_persisted(agent, turns=1, runs=2)


@pytest.mark.parametrize("exhausted", [False, True])
def test_transient_turn_retry_revokes_old_grant_and_only_persists_final_attempt(agent, exhausted):
    tokens, run_ids = [], []

    def analyze(token):
        if tokens:
            assert agent.query(tokens[0], spec={}).status_code == 404
        tokens.append(token)
        preview = agent.query(token, spec={})
        run_ids.append(tool_result(preview)["query_run_id"])
        if len(tokens) == 1 or exhausted:
            raise PlannerUnavailableError("连接中断", retry_after_seconds=2)
        return f"论文共 [{run_ids[-1]}:paper_record_count] 篇。"

    response = agent.ask(analyze)
    assert len(set(tokens)) == len(set(run_ids)) == 2
    if exhausted:
        assert response.status_code == 503
        assert response.json()["code"] == "PLANNER_UNAVAILABLE"
        assert response.headers["Retry-After"] == "2"
        assert_persisted(agent, turns=0, runs=0)
    else:
        assert response.status_code == 200, response.text
        assert response.json()["turn"]["run_ids"] == [run_ids[-1]]
        assert agent.ask(lambda _: pytest.fail("duplicate model call")).json()["turn"]["run_ids"] == [run_ids[-1]]
        assert_persisted(agent, turns=1, runs=1)


@pytest.mark.parametrize("change", ["scope", "version", "invalid_token", "config"])
def test_fatal_turn_failures_skip_retry(agent, change):
    tokens = []

    def analyze(token):
        tokens.append(token)
        if change == "invalid_token":
            assert agent.query(token + "bad", spec={}).status_code == 404
            raise PlannerInvalidOutputError("查询授权失败")
        if change == "config":
            raise PlannerConfigError("规划实例配置无效")
        with agent.sessions.begin() as session:
            if change == "scope":
                relation = session.scalar(select(Supervision).where(Supervision.teacher_id == agent.ids["teacher"]))
                relation.valid_to = "2000-01-01"
            else:
                session.get(QueryConversation, agent.conversation).lock_version += 1
        raise PlannerUnavailableError("连接中断")

    response = agent.ask(analyze)
    assert response.status_code == {"scope": 409, "version": 409, "invalid_token": 502, "config": 503}[change]
    assert len(tokens) == 1
    assert_persisted(agent, turns=0, runs=0)


def test_view_change_rolls_back_before_retrying(agent):
    run_ids = []

    def analyze(token):
        response = agent.query(token, spec={
            "operation": "portrait", "filters": [{"field": "student_id", "value": agent.ids["student1"]}],
        })
        run_ids.append(tool_result(response)["query_run_id"])
        if len(run_ids) == 1:
            with agent.sessions.begin() as session:
                profile = session.scalar(select(StudentProfile).where(StudentProfile.user_id == agent.ids["student1"]))
                profile.major = "新专业"
        return f"论文共 [{run_ids[-1]}:paper_record_count] 篇。"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    assert len(run_ids) == 2
    assert response.json()["turn"]["run_ids"] == [run_ids[-1]]
    assert response.json()["result"]["portrait"]["major"] == "新专业"
    assert_persisted(agent, turns=1, runs=1)


def test_ambiguous_commit_uses_receipt_before_retrying(agent, monkeypatch):
    write_once = TeacherQueryEngine._write_once
    run_ids = []

    def lose_commit_acknowledgment(self, *args):
        write_once(self, *args)
        raise SQLAlchemyError("commit acknowledgment lost")

    def analyze(token):
        preview = agent.query(token, spec={})
        run_ids.append(tool_result(preview)["query_run_id"])
        return f"论文共 [{run_ids[-1]}:paper_record_count] 篇。"

    monkeypatch.setattr(TeacherQueryEngine, "_write_once", lose_commit_acknowledgment)
    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    assert len(run_ids) == 1
    assert response.json()["turn"]["run_ids"] == run_ids
    assert response.json()["analysis"] is None
    assert_persisted(agent, turns=1, runs=1)


def test_duplicate_name_has_zero_cards_and_only_visible_candidates(agent):
    with agent.sessions.begin() as session:
        for username in ("student1", "student2"):
            session.get(User, agent.ids[username]).name = "同名学生"
        session.add(User(username="out_of_scope", name="同名学生", role="student", password_hash="unused"))

    def analyze(token):
        response = agent.query(token, spec={
            "operation": "portrait", "filters": [{"field": "student_name", "value": "同名学生", "operator": "eq"}],
        })
        view = tool_result(response)
        assert view["code"] == "CLARIFICATION_NEEDED" and "query_run_id" not in view
        assert {candidate["student_id"] for candidate in view["clarification"]["student_candidates"]} == {
            agent.ids["student1"], agent.ids["student2"],
        }
        return "我已经自行选择了学生"

    response = agent.ask(analyze, message="查看同名学生的画像")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "clarification_needed"
    assert body["results"] == body["turn"]["run_ids"] == []
    assert body["analysis"] is None and body["result"]["query_run_id"] is None
    assert {candidate["student_id"] for candidate in body["result"]["clarification"]["student_candidates"]} == {
        agent.ids["student1"], agent.ids["student2"],
    }
    assert_persisted(agent, turns=1, runs=0)

    def choose(token):
        result = agent.query(token, spec={
            "operation": "portrait", "filters": [{"field": "student_id", "value": agent.ids["student2"]}],
        })
        return f"论文共 {tool_result(result)['metric_refs']['paper_record_count']} 篇。"

    selected = agent.ask(choose, key="choice", version=1, message=f"查看 {agent.ids['student2']} 的画像")
    assert selected.status_code == 200, selected.text
    assert selected.json()["result"]["portrait"]["student_id"] == agent.ids["student2"]
    assert_persisted(agent, turns=2, runs=1)


@pytest.mark.parametrize("argument", ["spec", "patch"])
def test_explicit_scoped_candidate_id_can_be_queried_in_same_turn(agent, argument):
    duplicate_name = "论文" if argument == "spec" else "同名学生"
    with agent.sessions.begin() as session:
        for username in ("student1", "student2"):
            session.get(User, agent.ids[username]).name = duplicate_name
        unrelated = User(username="unrelated_student", name="其他学生", role="student", password_hash="unused")
        outside = User(username="outside_student", name=duplicate_name, role="student", password_hash="unused")
        session.add_all([unrelated, outside])
        session.flush()
        session.add(Supervision(teacher_id=agent.ids["teacher"], student_id=unrelated.id, valid_from="2000-01-01"))
        unrelated_id, outside_id = unrelated.id, outside.id

    chosen_id = agent.ids["student2"]

    def analyze(token):
        clarification = tool_result(agent.query(token, spec={"operation": "portrait", "filters": [
            {"field": "student_name", "operator": "eq", "value": duplicate_name},
        ]}))
        assert clarification["code"] == "CLARIFICATION_NEEDED"
        filters_key = "filters" if argument == "spec" else "set_filters"

        def portrait(student_id):
            return agent.query(token, **{argument: {"operation": "portrait", filters_key: [
                {"field": "student_id", "value": student_id},
            ]}})

        assert portrait(outside_id).status_code == 404
        assert tool_result(portrait(unrelated_id)) == clarification
        view = tool_result(portrait(chosen_id))
        assert view["portrait"]["student_id"] == chosen_id
        return f"论文共 {view['metric_refs']['paper_record_count']} 篇。"

    response = agent.ask(analyze, message=f"查看{duplicate_name}的画像")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1 and body["result"] == body["results"][0]
    assert body["result"]["portrait"]["student_id"] == chosen_id
    assert {candidate["student_id"] for candidate in body["turn"]["clarification"]["student_candidates"]} == {
        agent.ids["student1"], agent.ids["student2"],
    }
    assert_persisted(agent, turns=1, runs=1)
    with agent.sessions() as session:
        turn = session.get(QueryConversation, agent.conversation).turns_json[0]
        assert duplicate_name not in turn["user_message"]
        assert set(turn) == {
            "id", "turn_index", "input_mode", "user_message", "resolved_query_spec",
            "planner_trace", "status", "run_ids", "created_at",
        }
        assert session.scalar(select(QueryRun)).applied_query["filters"] == [
            {"field": "student_id", "operator": "eq", "value": chosen_id},
        ]


def test_clarification_preserves_preceding_successful_query(agent):
    with agent.sessions.begin() as session:
        for username in ("student1", "student2"):
            session.get(User, agent.ids[username]).name = "同名学生"

    run_ids = []

    def analyze(token):
        first = agent.query(token, spec={"operation": "portrait", "filters": [
            {"field": "student_id", "value": agent.ids["student1"]},
        ]})
        run_ids.append(tool_result(first)["query_run_id"])
        second = agent.query(token, spec={
            "operation": "portrait", "filters": [{"field": "student_name", "value": "同名学生"}],
        })
        clarification = tool_result(second)
        assert clarification["code"] == "CLARIFICATION_NEEDED"
        assert tool_result(agent.query(token, patch={"page_size": 10})) == clarification
        return f"论文共 [{run_ids[0]}:paper_record_count] 篇。"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["turn"]["run_id"] == run_ids[0] and body["turn"]["run_ids"] == run_ids
    assert len(body["results"]) == 1 and body["result"] == body["results"][0]
    assert body["analysis"]
    assert {candidate["student_id"] for candidate in body["turn"]["clarification"]["student_candidates"]} == {
        agent.ids["student1"], agent.ids["student2"],
    }
    assert_persisted(agent, turns=1, runs=1)


@pytest.mark.parametrize(("text", "message"), [
    ("您想查看今年还是去年的论文？", "您想查看今年还是去年的论文？"),
    ("请联系校外学生李四。", "请明确要查看的论文范围，或从名单中选择学生。"),
    ("论文" * 200 + "？", "请明确要查看的论文范围，或从名单中选择学生。"),
])
def test_zero_call_clarification_uses_only_bounded_safe_planner_text(agent, text, message):
    response = agent.ask(lambda _: text)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"] == body["turn"]["run_ids"] == []
    assert body["analysis"] is None and body["result"]["query_run_id"] is None
    assert body["result"]["clarification"]["message"] == body["turn"]["clarification"]["message"] == message
    replay = agent.ask(lambda _: pytest.fail("clarification replay called the model")).json()
    assert replay["turn"]["id"] == body["turn"]["id"]
    assert replay["turn"]["run_id"] is None and replay["turn"]["run_ids"] == replay["results"] == []
    assert replay["analysis"] is None and replay["analysis_notice"] is None
    assert_persisted(agent, turns=1, runs=0)


def test_multiple_tool_queries_have_one_turn_and_no_reusable_grant(agent):
    tokens, run_ids = [], []

    def analyze(token):
        tokens.append(token)
        for year in (2026, 2025):
            response = agent.query(token, spec={"time_range": {"from": f"{year}-01-01", "to": f"{year}-12-31"}})
            view = tool_result(response)
            assert set(view) >= {"query_run_id", "metrics", "metric_refs", "items"}
            run_ids.append(view["query_run_id"])
        return f"本期论文共 [{run_ids[0]}:paper_record_count] 篇，上期共 [{run_ids[1]}:paper_record_count] 篇。"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["turn"]["run_ids"] == run_ids
    assert [result["query_run_id"] for result in body["results"]] == run_ids
    assert body["result"] == body["results"][-1]
    assert body["analysis"] and "0" in body["analysis"]
    assert agent.query(tokens[0], spec={}).status_code == 404
    invalid_after_revoke = agent.query(tokens[0], spec={}, patch={})
    assert invalid_after_revoke.status_code == 404
    assert "result" not in invalid_after_revoke.json()
    with agent.sessions.begin() as session:
        session.get(QueryRun, run_ids[0]).created_at = "2099-01-01"
        session.get(QueryRun, run_ids[1]).created_at = "2000-01-01"
    replay = agent.ask(lambda _: pytest.fail("duplicate model call")).json()
    assert replay["turn"]["run_ids"] == run_ids
    history = agent.teacher.get(f"{CONVERSATIONS}/{agent.conversation}").json()
    assert len(history["turns"]) == 1
    assert [item["query_run_id"] for item in history["latest_results"]] == run_ids
    assert agent.clients["manager"].get(f"{ROOT}/runs/{run_ids[0]}").status_code == 404
    drill = post(agent.teacher, f"{CONVERSATIONS}/{agent.conversation}/turns", {
        "expected_lock_version": 1,
        "input": {"mode": "drilldown_patch", "parent_run_id": run_ids[0], "patch": {"operation": "list"}},
    })
    assert drill.status_code == 200, drill.text
    assert drill.json()["result"]["applied_query"]["time_range"]["from"] == "2026-01-01"


def test_failed_agent_turn_rolls_back_calls_and_caps_queries(agent):
    def analyze(token):
        assert tool_result(agent.query(token, spec={}, teacher_id=agent.ids["manager"]), is_error=True)[
            "code"] == "RETRYABLE_TOOL_INPUT"
        for _ in range(5):
            tool_result(agent.query(token, spec={}))
        assert agent.query(token, spec={}).status_code == 404
        raise PlannerUnavailableError("连接中断")

    assert agent.ask(analyze).status_code == 503
    assert_persisted(agent, turns=0, runs=0)


def test_unverified_analysis_keeps_verified_cards(agent):
    def analyze(token):
        tool_result(agent.query(token, spec={}))
        return "导师组已发表 99999 篇论文"

    response = agent.ask(analyze)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"] is None and body["analysis_notice"]
    assert len(body["results"]) == 1
    assert body["results"][0]["query_run_id"] == body["turn"]["run_ids"][0]


def test_tool_portrait_respects_live_teacher_scope(agent):
    def analyze(token):
        def portrait(student_id):
            return agent.query(token, spec={"operation": "portrait",
                               "filters": [{"field": "student_id", "value": student_id}]})

        assert portrait(agent.ids["manager"]).status_code == 404
        response = portrait(agent.ids["student1"])
        view = tool_result(response)
        assert view["portrait"]["student_id"] == agent.ids["student1"]
        return f"可以打开学生画像核对归档材料 [{view['query_run_id']}]。"

    assert agent.ask(analyze).status_code == 200


def test_revocation_and_expiry_invalidate_live_callbacks(agent, clock):
    def analyze(token):
        tool_result(agent.query(token, spec={}))
        with agent.sessions.begin() as session:
            relation = session.scalar(select(Supervision).where(Supervision.teacher_id == agent.ids["teacher"]))
            relation.valid_to = "2000-01-01"
        assert agent.query(token, spec={"filters": [
            {"field": "student_name", "value": "未登记合成学生"},
        ]}).status_code == 409
        return "查询已结束"

    assert agent.ask(analyze).status_code == 409

    def expire(token):
        first = agent.query(token, spec={})
        view = tool_result(first)
        clock.now += 60
        assert agent.query(token, spec={}).status_code == 404
        return f"本轮结果见卡片 [{view['query_run_id']}]。"

    assert agent.ask(expire, key="expired").status_code == 200
    assert_persisted(agent, turns=1, runs=1)


def test_grant_store_serializes_claims_and_keeps_expired_results_for_owner():
    clock = SimpleNamespace(now=10.0)
    grants = InMemoryTurnGrantStore(clock=lambda: clock.now, ttl_seconds=5)
    grant = ActiveTurnGrant("teacher", "conversation", "turn", 0, "scope", [], TurnBudget())
    grants.issue("first", grant)
    with pytest.raises(ConcurrencyConflictError):
        grants.issue("second", grant)

    claimed = Event()
    queued = Event()

    def initial():
        with grants.claim("first") as active:
            active.calls.append({"spec": {"page": 1}})
            claimed.set()
            assert queued.wait(5)
        active.calls.clear()

    def refine():
        assert claimed.wait(5)
        queued.set()
        with grants.claim("first") as active:
            assert active.calls == [{"spec": {"page": 1}}]
            active.calls.append({"spec": {"page": 2}})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(initial), pool.submit(refine)
        first.result(timeout=5)
        second.result(timeout=5)

    grant.calls.append({"spec": {"page": 3}})
    clock.now = 15
    with pytest.raises(ResourceNotFoundError), grants.claim("first"):
        pytest.fail("expired grant was accepted")
    with grants.finalize("first") as final:
        assert final.calls == [{"spec": {"page": 1}}, {"spec": {"page": 2}}]
    with pytest.raises(ResourceNotFoundError), grants.finalize("first"):
        pytest.fail("grant was finalized twice")
    grants.revoke("first")
    grants.issue("second", grant)
    with pytest.raises(ResourceNotFoundError), grants.claim("first"):
        pytest.fail("revoked grant was accepted")


def test_expired_abandoned_grant_can_be_replaced_without_releasing_new_owner():
    clock = SimpleNamespace(now=10.0)
    grants = InMemoryTurnGrantStore(clock=lambda: clock.now, ttl_seconds=5)
    old = ActiveTurnGrant("teacher", "conversation", "old", 0, "scope", [], TurnBudget())
    new = ActiveTurnGrant("teacher", "conversation", "new", 0, "scope", [], TurnBudget())
    grants.issue("old", old)
    clock.now = 15
    grants.issue("new", new)
    grants.revoke("old")
    with pytest.raises(ResourceNotFoundError), grants.finalize("old"):
        pytest.fail("superseded grant was finalized")
    with pytest.raises(ConcurrencyConflictError):
        grants.issue("intruder", old)
    with grants.claim("new") as active:
        assert active.turn_id == "new"


def test_expiry_takeover_waits_for_finalization_without_blocking_other_conversations():
    expired = Event()
    observed_expiry = Event()

    def clock():
        if expired.is_set():
            observed_expiry.set()
            return 15.0
        return 10.0

    grants = InMemoryTurnGrantStore(clock=clock, ttl_seconds=5)
    grants.issue("old", ActiveTurnGrant("teacher", "conversation", "old", 0, "scope", [], TurnBudget()))
    replacement = ActiveTurnGrant("teacher", "conversation", "new", 0, "scope", [], TurnBudget())
    independent = ActiveTurnGrant("teacher", "other", "another", 0, "scope", [], TurnBudget())
    with ThreadPoolExecutor(max_workers=2) as pool:
        with grants.finalize("old"):
            expired.set()
            replace = pool.submit(grants.issue, "new", replacement)
            assert observed_expiry.wait(5)
            pool.submit(grants.issue, "other", independent).result(timeout=5)
            assert not replace.done()
        replace.result(timeout=5)
    with grants.claim("new") as active:
        assert active.turn_id == "new"


def test_grant_store_rejects_multiple_workers(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(PlannerConfigError):
        InMemoryTurnGrantStore()
