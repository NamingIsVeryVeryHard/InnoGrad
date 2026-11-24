import json

import pytest

from test_teacher_agent_tools import agent, clock, env, tool_result  # noqa: F401
from test_workflow import submitted


def test_turn_strips_legacy_blocks_and_preserves_cited_analysis_and_evidence(agent, env):
    submission_id, *_ = submitted(env)

    def analyze(token):
        view = tool_result(agent.query(token, spec={
            "operation": "list", "basis": "submitted_latest", "include": ["metrics", "items", "sources"],
        }))
        run_id = view["query_run_id"]
        return (
            '```visual-html title="旧图表"\r\n__INNOGRAD_DATA__ marker\r\n```\r\n'
            f"共有 [{run_id}:paper_record_count] 篇论文。\n"
            "```visual-html\nsecond marker"
        )

    reply = agent.ask(analyze)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["visual"] is None
    assert payload["visual_spec"] is None
    assert payload["analysis_notice"] is None
    result = payload["result"]
    assert payload["results"] == [result]
    assert result["sources"]
    assert submission_id in [item["submission_id"] for item in result["items"]]
    assert payload["analysis"] == f"共有 1 [{result['query_run_id']}] 篇论文。"
    assert "marker" not in reply.text


def test_turn_with_only_legacy_block_returns_result_cards(agent):
    def analyze(token):
        tool_result(agent.query(token, spec={"operation": "list"}))
        return "```visual-html\n__INNOGRAD_DATA__ marker\n```"

    reply = agent.ask(analyze)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["visual"] is None
    assert payload["visual_spec"] is None
    assert payload["analysis"] is None
    assert payload["result"]["query_run_id"] == payload["turn"]["run_ids"][0]
    assert "marker" not in reply.text


def fenced(blocks, layout="grid"):
    return "```visual-spec\n" + json.dumps({"layout": layout, "blocks": blocks}) + "\n```"


def test_verified_multi_run_layout_only_on_initial_response(agent):
    def analyze(token):
        grouped = tool_result(agent.query(token, spec={"group_by": ["degree"]}))["query_run_id"]
        detail = tool_result(agent.query(token, spec={"operation": "list"}))["query_run_id"]
        return f"论文共 [{grouped}:paper_record_count] 篇。\n" + fenced([
            {"type": "bar", "title": "学生人数", "measure": "student_count", "interaction": "drilldown",
             "run_id": grouped},
            {"type": "donut", "run_id": grouped},
            {"type": "metrics", "run_id": grouped},
            {"type": "records", "interaction": "open_record", "run_id": detail},
            {"type": "timeline", "run_id": detail},
        ])

    reply = agent.ask(analyze)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    grouped, detail = payload["turn"]["run_ids"]
    assert payload["visual"] is None
    assert payload["visual_spec"]["layout"] == "grid"
    blocks = payload["visual_spec"]["blocks"]
    assert [block["run_id"] for block in blocks] == [grouped, grouped, grouped, detail, detail]
    assert blocks[0]["title"] == "学生人数"
    assert [block.get("measure") for block in blocks] == ["student_count", "record_count", None, None, None]
    assert [block["interaction"] for block in blocks] == ["drilldown", "none", "none", "open_record", "none"]
    replay = agent.ask(lambda _: pytest.fail("replay invoked planner"))
    assert replay.status_code == 200, replay.text
    assert replay.json()["visual_spec"] is None


@pytest.mark.parametrize("invalid", [
    {"type": "metrics", "measure": "record_count"}, {"type": "bar", "interaction": "open_record"},
    {"type": "records", "interaction": "drilldown"}, {"type": "timeline", "rows": [{"count": 999}]},
    {"type": "bar", "url": "https://example.org"}, {"type": "metrics", "title": "<b>论文</b>"},
    {"type": "bar", "title": "论文999篇"},
])
def test_invalid_visual_falls_back_to_verified_cards(agent, invalid):
    def analyze(token):
        run = tool_result(agent.query(token, spec={}))["query_run_id"]
        return f"共有 [{run}:paper_record_count] 篇论文。\n" + fenced([
            {"type": "metrics", "run_id": run}, {**invalid, "run_id": run},
        ])

    reply = agent.ask(analyze)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["visual_spec"] is None
    assert payload["results"] == [payload["result"]]
    assert payload["analysis"] and payload["analysis_notice"] is None


def test_previous_run_invalidates_entire_layout(agent):
    def first(token):
        run = tool_result(agent.query(token, spec={}))["query_run_id"]
        return fenced([{"type": "metrics", "run_id": run}], "stack")

    initial = agent.ask(first).json()
    stale = initial["visual_spec"]["blocks"][0]["run_id"]

    def second(token):
        current = tool_result(agent.query(token, spec={}))["query_run_id"]
        return fenced([{"type": "metrics", "run_id": current}, {"type": "metrics", "run_id": stale}])

    reply = agent.ask(second, key="next", version=initial["conversation_lock_version"])
    assert reply.status_code == 200, reply.text
    assert reply.json()["visual_spec"] is None
    assert reply.json()["result"]["query_run_id"] != stale


@pytest.mark.parametrize("fence", [
    "```visual-spec\n{broken}\n```",
    "```visual-spec\n{body}",
    "```visual-spec\n{body}\n```\n```visual-html\nmarker\n```",
    "```visual-spec\n{body}\n```\n```visual-spec\n{body}\n```",
])
def test_malformed_or_extra_fences_preserve_cited_text(agent, fence):
    def analyze(token):
        run = tool_result(agent.query(token, spec={}))["query_run_id"]
        body = json.dumps({"layout": "stack", "blocks": [{"type": "metrics", "run_id": run}]})
        return f"共有 [{run}:paper_record_count] 篇论文。\n" + fence.replace("{body}", body)

    reply = agent.ask(analyze)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["visual_spec"] is None
    assert payload["analysis"] and payload["analysis_notice"] is None
    assert "```" not in payload["analysis"]


def test_clarification_strips_legacy_block_without_query_results(agent):
    question = "您想查看今年还是去年的论文？"
    reply = agent.ask(lambda _: f"{question}\n```visual-html\nmarker\n```")
    assert reply.status_code == 200, reply.text
    assert reply.json()["result"]["clarification"]["message"] == question
    assert "marker" not in reply.text
