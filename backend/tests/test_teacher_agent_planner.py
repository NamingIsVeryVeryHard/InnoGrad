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


def tool_event(kind, call_id="first", **extra):
    return {"type": kind, "toolName": "query_papers", "toolCallId": call_id, **extra}


@pytest.fixture
def issue_token():
    return Mock(return_value=TOKEN)


@pytest.fixture
def pi_runtime(tmp_path, issue_token):
    grant_dir = tmp_path / "private"
    grant = grant_dir / SESSION
    deleted = []
    prompts = []

    def create(events, *, envelope_override=None, abort=False, existing_grant=False):
        def handle(req):
            path = req.url.path
            assert TOKEN not in str(req.url) + str(req.headers.raw) + req.content.decode()
            if req.method == "DELETE":
                if not existing_grant:
                    assert not grant.exists()
                deleted.append(path)
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
            return httpx.Response(200, text=stream + "data: [DONE]\n\n")

        return InnoAgentQueryPlanner(TeacherAgentConfig("innoagent", "https://teacher.example", grant_dir=str(grant_dir)),
                                     transport=httpx.MockTransport(handle))

    return create, grant, deleted, prompts


def test_multi_query_returns_only_final_delta_and_preserves_authorized_context(pi_runtime, issue_token, caplog):
    caplog.set_level("INFO", logger="httpx")
    create, grant, deleted, prompts = pi_runtime
    answer = "李同学已发表 [real-run:paper_record_count] 篇。[real-run]"
    events = []
    for call_id in ("compare-a", "compare-b"):
        events.extend([
            {"type": "text_delta", "delta": "intermediate"},
            {"type": "tool_call_start", "contentIndex": 0},
            tool_event("tool_call_delta", "content-0", toolName="query_"),
            tool_event("tool_call_end", call_id),
            tool_event("tool_start", call_id), tool_event("tool_end", call_id, isError=False),
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
    ([{"type": "text_delta", "delta": "unfinished"}], PlannerUnavailableError),
    ([{"type": "permission_request"}], PlannerUnavailableError),
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
    with pytest.raises(PlannerUnavailableError):
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
