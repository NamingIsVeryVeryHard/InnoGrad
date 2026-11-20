import pytest

from app.teacher_agent.planner import requests_scholarship
from test_teacher_agent_conversations import CONVERSATIONS, ROOT, question
from test_teacher_agent_tools import agent, assert_persisted, clock, tool_result
from test_workflow import env, post


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
