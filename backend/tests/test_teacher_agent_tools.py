from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import QueryRun, QueryTurn, QueryTurnGrant, Supervision
from app.teacher_agent.api import _ConfiguredPlanner
from app.teacher_agent.errors import PlannerUnavailableError
from test_teacher_agent_conversations import CONVERSATIONS, ROOT, question
from test_workflow import env, post


@pytest.fixture
def agent(env, monkeypatch):
    app, clients, ids = env
    transport = TestClient(app)
    teacher = clients["teacher"]
    conversation = post(teacher, CONVERSATIONS, {}).json()["id"]
    monkeypatch.setattr(_ConfiguredPlanner, "mode", "innoagent")

    def ask(callback, key="ask"):
        monkeypatch.setattr(_ConfiguredPlanner, "analyze", lambda self, request, issue_token: callback(issue_token()))
        return post(teacher, f"{CONVERSATIONS}/{conversation}/turns",
                    question("请比较今年和去年的论文数量", 0), key)

    def query(token, **body):
        return transport.post(f"{ROOT}/tools/query-papers", headers={"Authorization": f"Bearer {token}"}, json=body)

    return SimpleNamespace(ask=ask, query=query, sessions=app.state.sessions, conversation=conversation,
                           clients=clients, teacher=teacher, ids=ids)


def test_multiple_tool_queries_have_one_turn_and_no_reusable_grant(agent):
    tokens, run_ids = [], []

    def analyze(token):
        tokens.append(token)
        for year in (2026, 2025):
            response = agent.query(token, spec={"time_range": {"from": f"{year}-01-01", "to": f"{year}-12-31"}})
            assert response.status_code == 200, response.text
            view = response.json()
            assert set(view) >= {"query_run_id", "metrics", "items"}
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
        assert agent.query(token, spec={}, teacher_id=agent.ids["manager"]).status_code == 422
        for _ in range(5):
            assert agent.query(token, spec={}).status_code == 200
        assert agent.query(token, spec={}).status_code == 404
        raise PlannerUnavailableError("连接中断")

    assert agent.ask(analyze).status_code == 503
    with agent.sessions() as session:
        for model in (QueryRun, QueryTurn, QueryTurnGrant):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_unverified_analysis_keeps_verified_cards(agent):
    def analyze(token):
        assert agent.query(token, spec={}).status_code == 200
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
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["portrait"]["student_id"] == agent.ids["student1"]
        return f"可以打开学生画像核对归档材料 [{view['query_run_id']}]。"

    assert agent.ask(analyze).status_code == 200


def test_revocation_and_expiry_invalidate_live_callbacks(agent):
    def analyze(token):
        assert agent.query(token, spec={}).status_code == 200
        with agent.sessions.begin() as session:
            relation = session.scalar(select(Supervision).where(Supervision.teacher_id == agent.ids["teacher"]))
            relation.valid_to = "2000-01-01"
        assert agent.query(token, spec={}).status_code == 409
        return "查询已结束"

    assert agent.ask(analyze).status_code == 409

    def expire(token):
        first = agent.query(token, spec={})
        assert first.status_code == 200
        with agent.sessions.begin() as session:
            session.scalar(select(QueryTurnGrant)).expires_at = 0
        assert agent.query(token, spec={}).status_code == 404
        return f"本轮结果见卡片 [{first.json()['query_run_id']}]。"

    assert agent.ask(expire, key="expired").status_code == 200
