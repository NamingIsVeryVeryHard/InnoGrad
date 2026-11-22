import pytest
from sqlalchemy import func, select

from app.db import Audit, Idempotency, QueryConversation, QueryRun, uid
from app.teacher_agent.contract import ScholarshipQuerySpec
from app.teacher_agent.planner import requests_scholarship
from test_teacher_agent_conversations import CONVERSATIONS, ROOT, question
from test_teacher_agent_tools import agent, assert_persisted, clock, tool_result
from test_workflow import env, post


SCHOLARSHIP_TURN = {
    "expected_lock_version": 0,
    "input": {"mode": "structured_spec", "spec": {"domain": "scholarship"}},
}
SCHOLARSHIP_NOTICE = "当前仅开放论文查询，奖学金查询将在后续开放。"


def execution_counts(session):
    return (
        session.scalar(select(func.count()).select_from(QueryRun)),
        session.scalar(select(func.count()).select_from(Audit).where(Audit.action == "teacher_agent.query")),
    )


def check_unsupported_scholarship_turn(turn, result, results):
    assert turn["status"] == result["status"] == "unsupported_domain"
    assert turn["id"] == result["turn_id"]
    assert not turn["access_revoked"]
    assert turn["run_ids"] == results == result["items"] == result["sources"] == []
    assert turn["run_id"] is result["query_run_id"] is None
    assert turn["resolved_query"] is result["applied_query"] is None
    assert turn["clarification"] == result["clarification"] == {
        "message": SCHOLARSHIP_NOTICE, "suggestions": [], "student_candidates": [],
    }


@pytest.mark.parametrize("role", ["teacher", "manager"])
def test_structured_scholarship_retains_notice_without_execution(env, role):
    app, clients, _ = env
    actor = clients[role]
    created = post(actor, CONVERSATIONS, {})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    path = f"{CONVERSATIONS}/{conversation_id}"

    response = post(actor, f"{path}/turns", SCHOLARSHIP_TURN, "scholarship")
    assert response.status_code == 200, response.text
    initial = response.json()
    check_unsupported_scholarship_turn(initial["turn"], initial["result"], initial["results"])
    assert initial["result"]["conversation_id"] == conversation_id
    assert initial["turn"]["input_mode"] == "structured_spec"
    assert initial["conversation_lock_version"] == 1
    with app.state.sessions() as session:
        assert execution_counts(session) == (0, 0)

    replay = post(actor, f"{path}/turns", SCHOLARSHIP_TURN, "scholarship")
    history = actor.get(path)
    assert replay.status_code == history.status_code == 200
    assert replay.json() == initial
    detail = history.json()
    assert detail["active_query"] is None
    assert detail["conversation"]["turn_count"] == detail["conversation"]["lock_version"] == 1
    assert detail["turns"] == [initial["turn"]]
    assert detail["latest_result"] == initial["result"]
    assert detail["latest_results"] == []
    with app.state.sessions() as session:
        assert execution_counts(session) == (0, 0)
        assert session.scalar(select(Audit.object_id).where(Audit.action == "teacher_agent.turn")) == initial["turn"]["id"]

    paper = {"expected_lock_version": 1, "input": {"mode": "structured_spec", "spec": {"domain": "paper"}}}
    executed = post(actor, f"{path}/turns", paper, "paper")
    assert executed.status_code == 200, executed.text
    body = executed.json()
    card, = body["results"]
    run_id = card["query_run_id"]
    assert card["status"] == "ok" and card["pagination"]["total"] == 0
    assert run_id and body["turn"]["run_ids"] == [run_id]
    retry = post(actor, f"{path}/turns", paper, "paper")
    run = actor.get(f"{ROOT}/runs/{run_id}")
    reopened = actor.get(path)
    assert retry.status_code == run.status_code == reopened.status_code == 200
    assert [item["query_run_id"] for item in retry.json()["results"]] == [run_id]
    assert run.json()["query_run_id"] == run_id and run.json()["pagination"]["total"] == 0
    assert reopened.json()["turns"][0] == initial["turn"]
    assert [item["query_run_id"] for item in reopened.json()["latest_results"]] == [run_id]
    with app.state.sessions() as session:
        assert execution_counts(session) == (1, 1)


def test_legacy_structured_scholarship_receipt_keeps_history_without_result_cards(env):
    app, clients, ids = env
    teacher = clients["teacher"]
    created = post(teacher, CONVERSATIONS, {})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    path = f"{CONVERSATIONS}/{conversation_id}"
    response = post(teacher, f"{path}/turns", SCHOLARSHIP_TURN, "legacy")
    assert response.status_code == 200, response.text
    original = response.json()["turn"]
    spec = ScholarshipQuerySpec().model_dump(mode="json", by_alias=True)
    run_id = original["run_id"] or uid()
    with app.state.sessions.begin() as session:
        conversation = session.get(QueryConversation, conversation_id)
        if original["run_id"] is None:
            stamp = original["created_at"]
            conversation.turns_json = [
                {**conversation.turns_json[0], "run_ids": [run_id], "resolved_query_spec": spec},
            ]
            session.add(QueryRun(
                id=run_id, teacher_id=ids["teacher"], conversation_id=conversation_id, turn_id=original["id"],
                domain=spec["domain"], operation=spec["operation"], basis=spec["basis"], applied_query=spec,
                scope_digest=conversation.scope_digest_snapshot, scope_size=conversation.scope_size_snapshot,
                data_as_of=stamp, created_at=stamp, result_version=response.json()["result"]["schema_version"],
                metric_receipt={}, source_refs=[],
            ))
            session.add(Audit(actor_id=ids["teacher"], action="teacher_agent.query", object_id=run_id))
        stored_turns = conversation.turns_json
        receipt = session.scalar(select(Idempotency).where(
            Idempotency.operation == f"teacher_agent.turn/{conversation_id}", Idempotency.key == "legacy",
        ))
        receipt_id = receipt.id
        assert receipt.response == {"turn_id": original["id"]}

    retry = post(teacher, f"{path}/turns", SCHOLARSHIP_TURN, "legacy")
    reopened = teacher.get(path)
    assert retry.status_code == reopened.status_code == 200
    body, detail = retry.json(), reopened.json()
    check_unsupported_scholarship_turn(body["turn"], body["result"], body["results"])
    assert body["turn"]["id"] == original["id"]
    assert body["turn"]["created_at"] == original["created_at"]
    assert detail["turns"] == [body["turn"]]
    assert detail["latest_result"] == body["result"] and detail["latest_results"] == []

    legacy_url = f"{ROOT}/runs/{run_id}"
    old_run = teacher.get(legacy_url)
    assert old_run.status_code == 200 and old_run.json()["query_run_id"] == run_id
    assert old_run.json()["status"] == "unsupported_domain"
    assert clients["manager"].get(legacy_url).status_code == 404
    with app.state.sessions() as session:
        assert execution_counts(session) == (1, 1)
        assert session.get(QueryRun, run_id).applied_query == spec
        assert session.get(QueryConversation, conversation_id).turns_json == stored_turns
        assert session.get(Idempotency, receipt_id).response == {"turn_id": original["id"]}


@pytest.mark.parametrize(("message", "expected"), [
    ("查看奖学金申请情况", True),
    ("奖学金发给谁了？", True),
    ("今年奖学金评给了几人？", True),
    ("谁领了奖学金？", True),
    ("哪些发表过论文的学生获得了“国家奖学金”？", True),
    ("今年拿到校级奖学金的同学有多少？", True),
    ("哪些学生获奖了？", True),
    ("获得国家奖学金的学生发表了哪些论文？", True),
    ("国家奖学金获得者的论文有哪些？", True),
    ("获奖学生发表的论文有多少篇？", True),
    ("哪些论文获奖了？", True),
    ("列出标题包含奖学金的论文和获奖学生名单", True),
    ("列出标题包含奖学金的论文，也看看奖学金发给谁了", True),
    ("列出获得国家奖学金的学生发表的、标题包含奖学金的论文", True),
    ("列出论文标题包含奖学金且作者曾获得国家奖学金的记录", True),
    ("列出论文标题包含‘国家奖学金申请’的记录", False),
    ("论文下一页", False),
])
def test_requested_object_controls_scholarship_routing(message, expected):
    assert requests_scholarship(message) is expected


@pytest.mark.parametrize(("message", "ongoing"), [
    ("获得国家奖学金的学生有哪些？", False),
    ("获得国家奖学金的学生有哪些？", True),
    ("获得国家奖学金的学生发表了哪些论文？", True),
])
def test_scholarship_turn_has_no_runs_and_survives_refresh_and_retry(agent, message, ongoing):
    agent_calls = []

    def analyze(token):
        agent_calls.append(token)
        tool_result(agent.query(token, spec={"group_by": ["stage"]}))
        return "当前仅能查询论文。"

    path = f"{CONVERSATIONS}/{agent.conversation}"
    previous = None
    if ongoing:
        previous = agent.ask(analyze, key="papers", message="按阶段统计论文").json()
        assert previous["result"]["status"] == "ok"
        agent_calls.clear()

    version = int(ongoing)
    response = agent.ask(analyze, message=message, version=version)
    assert response.status_code == 200, response.text
    initial = response.json()
    assert initial["result"]["status"] == "unsupported_domain"
    assert agent_calls == []

    history = agent.teacher.get(path)
    replay = post(agent.teacher, path + "/turns", question(message, version), "ask")
    assert history.status_code == replay.status_code == 200
    detail = history.json()
    assert replay.json() == initial
    assert detail["latest_result"] == initial["result"]
    assert detail["latest_results"] == initial["results"] == []
    assert detail["turns"][-1] == initial["turn"]
    assert initial["turn"]["status"] == "unsupported_domain"
    assert initial["turn"]["run_ids"] == []
    assert initial["turn"]["run_id"] is None
    assert initial["result"]["query_run_id"] is None
    assert initial["turn"]["clarification"] == initial["result"]["clarification"]
    assert initial["result"]["clarification"]["message"] == "当前仅开放论文查询，奖学金查询将在后续开放。"
    assert len(detail["turns"]) == version + 1
    if previous:
        assert detail["turns"][0] == previous["turn"]
        assert detail["active_query"] == previous["result"]["applied_query"]
        run = agent.teacher.get(f"{ROOT}/runs/{previous['turn']['run_id']}")
        assert run.status_code == 200, run.text
        assert run.json()["applied_query"] == previous["result"]["applied_query"]
    assert_persisted(agent, turns=version + 1, runs=version)


@pytest.mark.parametrize(("message", "value"), [
    ("列出标题包含‘奖学金’的论文", "奖学金"),
    ("列出标题包含奖学金的论文", "奖学金"),
    ("列出标题包含获奖的论文", "获奖"),
    ("列出标题包含获得国家奖学金的学生的论文", "获得国家奖学金的学生"),
    ("查找关于国家奖学金申请的论文", "国家奖学金申请"),
    ("查找关于‘获得国家奖学金的学生’的论文", "获得国家奖学金的学生"),
])
def test_scholarship_search_text_still_reaches_paper_query(agent, message, value):
    title_filter = {"field": "title", "operator": "contains", "value": value}

    def analyze(token):
        tool_result(agent.query(token, spec={"filters": [title_filter]}))
        return ""

    response = agent.ask(analyze, message=message)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "ok"
    assert body["result"]["applied_query"]["filters"] == [title_filter]
    assert body["turn"]["run_ids"] == [body["result"]["query_run_id"]]
    assert_persisted(agent, turns=1, runs=1)
