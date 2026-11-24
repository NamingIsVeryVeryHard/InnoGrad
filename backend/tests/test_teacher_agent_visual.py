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
    assert payload["analysis"] is None
    assert payload["result"]["query_run_id"] == payload["turn"]["run_ids"][0]
    assert "marker" not in reply.text


def test_clarification_strips_legacy_block_without_query_results(agent):
    question = "您想查看今年还是去年的论文？"
    reply = agent.ask(lambda _: f"{question}\n```visual-html\nmarker\n```")
    assert reply.status_code == 200, reply.text
    assert reply.json()["result"]["clarification"]["message"] == question
    assert "marker" not in reply.text
