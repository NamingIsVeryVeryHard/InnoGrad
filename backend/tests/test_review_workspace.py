import base64
import json
from copy import deepcopy

import httpx
import pytest

from app.adapters.innoagent import InnoAgentAdapter
from app.agent import AgentResult, analyze
from app.material_rules import SKILL_ROOT
from app.review_errors import ReviewFailure
from app.review_workspace import ReviewWorkspace
from test_review_execution import check, package_with_pages


def read_events(bundle, path, *, offset=1, limit=None, truncated=None, error=False, text=None):
    lines = bundle.lines[path][offset - 1:]
    if limit:
        lines = lines[:limit]
    if truncated:
        lines = lines[:truncated["outputLines"]]
    return [
        {"type": "tool_start", "toolCallId": "call", "toolName": "read",
         "args": {"path": path, "offset": offset, **({"limit": limit} if limit else {})}},
        {"type": "tool_end", "toolCallId": "call", "toolName": "read", "isError": error,
         "result": {"content": [{"type": "text", "text": "\n".join(lines) if text is None else text}],
                    "details": {"truncation": truncated} if truncated else {}}},
    ]


def record(bundle, path, **kwargs):
    for event in read_events(bundle, path, **kwargs):
        bundle.record(event, "owned-workspace")


def test_complete_bundle_preserves_all_text_and_frozen_context():
    package = package_with_pages(23)
    original = deepcopy(package)
    bundle = ReviewWorkspace(package, AgentResult.model_json_schema())
    assert json.loads(bundle.files["review/package.json"]) == original
    assert package == original
    manifest = json.loads(bundle.files["review/manifest.json"])
    assert manifest["review_context"]["requirements"] == original["requirements"]
    assert manifest["source_files"][0]["block_count"] == 23
    for block in original["attachments"][0]["content"]:
        assert block["text"] in bundle.files["review/sources/001.txt"]
    assert not bundle.coverage()["complete"]


def test_only_verified_complete_reads_satisfy_coverage():
    bundle = ReviewWorkspace(package_with_pages(1), {})
    record(bundle, "review/manifest.json")
    path = "review/sources/001.txt"
    record(bundle, path, limit=1)
    with pytest.raises(ReviewFailure, match="COVERAGE_INCOMPLETE") as caught:
        bundle.validate_coverage()
    assert caught.value.metadata["validation_issues"][0]["unread_line_ranges"][0][0] == 2
    record(bundle, path, offset=2, text="permission denied")
    assert not bundle.coverage()["complete"]
    record(bundle, path, offset=2, error=True)
    assert not bundle.coverage()["complete"]
    record(bundle, path, offset=2)
    bundle.validate_coverage()
    assert bundle.coverage()["complete"]


def test_native_truncation_does_not_claim_the_remaining_lines():
    bundle = ReviewWorkspace(package_with_pages(2), {})
    path = "review/package.json"
    record(bundle, path, truncated={"truncated": True, "outputLines": 5})
    assert len(bundle.seen[path]) == 5
    assert not bundle.coverage()["complete"]
    record(bundle, path, offset=6)
    bundle.validate_coverage()
    assert bundle.coverage()["canonical_package_read"]


@pytest.mark.parametrize("args", ["malformed", {"path": 123}])
def test_bad_tool_arguments_do_not_break_the_agent_recovery_loop(args):
    bundle = ReviewWorkspace(package_with_pages(1), {})
    bundle.record({"type": "tool_start", "toolCallId": "bad", "toolName": "read", "args": args},
                  "owned-workspace")
    bundle.record({"type": "tool_end", "toolCallId": "bad", "toolName": "read", "isError": True,
                   "result": "invalid arguments"}, "owned-workspace")
    assert not bundle.coverage()["complete"]
    assert bundle.trace[-1]["lines_verified"] == 0


@pytest.mark.parametrize("text", [
    '{"checks":[],"checks":[{}]}',
    '{"checks":[{"rule_id":"one","rule_id":"two"}]}',
    '{"result":{"checks":[]}',
    '{"result":{"checks":[]}}',
    '{"checks":[]} {"broken":',
    '[{"checks":[]}]',
    '{"checks":[NaN]}',
    '"result":{"checks":[]}',
    '{"checks":[]},"approval":true',
])
def test_strict_parser_rejects_ambiguous_or_incomplete_json(text):
    with pytest.raises(ReviewFailure, match="OUTPUT_INVALID"):
        InnoAgentAdapter._report(text)


def test_truncated_stream_is_invalid():
    with pytest.raises(ReviewFailure, match="OUTPUT_INVALID"):
        InnoAgentAdapter._last_json(['data: {"event":{"type":"text_delta","delta":"{"}}'])


def test_untyped_event_is_not_an_assistant_report():
    with pytest.raises(ReviewFailure, match="OUTPUT_INVALID"):
        InnoAgentAdapter._last_json(['data: {"checks":[],"checks":[{}]}'])


def mock_runtime(monkeypatch, outputs, reads=None, fail_at=None, done=True, read_limit=None):
    state = {"calls": [], "uploads": {}, "turns": 0}
    original_client = httpx.Client

    def handle(request):
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        state["calls"].append((method, path, body))
        if (method, path) == fail_at:
            return httpx.Response(503)
        if path == "/api/health":
            data = {"status": "ok"}
        elif path == "/api/skills":
            data = [{"name": "material-review"}]
        elif path.endswith("/file"):
            data = {"content": (SKILL_ROOT / "SKILL.md").read_text()}
        elif path == "/api/workspaces" and method == "POST":
            assert body["isTemp"] is False
            data = {"id": "owned-workspace", "isTemp": False}
        elif path == "/api/workspace/upload":
            state["uploads"].update({
                f["path"]: base64.b64decode(f["dataBase64"]).decode() for f in body["files"]
            })
            state.setdefault("upload_sizes", []).append(len(request.content))
            data = {"uploaded": list(state["uploads"])}
        elif path == "/api/sessions" and method == "POST":
            assert body == {"workspaceId": "owned-workspace"}
            data = {"id": "session", "workspaceId": "owned-workspace"}
        elif path == "/api/chat/stream":
            turn = state["turns"]
            state["turns"] += 1
            state.setdefault("prompts", []).append(body)
            events = []
            if reads is None or reads[turn]:
                for file_index, (file_path, file_text) in enumerate(state["uploads"].items()):
                    lines = file_text.split("\n")
                    limit = read_limit or len(lines)
                    for offset in range(1, len(lines) + 1, limit):
                        events += [
                            {"type": "tool_start", "toolCallId": f"r-{file_index}-{offset}",
                             "toolName": "read", "args": {"path": file_path, "offset": offset, "limit": limit}},
                            {"type": "tool_end", "toolCallId": f"r-{file_index}-{offset}",
                             "toolName": "read",
                             "result": {"content": [{"type": "text",
                                 "text": "\n".join(lines[offset - 1:offset - 1 + limit])}]},
                             "isError": False},
                        ]
            events += [{"type": "thinking_delta", "delta": "ignore"},
                       {"type": "text_start"}, {"type": "text_delta", "delta": outputs[turn]}]
            if done:
                events.append({"type": "done"})
            return httpx.Response(200, text="".join("data: " + json.dumps({"event": e}) + "\n\n" for e in events))
        elif method == "DELETE":
            if path.startswith("/api/workspaces/"):
                assert request.url.params["removeFiles"] == "1"
            data = {"deleted": True}
        else:
            data = {"messages": [{"role": "assistant", "model": "actual-model", "provider": "local"}]}
        return httpx.Response(200, json=data)

    monkeypatch.setattr(httpx, "Client",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    return state


@pytest.mark.parametrize("failure", ["format", "evidence", "coverage"])
def test_bounded_correction_keeps_session_and_cleans_owned_files(monkeypatch, failure):
    valid = json.dumps({"checks": [check("下一学年开展验证实验").model_dump()]}, ensure_ascii=False)
    invalid = '{"checks":[' if failure == "format" else json.dumps(
        {"checks": [check("编造的计划").model_dump()]}, ensure_ascii=False)
    state = mock_runtime(monkeypatch, [valid if failure == "coverage" else invalid, valid],
                         reads=[False, True] if failure == "coverage" else None)
    result = analyze({"review_package": package_with_pages(1)},
                     {"mode": "innoagent", "base_url": "http://test"}, "/unused")
    metadata = result["agent"]
    assert state["turns"] == 2
    assert [body["sessionId"] for body in state["prompts"]] == ["session", "session"]
    assert "正文正文" not in state["prompts"][0]["prompt"]
    assert "review_package_path" in state["prompts"][0]["prompt"]
    assert metadata["repair_attempts"] == 1
    assert metadata["coverage"]["complete"]
    assert metadata["cleanup_status"] == "deleted"
    assert metadata["workspace_cleanup_status"] == metadata["session_cleanup_status"] == "deleted"
    assert [(m, p) for m, p, _ in state["calls"] if m == "DELETE"] == [
        ("DELETE", "/api/sessions/session"), ("DELETE", "/api/workspaces/owned-workspace"),
    ]


def test_second_invalid_report_fails_after_one_repair_and_cleans_up(monkeypatch):
    state = mock_runtime(monkeypatch, ["{}", "{}"])
    with pytest.raises(ReviewFailure, match="OUTPUT_INVALID") as caught:
        InnoAgentAdapter({"base_url": "http://test"}).review(package_with_pages(1), {})
    assert state["turns"] == 2
    assert caught.value.metadata["cleanup_status"] == "deleted"


def test_valid_output_without_confirmed_terminal_event_is_rejected(monkeypatch):
    state = mock_runtime(monkeypatch, ['{"checks":[]}'], done=False)
    with pytest.raises(ReviewFailure, match="TRANSIENT_SERVICE") as caught:
        InnoAgentAdapter({"base_url": "http://test"}).review(package_with_pages(1), {})
    assert state["turns"] == 1 and caught.value.transient
    assert caught.value.metadata["protocol_event"] == "incomplete_stream"
    assert caught.value.metadata["cleanup_status"] == "deleted"


def test_large_sources_are_uploaded_separately_and_do_not_limit_report_stream(monkeypatch):
    package = package_with_pages(180)
    for block in package["attachments"][0]["content"]:
        block["text"] = "研" * 12000
    package["attachments"].append({**deepcopy(package["attachments"][0]), "file_id": "second"})
    state = mock_runtime(monkeypatch, ['{"checks":[]}'], read_limit=2)
    result, metadata = InnoAgentAdapter({"base_url": "http://test"}).review(package, {})
    assert result == {"checks": []} and metadata["coverage"]["complete"]
    assert sum(state["upload_sizes"]) > 32 * 1024 * 1024
    assert max(state["upload_sizes"]) < 32 * 1024 * 1024
    assert not any(method == "GET" and path == "/api/sessions/session"
                   for method, path, _ in state["calls"])


def test_individual_file_limit_is_explicit_and_cleans_workspace(monkeypatch):
    state = mock_runtime(monkeypatch, [])
    monkeypatch.setattr("app.adapters.innoagent.MAX_UPLOAD_BODY_BYTES", 1000)
    with pytest.raises(ReviewFailure, match="INPUT_TRANSFER_LIMIT") as caught:
        InnoAgentAdapter({"base_url": "http://test"}).review(package_with_pages(1), {})
    assert not state["uploads"] and state["turns"] == 0
    assert caught.value.metadata["cleanup_status"] == "deleted"


@pytest.mark.parametrize("fail_at,cleanup,workspace_status", [
    (("GET", "/api/health"), "not_required", "not_required"),
    (("POST", "/api/workspace/upload"), "deleted", "deleted"),
    (("POST", "/api/sessions"), "failed", "deleted"),
    (("DELETE", "/api/workspaces/owned-workspace"), "failed", "failed"),
])
def test_cleanup_reports_partial_lifecycle_accurately(monkeypatch, fail_at, cleanup, workspace_status):
    mock_runtime(monkeypatch, ['{"checks":[]}'], fail_at=fail_at)
    adapter = InnoAgentAdapter({"base_url": "http://test"})
    try:
        _, metadata = adapter.review(package_with_pages(1), {})
    except ReviewFailure as exc:
        metadata = exc.metadata
    assert metadata["cleanup_status"] == cleanup
    assert metadata["workspace_cleanup_status"] == workspace_status
