import json
import stat
from datetime import date
from unittest.mock import Mock

import httpx
import pytest

from app.teacher_agent.contract import (
    PaperQuerySpec,
    PaperTimeRange,
    PublicationStatusFilter,
    StudentNameFilter,
    StudentIdFilter,
    export_paper_tool_input_schema,
)
from app.teacher_agent.errors import (
    PlannerConfigError,
    PlannerInvalidOutputError,
    PlannerUnavailableError,
)
from app.teacher_agent.planner import (
    CLARIFY,
    INSTRUCTIONS,
    ChatCompletionQueryPlanner,
    InnoAgentQueryPlanner,
    PlanRequest,
    RuleQueryPlanner,
    TeacherAgentConfig,
    build_planner,
    teacher_agent_config,
)


TODAY = date(2026, 11, 19)


def request(message, previous_spec=None, enabled_domains=("paper",)):
    return PlanRequest(message, previous_spec, TODAY, enabled_domains)


def test_rules_use_selected_student_and_portrait_clears_inherited_grouping():
    planner = RuleQueryPlanner()
    previous = PaperQuerySpec(
        filters=[StudentIdFilter(value="selected-student")],
        group_by=["publication_status"],
    )

    result = planner.plan(request("查看指定学生的画像", previous))

    assert planner.mode == "rules"
    assert result.trace.mode == "rules"
    assert result.output.action == "replace"
    assert result.output.spec.operation == "portrait"
    assert result.output.spec.group_by == []
    assert result.output.spec.filters[0].value == "selected-student"


def test_rules_keep_previous_personal_filter_as_sentinel_in_planner_input():
    planner = RuleQueryPlanner()
    previous = PaperQuerySpec(
        filters=[StudentIdFilter(value="student-actual-id")],
        group_by=["publication_status"],
    )

    result = planner.plan(request("只看已发表的论文名单", previous))

    assert result.output.action == "patch"
    assert result.output.patch.set_filters[0].value == "published"
    assert result.output.patch.group_by == []


def test_rules_grouping_by_publication_status_does_not_filter_to_published():
    planner = RuleQueryPlanner()

    result = planner.plan(request("按发表状态分组统计论文"))

    assert result.output.action == "replace"
    assert result.output.spec.filters == []
    assert result.output.spec.group_by == ["publication_status"]


def test_rules_all_publication_statuses_do_not_filter_to_published():
    planner = RuleQueryPlanner()

    result = planner.plan(request("按发表状态分组统计所有论文"))

    assert result.output.action == "replace"
    assert result.output.spec.filters == []


def test_rules_explicit_published_filter_survives_publication_status_grouping():
    planner = RuleQueryPlanner()

    result = planner.plan(request("按发表状态分组统计已发表论文"))

    assert result.output.spec.group_by == ["publication_status"]
    assert result.output.spec.filters[0].value == "published"


def test_rules_followup_degree_filter_preserves_publication_status_grouping():
    planner = RuleQueryPlanner()
    previous = planner.plan(request("今年论文发表情况")).output.spec

    result = planner.plan(request("只看博士", previous))

    assert result.output.action == "patch"
    assert result.output.patch.set_filters[0].field == "degree"
    assert result.output.patch.set_filters[0].value == "博士"
    assert result.output.patch.time_range is None
    assert result.output.patch.group_by is None


def test_rules_emit_only_fixed_unsupported_and_clarification_sentences():
    planner = RuleQueryPlanner()

    unsupported = planner.plan(request("查看奖学金申请情况"))
    clarify = planner.plan(request("帮我看看"))

    assert unsupported.output.message == "当前仅支持论文查询，暂未开放奖学金查询。"
    assert clarify.output.message == CLARIFY


def test_explicit_modes_do_not_fallback(monkeypatch):
    monkeypatch.setenv("TEACHER_AGENT_MODE", "chat")
    monkeypatch.delenv("TEACHER_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)

    with pytest.raises(PlannerConfigError):
        build_planner()

    monkeypatch.setenv("TEACHER_AGENT_MODE", "unknown")
    with pytest.raises(PlannerConfigError):
        teacher_agent_config()


def test_chat_repair_is_one_turn_and_sanitizes_fixed_text():
    responses = [
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"action":"replace","spec":{}}'}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "action": "replace",
            "spec": PaperQuerySpec(
                time_range=PaperTimeRange(date_from="2026-01-01", date_to="2026-12-31"),
            ).model_dump(by_alias=True),
        }, ensure_ascii=False)}}]},
    ]
    prompts = []

    def handler(request):
        body = json.loads(request.content)
        prompts.append(body["messages"])
        return httpx.Response(200, json=responses.pop(0))

    planner = ChatCompletionQueryPlanner(
        TeacherAgentConfig("chat", "https://planner.example", "synthetic"),
        transport=httpx.MockTransport(handler),
    )

    result = planner.plan(request("今年论文发表情况"))

    assert result.trace.repair_attempts == 1
    assert len(prompts) == 2
    assert prompts[1][-1]["content"].startswith("上一轮缺少唯一有效的结构化计划")
    assert INSTRUCTIONS in prompts[0][0]["content"]


def test_innoagent_prompt_references_optional_visual_html_guidance(pi_runtime, issue_token):
    create, _, _, prompts = pi_runtime
    events = [*successful_attempt("visual"), {"type": "text_delta", "delta": "结论。"}, {"type": "done"}]

    create(events).analyze(request("今年论文发表情况"), issue_token)

    assert "Optional visual HTML" in prompts[0]
    assert "visual-html" in prompts[0]


def test_chat_invalid_output_maps_to_502_error_after_repair():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"action":"replace","spec":{}}'}}],
        })

    planner = ChatCompletionQueryPlanner(
        TeacherAgentConfig("chat", "https://planner.example", "synthetic"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PlannerInvalidOutputError) as exc_info:
        planner.plan(request("今年论文发表情况"))
    assert exc_info.value.code == "INVALID_PLANNER_OUTPUT"


def test_external_status_and_transport_errors_map_to_503():
    def unavailable_handler(request):
        return httpx.Response(503, headers={"Retry-After": "2"})

    planner = ChatCompletionQueryPlanner(
        TeacherAgentConfig("chat", "https://planner.example", "synthetic"),
        transport=httpx.MockTransport(unavailable_handler),
    )

    with pytest.raises(PlannerUnavailableError) as exc_info:
        planner.plan(request("今年论文发表情况"))
    assert exc_info.value.code == "PLANNER_UNAVAILABLE"
    assert exc_info.value.retry_after_seconds == 1


def test_default_requires_dedicated_pi_and_grant_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("TEACHER_AGENT_MODE", raising=False)
    monkeypatch.delenv("TEACHER_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("TEACHER_AGENT_GRANT_DIR", raising=False)
    monkeypatch.delenv("TEACHER_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("TEACHER_AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("AI_BASE_URL", "https://review.example")
    monkeypatch.setenv("AI_API_KEY", "review-only")
    with pytest.raises(PlannerConfigError):
        build_planner()
    monkeypatch.setenv("TEACHER_AGENT_BASE_URL", "https://teacher.example")
    with pytest.raises(PlannerConfigError):
        build_planner()
    monkeypatch.setenv("TEACHER_AGENT_GRANT_DIR", str(tmp_path))
    config, key = teacher_agent_config()
    assert config.timeout_seconds == 120
    assert (config.mode, config.base_url, config.grant_dir, key) == ("innoagent", "https://teacher.example", str(tmp_path), "")
    monkeypatch.setenv("TEACHER_AGENT_BASE_URL", "https://review.example")
    with pytest.raises(PlannerConfigError):
        build_planner()


def test_innoagent_requires_disabled_memory():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/settings":
            return httpx.Response(200, json={"memory": {"l1Enabled": True, "l2Enabled": False, "l3Enabled": False}})
        return httpx.Response(500)

    planner = InnoAgentQueryPlanner(
        TeacherAgentConfig("innoagent", "http://127.0.0.1:3108", "synthetic", allow_internal_http=False),
        transport=httpx.MockTransport(handler),
    )

    issue_token = Mock()
    with pytest.raises(PlannerConfigError):
        planner.analyze(request("今年论文发表情况"), issue_token)
    issue_token.assert_not_called()
    assert calls == ["/api/settings"]


SESSION = "2026-11-19T08-00-00-000Z_9d512c36-7fd8-474c-8720-6ecc52e30f26.jsonl"
TOKEN = "test-only-private-capability"
PROXY_ARGS = {"server": "innograd_teacher", "tool": "query_papers", "args": {"spec": {}}}


def tool_event(kind, call_id="first", **extra):
    return {
        "type": kind, "toolName": "mcp", "toolCallId": call_id,
        **({"args": PROXY_ARGS} if kind in ("tool_start", "tool_call_end") else {}), **extra,
    }


def mcp_result(*, is_error=False, **structured):
    return {"details": {
        "mode": "call", "server": "innograd_teacher", "tool": "query_papers",
        **({"error": "tool_error"} if is_error else {}),
        "mcpResult": {"isError": is_error, "structuredContent": structured},
    }}


@pytest.fixture
def issue_token():
    return Mock(return_value=TOKEN)


@pytest.fixture
def pi_runtime(tmp_path, issue_token):
    grant_dir = tmp_path / "private"
    grant = grant_dir / SESSION
    deleted = []
    prompts = []

    def create(events, *, envelope_override=None, abort=False, existing_grant=False,
               cleanup_unavailable=False, close_early=False):
        def handle(req):
            path = req.url.path
            assert TOKEN not in str(req.url) + str(req.headers.raw) + req.content.decode()
            if req.method == "DELETE":
                if not existing_grant:
                    assert not grant.exists()
                deleted.append(path)
                if cleanup_unavailable and path == f"/api/sessions/{SESSION}":
                    return httpx.Response(503)
                if abort and deleted == [f"/api/sessions/{SESSION}"]:
                    return httpx.Response(409)
                if path == "/api/workspaces/workspace":
                    assert req.url.params["removeFiles"] == "1"
                return httpx.Response(204)
            if path == "/api/settings":
                return httpx.Response(200, json={"memory": dict.fromkeys(("l1Enabled", "l2Enabled", "l3Enabled"), False)})
            if path == f"/api/chat/status/{SESSION}":
                return httpx.Response(200, json={"stream": {"turnId": "turn"}})
            if path == f"/api/chat/{SESSION}/turn/abort":
                deleted.append("aborted")
                return httpx.Response(202, json={"cancelRequested": True})
            body = json.loads(req.content)
            if path == "/api/workspaces":
                assert body["isTemp"] is False
                return httpx.Response(201, json={**body, "id": "workspace"})
            if path == "/api/sessions":
                issue_token.assert_not_called()
                assert body["workspaceId"] == "workspace"
                return httpx.Response(201, json={**body, "id": SESSION})
            assert path == "/api/chat/stream"
            issue_token.assert_called_once_with()
            assert grant.read_text() == TOKEN
            assert stat.S_IMODE(grant.stat().st_mode) == 0o600
            assert stat.S_IMODE(grant_dir.stat().st_mode) == 0o700
            prompts.append(body["prompt"])
            envelope = {"sessionId": body["sessionId"], "clientRequestId": body["clientRequestId"], **(envelope_override or {})}
            stream = "".join(f"data: {json.dumps({**envelope, 'event': event})}\n\n" for event in events)
            return httpx.Response(200, text=stream if close_early else stream + "data: [DONE]\n\n")

        return InnoAgentQueryPlanner(TeacherAgentConfig("innoagent", "https://teacher.example", grant_dir=str(grant_dir)),
                                     transport=httpx.MockTransport(handle))

    return create, grant, deleted, prompts


def parameter_attempt(call_id, *, local=False):
    result = {
        "content": [{"type": "text", "text": (
            'Validation failed for tool "mcp":\n'
            '  - /args: Expected object\n\nReceived arguments:\n{}'
        )}],
        "details": {},
    } if local else mcp_result(is_error=True, code="RETRYABLE_TOOL_INPUT")
    return [
        tool_event("tool_call_end", call_id),
        tool_event("tool_start", call_id),
        tool_event("tool_end", call_id, isError=True, result=result),
    ]


def successful_attempt(call_id):
    return [
        tool_event("tool_call_end", call_id),
        tool_event("tool_start", call_id),
        tool_event("tool_end", call_id, isError=False, result=mcp_result(query_run_id=f"run-{call_id}")),
    ]


def test_innoagent_prompt_exposes_mcp_domain_fields_and_enums(pi_runtime, issue_token):
    create, _, _, prompts = pi_runtime
    events = [*successful_attempt("query"), {"type": "text_delta", "delta": "结果。"}, {"type": "done"}]

    create(events).analyze(request("论文"), issue_token)

    hint, = [value for line in prompts[0].splitlines() if line.startswith("{")
             and "filter_fields" in (value := json.loads(line))]
    definitions = export_paper_tool_input_schema()["$defs"]
    spec = definitions["PaperQuerySpec"]["properties"]
    assert set(hint["spec_fields"]) == spec.keys()
    assert set(hint["patch_fields"]) == definitions["QueryPatch"]["properties"].keys()
    assert hint["time_range"] == {
        "from": "YYYY-MM-DD", "to": "YYYY-MM-DD",
        "field": definitions["PaperTimeRange"]["properties"]["field"]["enum"],
    }
    assert hint["operation"] == spec["operation"]["enum"]
    assert hint["group_by"] == spec["group_by"]["items"]["enum"]
    assert hint["filter_fields"]["publication_status"] == {
        "operator": ["eq", "neq", "in"], "value": ["submitted", "accepted", "published"],
    }
    assert hint["filter_fields"]["degree"]["value"] == ["博士", "硕士", "未标注"]
    assert hint["filter_fields"]["has_doi"] == {"operator": ["eq"], "value": "boolean"}
    assert "$defs" not in hint


def test_adapter_schema_validation_error_can_be_corrected_in_same_stream(pi_runtime, issue_token):
    create, _, _, _ = pi_runtime
    events = [
        tool_event("tool_start", "wrong"),
        tool_event("tool_end", "wrong", isError=True, result={
            "content": [{"type": "text", "text": (
                "Failed to call tool: data/spec/time_range/field must be equal to one of the allowed values"
                "\n\nExpected parameters:\n  spec"
            )}],
            "details": {
                "mode": "call", "error": "call_failed", "server": "innograd_teacher",
                "tool": "query_papers",
                "message": "data/spec/time_range/field must be equal to one of the allowed values",
            },
        }),
        *successful_attempt("corrected"),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]

    assert create(events).analyze(request("论文"), issue_token) == "结果。"


@pytest.mark.parametrize("local", [False, True])
def test_parameter_error_can_be_corrected_in_same_stream(pi_runtime, issue_token, local):
    create, grant, _, prompts = pi_runtime
    answer = "待审论文有 [corrected:paper_record_count] 篇。"
    events = [
        *parameter_attempt("wrong", local=local),
        {"type": "text_delta", "delta": "intermediate"},
        *successful_attempt("corrected"),
        {"type": "text_delta", "delta": answer},
        {"type": "done"},
    ]
    assert create(events).analyze(request("论文"), issue_token) == answer
    assert len(prompts) == 1
    issue_token.assert_called_once_with()
    assert not grant.exists()


@pytest.mark.parametrize("errors", [2, 3])
def test_local_and_callback_errors_share_retry_budget(pi_runtime, issue_token, errors):
    create, _, _, _ = pi_runtime
    events = [
        event
        for index in range(errors)
        for event in parameter_attempt(str(index), local=index % 2 == 1)
    ]
    for index in range(5):
        events.extend(successful_attempt(f"success-{index}"))
    events.extend([{"type": "text_delta", "delta": "结果。"}, {"type": "done"}])
    planner = create(events)
    if errors == 2:
        assert planner.analyze(request("论文"), issue_token) == "结果。"
    else:
        with pytest.raises(PlannerInvalidOutputError, match="纠错次数"):
            planner.analyze(request("论文"), issue_token)


def test_configured_query_budget_applies_to_prompt_and_stream(pi_runtime, issue_token, monkeypatch):
    from app.teacher_agent.budget import TurnBudget

    create, _, _, prompts = pi_runtime
    monkeypatch.setenv("TEACHER_AGENT_MAX_QUERIES", "1")
    events = [
        *successful_attempt("first"),
        *successful_attempt("second"),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]
    turn = PlanRequest("论文", None, TODAY, budget=TurnBudget.from_env())
    with pytest.raises(PlannerInvalidOutputError, match="查询次数"):
        create(events).analyze(turn, issue_token)
    assert "最多 1 次成功查询" in prompts[0]


def test_clarification_uses_neither_a_card_nor_a_tool_retry(pi_runtime, issue_token):
    create, _, _, _ = pi_runtime
    clarification = tool_event("tool_end", "ask", isError=False, result=mcp_result(code="CLARIFICATION_NEEDED"))
    events = [tool_event("tool_start", "ask"), clarification]
    events.extend(parameter_attempt("wrong"))
    events.extend(parameter_attempt("local", local=True))
    for index in range(5):
        events.extend(successful_attempt(f"success-{index}"))
    events.extend([{"type": "text_delta", "delta": "结果。"}, {"type": "done"}])
    assert create(events).analyze(request("论文"), issue_token) == "结果。"


@pytest.mark.parametrize("code", ["NOT_FOUND", "CONVERSATION_CHANGED", "INVALID_PLANNER_OUTPUT"])
def test_unmarked_callback_error_is_fatal_even_if_corrected_later(pi_runtime, issue_token, code):
    create, _, _, _ = pi_runtime
    events = [
        tool_event("tool_start", "denied"),
        tool_event("tool_end", "denied", isError=True, result={
            "content": [{"type": "text", "text": f"Failed to call tool: {code}\n\nExpected parameters:\n  spec"}],
            "details": {"mode": "call", "error": "call_failed", "server": "innograd_teacher",
                        "tool": "query_papers", "message": code},
        }),
        *successful_attempt("corrected"),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]
    with pytest.raises(PlannerInvalidOutputError):
        create(events).analyze(request("论文"), issue_token)


@pytest.mark.parametrize("args", [
    {**PROXY_ARGS, "extra": True},
    {**PROXY_ARGS, "server": "other"},
    {**PROXY_ARGS, "tool": "other"},
    {"server": "innograd_teacher", "tool": "query_papers"},
])
def test_mcp_requires_exact_outer_target(pi_runtime, issue_token, args):
    create, _, _, _ = pi_runtime
    events = [
        tool_event("tool_call_end", args=args),
        *successful_attempt("first"),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]
    with pytest.raises(PlannerInvalidOutputError, match="工具参数"):
        create(events).analyze(request("论文"), issue_token)


@pytest.mark.parametrize("args", [
    {**PROXY_ARGS, "args": '{"spec":{},"patch":{}}'},
    {**PROXY_ARGS, "args": '{"spec":{},"extra":{}}'},
    {**PROXY_ARGS, "args": '{"spec":null}'},
    {**PROXY_ARGS, "args": '{"spec":{"page":NaN}}'},
    {**PROXY_ARGS, "args": '{"spec":'},
    {**PROXY_ARGS, "args": {"patch": {}, "extra": {}}},
    {**PROXY_ARGS, "args": []},
])
def test_malformed_mcp_arguments_cannot_produce_a_successful_result(pi_runtime, issue_token, args):
    create, _, _, _ = pi_runtime
    events = [
        tool_event("tool_call_end", args=args),
        tool_event("tool_start", args=args),
        tool_event("tool_end", isError=False, result=mcp_result(query_run_id="run-first")),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]
    with pytest.raises(PlannerInvalidOutputError, match="工具参数"):
        create(events).analyze(request("论文"), issue_token)


@pytest.mark.parametrize(("inner", "message"), [
    ({"spec": {}, "patch": {}}, "data must NOT have more than 1 properties"),
    ("{}", "data must NOT have fewer than 1 properties"),
    ('{"spec":', None),
])
def test_bad_inner_mcp_shape_can_be_repaired_after_success(pi_runtime, issue_token, inner, message):
    create, _, _, _ = pi_runtime
    arguments = {**PROXY_ARGS, "args": inner}
    result = {
        "content": [{"type": "text", "text": (
            f"Failed to call tool: {message}\n\nExpected parameters:\n  spec\n  patch"
            if message else "TEACHER_QUERY_ARGS_INVALID: args 必须是 JSON 对象或其 JSON 字符串，并且只含一个 spec 或 patch 对象。"
        )}],
        "details": {
            "mode": "call", "error": "call_failed", "server": "innograd_teacher",
            "tool": "query_papers", "message": message,
        } if message else {},
    }
    events = [
        *successful_attempt("first"),
        tool_event("tool_call_end", "wrong", args=arguments),
        tool_event("tool_start", "wrong", args=arguments),
        tool_event("tool_end", "wrong", isError=True, result=result),
        *successful_attempt("corrected"),
        {"type": "text_delta", "delta": "本年 [run-first:paper_record_count] 篇，去年 [run-corrected:paper_record_count] 篇。"},
        {"type": "done"},
    ]
    assert create(events).analyze(request("论文"), issue_token) == events[-2]["delta"]


@pytest.mark.parametrize("key", ["spec", "patch"])
def test_mcp_accepts_model_json_encoding_of_query_arguments(pi_runtime, issue_token, key):
    create, _, _, _ = pi_runtime
    arguments = {**PROXY_ARGS, "args": json.dumps({key: {}})}
    events = [
        tool_event("tool_call_end", args=arguments),
        tool_event("tool_start", args=arguments),
        tool_event("tool_end", isError=False, result=mcp_result(query_run_id="run-first")),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]
    assert create(events).analyze(request("论文"), issue_token) == "结果。"


@pytest.mark.parametrize(("is_error", "result"), [
    (False, {"details": {"mode": "call", "error": "aborted"}}),
    (False, mcp_result()),
    (False, mcp_result(code="RETRYABLE_TOOL_INPUT")),
    (True, mcp_result(is_error=True, code="CLARIFICATION_NEEDED")),
    (True, mcp_result(is_error=True, code="UNRECOGNIZED")),
])
def test_mcp_tool_end_requires_matching_receipt_and_error_flag(pi_runtime, issue_token, is_error, result):
    create, _, _, _ = pi_runtime
    events = [
        tool_event("tool_start"),
        tool_event("tool_end", isError=is_error, result=result),
        {"type": "text_delta", "delta": "结果。"},
        {"type": "done"},
    ]
    with pytest.raises(PlannerInvalidOutputError):
        create(events).analyze(request("论文"), issue_token)


def test_terminal_tool_error_survives_cleanup_unavailability(pi_runtime, issue_token):
    create, grant, deleted, _ = pi_runtime
    events = [
        tool_event("tool_start"),
        tool_event("tool_end", isError=True, result={
            "content": [{"type": "text", "text": "Paper query failed."}],
            "details": {},
        }),
    ]
    with pytest.raises(PlannerInvalidOutputError):
        create(events, cleanup_unavailable=True).analyze(request("论文"), issue_token)
    assert not grant.exists()
    assert deleted == [f"/api/sessions/{SESSION}", "/api/workspaces/workspace"]


def test_transport_ending_without_terminal_event_remains_retryable(pi_runtime, issue_token):
    create, _, _, _ = pi_runtime
    with pytest.raises(PlannerUnavailableError):
        create([{"type": "text_delta", "delta": "unfinished"}], close_early=True).analyze(request("论文"), issue_token)


def test_turn_budget_reads_defaults_and_overrides(monkeypatch):
    from app.teacher_agent.budget import TurnBudget

    for name in ("MAX_QUERIES", "MAX_TOOL_RETRIES", "MAX_TURN_RETRIES"):
        monkeypatch.delenv(f"TEACHER_AGENT_{name}", raising=False)
    assert TurnBudget.from_env() == TurnBudget(5, 2, 1)
    monkeypatch.setenv("TEACHER_AGENT_MAX_QUERIES", "8")
    monkeypatch.setenv("TEACHER_AGENT_MAX_TOOL_RETRIES", "0")
    monkeypatch.setenv("TEACHER_AGENT_MAX_TURN_RETRIES", "3")
    assert TurnBudget.from_env() == TurnBudget(8, 0, 3)
    monkeypatch.setenv("TEACHER_AGENT_MAX_QUERIES", "0")
    with pytest.raises(PlannerConfigError):
        TurnBudget.from_env()


def test_multi_query_returns_only_final_delta_and_preserves_authorized_context(pi_runtime, issue_token, caplog):
    caplog.set_level("INFO", logger="httpx")
    create, grant, deleted, prompts = pi_runtime
    answer = "李同学已发表 [real-run:paper_record_count] 篇。[real-run]"
    events = []
    for call_id in ("compare-a", "compare-b"):
        events.extend([
            {"type": "text_delta", "delta": "intermediate"},
            {"type": "tool_call_start", "contentIndex": 0},
            tool_event("tool_call_delta", "content-0", toolName="mc"),
            *successful_attempt(call_id),
        ])
    events.extend([
        {"type": "thinking_delta", "delta": "private reasoning"},
        {"type": "text_delta", "delta": "abandoned answer"},
        {"type": "system_event", "eventType": "message_start"},
        {"type": "text_delta", "delta": answer[:5]}, {"type": "text_delta", "delta": answer[5:]},
        {"type": "done", "fullText": "includes intermediate text"},
    ])
    question = "对比李同学的投稿和发表情况"
    previous = PaperQuerySpec(filters=[StudentNameFilter(value="李同学")])
    assert create(events).analyze(request(question, previous), issue_token) == answer
    issue_token.assert_called_once_with()
    assert prompts[0].startswith("/skill:teacher-query-planner ")
    payload = json.loads(prompts[0].splitlines()[-1])
    assert payload["user_message"] == question
    assert payload["previous_spec"] == previous.model_dump(mode="json", by_alias=True)
    assert deleted == [f"/api/sessions/{SESSION}", "/api/workspaces/workspace"]
    assert list(grant.parent.iterdir()) == []
    assert TOKEN not in caplog.text


def test_no_query_can_return_clarification(pi_runtime, issue_token):
    create, _, _, _ = pi_runtime
    events = [{"type": "text_delta", "delta": "请指定查询时间。"}, {"type": "done"}]
    assert create(events).analyze(request("看看"), issue_token) == "请指定查询时间。"


@pytest.mark.parametrize(("events", "error"), [
    ([tool_event("tool_call_start", toolName="read")], PlannerConfigError),
    ([tool_event("tool_end", isError=False)], PlannerInvalidOutputError),
    ([tool_event("tool_start"), tool_event("tool_end", "unmatched", isError=False)], PlannerInvalidOutputError),
    ([tool_event("tool_start"), tool_event("tool_start")], PlannerInvalidOutputError),
    ([tool_event("tool_start"), tool_event("tool_end", isError=True)], PlannerInvalidOutputError),
    ([tool_event("tool_start"), {"type": "done"}], PlannerInvalidOutputError),
    ([tool_event("tool_call_end"), {"type": "text_delta", "delta": "unexecuted"}, {"type": "done"}], PlannerInvalidOutputError),
    ([tool_event("tool_start", str(number)) for number in range(6)], PlannerInvalidOutputError),
    ([{"type": "done", "fullText": "no final deltas"}], PlannerInvalidOutputError),
    ([{"type": "text_delta", "delta": "unfinished"}], PlannerInvalidOutputError),
    ([{"type": "permission_request"}], PlannerInvalidOutputError),
    ([{"type": "aborted"}], PlannerInvalidOutputError),
    ([{"type": "question"}], PlannerInvalidOutputError),
])
def test_invalid_event_aborts_active_turn_and_removes_private_resources(pi_runtime, issue_token, events, error):
    create, grant, deleted, _ = pi_runtime
    with pytest.raises(error):
        create(events, abort=True).analyze(request("论文"), issue_token)
    assert list(grant.parent.iterdir()) == []
    assert deleted == [f"/api/sessions/{SESSION}", "aborted", f"/api/sessions/{SESSION}", "/api/workspaces/workspace"]


@pytest.mark.parametrize("field", ["sessionId", "clientRequestId"])
def test_mismatched_envelope_is_rejected(pi_runtime, issue_token, field):
    create, _, _, _ = pi_runtime
    with pytest.raises(PlannerInvalidOutputError):
        create([{"type": "done"}], envelope_override={field: "different"}).analyze(request("论文"), issue_token)


def test_grant_creation_is_exclusive_and_preserves_existing_file(pi_runtime, issue_token):
    create, grant, deleted, _ = pi_runtime
    grant.parent.mkdir(mode=0o700)
    grant.write_text("other-owner")
    with pytest.raises(PlannerConfigError):
        create([], existing_grant=True).analyze(request("论文"), issue_token)
    assert grant.read_text() == "other-owner"
    assert list(grant.parent.iterdir()) == [grant]
    assert deleted == [f"/api/sessions/{SESSION}", "/api/workspaces/workspace"]


def test_public_grant_directory_fails_before_streaming(pi_runtime, issue_token):
    create, grant, _, prompts = pi_runtime
    grant.parent.mkdir()
    grant.parent.chmod(0o755)
    with pytest.raises(PlannerConfigError):
        create([]).analyze(request("论文"), issue_token)
    issue_token.assert_not_called()
    assert list(grant.parent.iterdir()) == []
    assert prompts == []


def test_issuance_failure_cleans_up_ready_session(pi_runtime, issue_token):
    create, grant, deleted, prompts = pi_runtime
    issue_token.side_effect = RuntimeError("issuance failed")
    with pytest.raises(RuntimeError, match="issuance failed"):
        create([]).analyze(request("论文"), issue_token)
    issue_token.assert_called_once_with()
    assert list(grant.parent.iterdir()) == []
    assert deleted == [f"/api/sessions/{SESSION}", "/api/workspaces/workspace"]
    assert prompts == []
