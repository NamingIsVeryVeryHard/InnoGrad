import pytest

from app.teacher_agent.contract import METRIC_CATALOG, MetricCard, PaperQuerySpec, ResultEnvelope
from app.teacher_agent.visual import MAX_VISUAL_HTML_BYTES, extract_visual_artifact
from test_teacher_agent_conversations import CONVERSATIONS
from test_teacher_agent_tools import agent, clock, env, tool_result  # noqa: F401


def _ok_result(run_id="run-1"):
    definition = METRIC_CATALOG["paper_record_count"]
    return ResultEnvelope(
        query_run_id=run_id,
        applied_query=PaperQuerySpec(operation="aggregate", group_by=["publication_status"]),
        summary={
            "headline": "当前有效归档中有 5 条符合条件的论文申报记录，涉及 2 名学生。",
            "metrics": [
                MetricCard(
                    key=definition.key,
                    label=definition.label,
                    value=5,
                    unit=definition.unit,
                    subject=definition.subject,
                )
            ],
            "breakdown": [],
            "data_as_of": "2026-11-22",
            "basis": "current_effective_archives",
            "scope_student_count": 2,
            "notice": "",
        },
        pagination={"page": 1, "page_size": 50, "total": 5, "has_more": False},
    )


def test_extracts_valid_visual_block_and_strips_it_from_prose():
    raw = (
        "今年共有 [run-1:paper_record_count] 篇论文申报。\n\n"
        '```visual-html title="2026年论文分布"\n'
        '<div id="app"></div>\n'
        "<script>\n"
        "// harmless JS comment should be allowed\n"
        "const data = window.__INNOGRAD_DATA__;\n"
        "document.getElementById('app').textContent = data.runs[0].title;\n"
        "</script>\n"
        "```\n"
    )
    extracted = extract_visual_artifact(raw, [_ok_result("run-1")])
    assert extracted.dropped_reason is None
    assert extracted.prose == "今年共有 [run-1:paper_record_count] 篇论文申报。"
    assert extracted.visual is not None
    assert extracted.visual.kind == "html_sandbox"
    assert extracted.visual.title == "2026年论文分布"
    assert extracted.visual.source_run_ids == ["run-1"]
    assert "__INNOGRAD_DATA__" in extracted.visual.html


def test_returns_prose_unchanged_when_no_visual_block_present():
    raw = "今年共有 [run-1:paper_record_count] 篇论文申报。"
    extracted = extract_visual_artifact(raw, [_ok_result("run-1")])
    assert extracted.prose == raw
    assert extracted.visual is None
    assert extracted.dropped_reason is None


def test_drops_visual_without_data_binding_and_keeps_prose():
    raw = (
        "今年共有 [run-1:paper_record_count] 篇。\n"
        "```visual-html\n<div>硬编码 5 篇论文</div>\n```"
    )
    extracted = extract_visual_artifact(raw, [_ok_result("run-1")])
    assert extracted.prose == "今年共有 [run-1:paper_record_count] 篇。"
    assert extracted.visual is None
    assert extracted.dropped_reason == "missing_data_binding"


def test_drops_multiple_visual_blocks_and_empty_or_oversized_blocks():
    block = "```visual-html\n<script>console.log(window.__INNOGRAD_DATA__)</script>\n```"
    multi = extract_visual_artifact(f"结论。\n{block}\n{block}", [_ok_result()])
    assert multi.visual is None
    assert multi.dropped_reason == "multiple_visual_blocks"
    assert multi.prose == "结论。"

    empty = extract_visual_artifact("```visual-html\n   \n```", [_ok_result()])
    assert empty.visual is None
    assert empty.dropped_reason == "empty_html"

    oversized_body = "window.__INNOGRAD_DATA__;" + ("a" * MAX_VISUAL_HTML_BYTES)
    oversized = extract_visual_artifact(f"```visual-html\n<script>{oversized_body}</script>\n```", [_ok_result()])
    assert oversized.visual is None
    assert oversized.dropped_reason == "html_too_large"


def test_drops_visual_when_no_verified_ok_results():
    clarification = ResultEnvelope(status="clarification_needed", clarification={"message": "请明确学生"})
    raw = "```visual-html\n<script>window.__INNOGRAD_DATA__</script>\n```"
    extracted = extract_visual_artifact(raw, [clarification])
    assert extracted.visual is None
    assert extracted.dropped_reason == "no_verified_results"


@pytest.mark.parametrize(("name", "snippet"), [
    ("external_url", '<img src="https://evil.example/leak.png"><script>window.__INNOGRAD_DATA__</script>'),
    ("protocol_relative_attr", '<img src="//evil.example/leak.png"><script>window.__INNOGRAD_DATA__</script>'),
    ("css_import", '<style>@import "x.css";</style><script>window.__INNOGRAD_DATA__</script>'),
    ("script_src", '<script src="/evil.js">window.__INNOGRAD_DATA__</script>'),
    ("meta_tag", '<meta http-equiv="refresh" content="0"><script>window.__INNOGRAD_DATA__</script>'),
    ("base_tag", '<base href="/"><script>window.__INNOGRAD_DATA__</script>'),
    ("nested_embed", '<iframe></iframe><script>window.__INNOGRAD_DATA__</script>'),
    ("nested_embed", '<form></form><script>window.__INNOGRAD_DATA__</script>'),
    ("storage_or_cookie", "<script>document.cookie; window.__INNOGRAD_DATA__</script>"),
    ("storage_or_cookie", "<script>localStorage.getItem('x'); window.__INNOGRAD_DATA__</script>"),
    ("network_api", "<script>fetch('/api/v1/me'); window.__INNOGRAD_DATA__</script>"),
    ("network_api", "<script>new XMLHttpRequest(); window.__INNOGRAD_DATA__</script>"),
    ("frame_escape", "<script>window.top.location='x'; window.__INNOGRAD_DATA__</script>"),
    ("frame_escape", "<script>parent.postMessage({}, '*'); window.__INNOGRAD_DATA__</script>"),
])
def test_rejects_forbidden_patterns(name, snippet):
    raw = f"结论 [run-1]。\n```visual-html\n{snippet}\n```"
    extracted = extract_visual_artifact(raw, [_ok_result("run-1")])
    assert extracted.visual is None
    assert extracted.dropped_reason == f"forbidden_pattern:{name}"
    assert extracted.prose == "结论 [run-1]。"


def test_agent_turn_returns_initial_only_visual_alongside_grouped_prose(agent):
    def analyze(token):
        view = tool_result(agent.query(token, spec={"group_by": ["publication_status"]}))
        run_id = view["query_run_id"]
        return (
            f"今年共有 [{run_id}:paper_record_count] 篇论文。\n\n"
            '```visual-html title="发表状态分布"\n'
            '<canvas id="chart"></canvas>\n'
            "<script>const run = window.__INNOGRAD_DATA__.runs[0];</script>\n"
            "```"
        )

    reply = agent.ask(analyze, key="visual-grouped", message="今年论文发表情况")
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["analysis_notice"] is None
    assert payload["analysis"].startswith("各组统计请查看分组结果卡 [")
    assert payload["visual"]["kind"] == "html_sandbox"
    assert payload["visual"]["title"] == "发表状态分布"
    assert payload["visual"]["source_run_ids"] == payload["turn"]["run_ids"]
    assert "__INNOGRAD_DATA__" in payload["visual"]["html"]

    detail = agent.teacher.get(f"{CONVERSATIONS}/{agent.conversation}").json()
    assert "visual" not in detail
    assert "visual" not in detail["turns"][0]


def test_agent_turn_accepts_visual_only_without_unverified_notice(agent):
    def analyze(token):
        tool_result(agent.query(token, spec={"operation": "list"}))
        return (
            '```visual-html title="论文清单"\n'
            "<div id='list'></div><script>window.__INNOGRAD_DATA__</script>\n"
            "```"
        )

    reply = agent.ask(analyze, key="visual-only", message="列出今年论文")
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["analysis"] is None
    assert payload["analysis_notice"] is None
    assert payload["visual"]["title"] == "论文清单"


def test_agent_turn_drops_unsafe_visual_but_preserves_verified_prose(agent):
    def analyze(token):
        view = tool_result(agent.query(token, spec={"operation": "list"}))
        run_id = view["query_run_id"]
        return (
            f"共有 [{run_id}:paper_record_count] 篇论文。\n"
            "```visual-html\n<script>fetch('/api/v1/me'); window.__INNOGRAD_DATA__</script>\n```"
        )

    reply = agent.ask(analyze, key="visual-drop", message="列出论文")
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["visual"] is None
    assert payload["analysis_notice"] is None
    assert payload["analysis"] is not None
