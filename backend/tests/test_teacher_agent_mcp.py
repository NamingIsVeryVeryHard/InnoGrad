import json

import pytest
from fastapi.testclient import TestClient

from app.teacher_agent.contract import PaperQuerySpec, QueryPatch
from app.teacher_agent.engine import TeacherQueryEngine
from app.teacher_agent.errors import ResourceNotFoundError, RetryableToolInputError
from test_workflow import env


MCP_PATH = "/api/v1/teacher-agent/mcp"
PROTOCOL = "2025-11-25"
PI_CALL_ID = "pi-mcp-adapter/toolCallId"


@pytest.fixture
def mcp(env):
    with TestClient(env[0]) as client:
        yield client


def rpc(client, method, *, params=None, request_id=1, headers=None):
    packet = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        packet["id"] = request_id
    if params is not None:
        packet["params"] = params
    return client.post(MCP_PATH, json=packet, headers=headers)


def initialize(client, version, **kwargs):
    return rpc(client, "initialize", params={
        "protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "probe", "version": "1"},
    }, **kwargs)


def test_streamable_http_negotiation_and_static_discovery(mcp):
    preflight = rpc(mcp, "server/discover", headers={"MCP-Protocol-Version": "2026-07-28"})
    assert preflight.status_code == 400
    assert initialize(mcp, "2025-06-18").json()["result"]["protocolVersion"] == "2025-06-18"
    handshake = initialize(mcp, PROTOCOL, request_id="handshake")
    assert handshake.status_code == 200
    assert handshake.headers["Cache-Control"] == "no-store"
    assert handshake.json() == {"jsonrpc": "2.0", "id": "handshake", "result": {
        "protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
        "serverInfo": {"name": "innograd_teacher", "version": "1"},
    }}
    assert initialize(mcp, "2030-01-01").json()["result"]["protocolVersion"] == PROTOCOL

    headers = {"MCP-Protocol-Version": PROTOCOL}
    initialized = rpc(mcp, "notifications/initialized", request_id=None, headers=headers)
    assert initialized.status_code == 202 and initialized.content == b""
    assert initialized.headers["Cache-Control"] == "no-store"
    assert rpc(mcp, "ping", headers=headers).json()["result"] == {}
    listing = rpc(mcp, "tools/list", headers=headers).json()["result"]["tools"]
    assert [tool["name"] for tool in listing] == ["query_papers"]
    schema = listing[0]["inputSchema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["minProperties"] == schema["maxProperties"] == 1
    assert schema["properties"]["spec"]["$ref"] == "#/$defs/PaperQuerySpec"
    assert schema["properties"]["patch"]["$ref"] == "#/$defs/QueryPatch"
    for contract in (PaperQuerySpec, QueryPatch):
        declared = schema["$defs"][contract.__name__]
        expected = contract.model_json_schema()
        assert declared["properties"] == expected["properties"]
        assert declared["additionalProperties"] is False


def test_transport_rejects_browser_origin_and_unsupported_methods(mcp):
    origin = {"Origin": "https://untrusted.example"}
    rejected = initialize(mcp, PROTOCOL, headers=origin)
    assert rejected.status_code == 403
    assert rejected.headers["Cache-Control"] == "no-store"
    for method in ("GET", "DELETE"):
        response = mcp.request(method, MCP_PATH)
        assert response.status_code == 405
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Allow"] == "POST"
        rejected = mcp.request(method, MCP_PATH, headers=origin)
        assert rejected.status_code == 403
        assert rejected.headers["Cache-Control"] == "no-store"
    assert mcp.post("/api/v1/teacher-agent/tools/query-papers", json={"spec": {}}).status_code in (404, 405)


def test_json_rpc_errors_keep_ids_and_do_not_call_engine(mcp, monkeypatch):
    def unexpected(*_args):
        pytest.fail("protocol error reached engine")

    monkeypatch.setattr(TeacherQueryEngine, "query_for_agent", unexpected)
    malformed = mcp.post(MCP_PATH, content="{", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == -32700
    for packet in ([], {"jsonrpc": "2.0", "method": "ping", "id": True},
                   {"jsonrpc": "2.0", "method": "ping", "id": None}):
        invalid = mcp.post(MCP_PATH, json=packet)
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == -32600
    unknown = rpc(mcp, "unknown", request_id="example").json()
    assert unknown["id"] == "example" and unknown["error"]["code"] == -32601
    assert rpc(mcp, "initialize", params={}).json()["error"]["code"] == -32602
    request = {"name": "query_papers", "arguments": {"spec": {}}}
    missing = rpc(mcp, "tools/call", params=request)
    assert missing.status_code == 404
    assert "structuredContent" not in missing.json()
    bearer = {"Authorization": "Bearer synthetic"}
    assert rpc(mcp, "tools/call", params=request, request_id=None, headers=bearer).status_code == 202
    assert rpc(mcp, "tools/call", params={"name": "unknown"}, headers=bearer).json()["error"]["code"] == -32602
    assert rpc(mcp, "tools/call", params={**request, "arguments": "not-an-object"},
               headers=bearer).json()["error"]["code"] == -32602


def test_standard_and_pi_call_ids_and_success_payload(mcp, monkeypatch):
    received = []

    def query(_engine, token, raw, call_id):
        assert isinstance(raw, dict)
        received.append((token, raw, call_id))
        return {"query_run_id": "run-fixture", "metrics": {"paper_record_count": 2}}

    monkeypatch.setattr(TeacherQueryEngine, "query_for_agent", query)
    arguments = {"spec": {}}
    headers = {"Authorization": "Bearer synthetic", "MCP-Protocol-Version": PROTOCOL}
    for identifier, metadata in ((1, {}), ("1", {"progressToken": 1}), (2, {PI_CALL_ID: "model-call-id"})):
        response = rpc(mcp, "tools/call", request_id=identifier, headers=headers,
                       params={"name": "query_papers", "arguments": arguments, "_meta": metadata})
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        payload = response.json()
        assert payload["id"] == identifier
        result = payload["result"]
        assert result["isError"] is False
        assert result["structuredContent"]["metric_refs"] == {"paper_record_count": "[run-fixture:paper_record_count]"}
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert [token for token, _, _ in received] == ["synthetic"] * 3
    assert [raw for _, raw, _ in received] == [arguments] * 3
    call_ids = [call_id for _, _, call_id in received]
    assert len(set(call_ids)) == 3 and call_ids[-1] == "model-call-id"


@pytest.mark.parametrize(("outcome", "is_error", "code"), [
    (RetryableToolInputError("请改用博士。"), True, "RETRYABLE_TOOL_INPUT"),
    ({"clarification": {
        "message": "请选择一位学生。",
        "suggestions": ["请按学号选择。"],
        "student_candidates": [
            {"student_id": "student-1", "student_name": "同名学生", "year": "2025", "degree": "博士", "major": "物理"},
            {"student_id": "student-2", "student_name": "同名学生", "year": "2026", "degree": "硕士", "major": "数学"},
        ],
    }}, False, "CLARIFICATION_NEEDED"),
    (ResourceNotFoundError("本轮查询授权已结束"), None, None),
])
def test_only_domain_outcomes_have_teacher_markers(mcp, monkeypatch, outcome, is_error, code):
    def query(*_args):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(TeacherQueryEngine, "query_for_agent", query)
    response = rpc(mcp, "tools/call", headers={"Authorization": "Bearer synthetic"},
                   params={"name": "query_papers", "arguments": {"spec": {}}})
    if code is None:
        assert response.status_code == 404
        assert "result" not in response.json()
        return
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is is_error
    assert result["structuredContent"]["code"] == code
    content = result["content"][0]
    assert content["type"] == "text"
    if is_error:
        assert content["text"] == "请改用博士。"
    else:
        expected = {"code": "CLARIFICATION_NEEDED", "clarification": outcome["clarification"]}
        assert result["structuredContent"] == expected
        assert json.loads(content["text"]) == expected
