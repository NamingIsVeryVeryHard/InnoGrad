"""Stateless Streamable HTTP for the teacher paper query tool."""

import json

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..login_session import find_login, login_user
from .contract import export_paper_tool_input_schema
from .dsh_tools import TOOLS, call_tool
from .engine import ActorContext, TeacherQueryEngine
from .errors import ResourceNotFoundError, RetryableToolInputError, TeacherAgentError


PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = {"2025-03-26", "2025-06-18", PROTOCOL_VERSION}
PI_CALL_ID = "pi-mcp-adapter/toolCallId"
PAPER_TOOL = {
    "name": "query_papers",
    "description": "查询论文。传入 spec 发起新查询，或传入 patch 修改上一条查询，每次仅传其中一个。",
    "inputSchema": export_paper_tool_input_schema(),
}


def _result(request_id, value):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": value})


def _error(request_id, code, message, *, status=200):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
                        status_code=status)


def _parse_constant(_value):
    raise ValueError("JSON constants must be finite")


def _call_id(request_id, metadata):
    adapter_id = metadata.get(PI_CALL_ID) if isinstance(metadata, dict) else None
    if isinstance(adapter_id, str) and adapter_id:
        return adapter_id
    return f"rpc:{json.dumps(request_id)}"


def _tool_result(data, *, text=None, is_error=False):
    return {
        "content": [{"type": "text", "text": text if text is not None else json.dumps(data, ensure_ascii=False)}],
        "isError": is_error,
        "structuredContent": data,
    }


async def _call_paper_tool(engine, request_id, params, token):
    if not token:
        raise ResourceNotFoundError("本轮查询授权无效")
    arguments = params.get("arguments", {})
    if params.get("name") != PAPER_TOOL["name"] or not isinstance(arguments, dict):
        return _error(request_id, -32602, "Invalid tool name or arguments")
    try:
        view = await run_in_threadpool(
            engine.query_for_agent, token, arguments, _call_id(request_id, params.get("_meta")),
        )
    except RetryableToolInputError as error:
        message = str(error)
        return _result(request_id, _tool_result({"code": error.code, "message": message}, text=message, is_error=True))
    if "clarification" in view:
        return _result(request_id, _tool_result(
            {"code": "CLARIFICATION_NEEDED", "clarification": view["clarification"]},
        ))
    run_id = view["query_run_id"]
    references = {key: f"[{run_id}:{key}]" for key in view["metrics"]}
    return _result(request_id, _tool_result({**view, "metric_refs": references}))


def _list_tools(sessions, token):
    if token:
        with sessions() as session:
            login = find_login(session, token)
            if login is not None:
                ActorContext.from_user(login_user(session, login))
                return TOOLS
    return [PAPER_TOOL]


def _call_teacher_tool(sessions, token, name, arguments, base_url):
    with sessions.begin() as session:
        user = login_user(session, find_login(session, token))
        ActorContext.from_user(user)
        try:
            return _tool_result(call_tool(session, user, name, arguments, base_url))
        except ValidationError as error:
            issues = [{"field": ".".join(map(str, issue["loc"])), "message": issue["msg"]}
                      for issue in error.errors(include_input=False, include_url=False)]
            return _tool_result({"code": "INVALID_ARGUMENTS", "issues": issues}, is_error=True)
        except TeacherAgentError as error:
            return _tool_result({"code": error.code, "message": str(error)}, is_error=True)


async def handle_mcp(request: Request, engine: TeacherQueryEngine, token: str | None) -> Response:
    if "origin" in request.headers:
        return _error(None, -32600, "Origin not allowed", status=403)
    if request.method != "POST":
        return Response(status_code=405, headers={"Allow": "POST"})
    protocol = request.headers.get("MCP-Protocol-Version")
    if protocol is not None and protocol not in SUPPORTED_VERSIONS:
        return _error(None, -32600, "Unsupported MCP protocol version", status=400)
    if request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(None, -32600, "Content-Type must be application/json", status=415)
    try:
        packet = json.loads(await request.body(), parse_constant=_parse_constant)
    except (ValueError, RecursionError):
        return _error(None, -32700, "Parse error", status=400)

    if not isinstance(packet, dict) or packet.get("jsonrpc") != "2.0" or not isinstance(packet.get("method"), str):
        return _error(None, -32600, "Invalid Request", status=400)
    request_id = packet.get("id")
    method = packet["method"]
    params = packet.get("params", {})
    notification = "id" not in packet
    if not notification and type(request_id) not in (str, int):
        return _error(None, -32600, "Invalid Request", status=400)
    if not isinstance(params, dict):
        if notification:
            return Response(status_code=400)
        return _error(request_id, -32602, "Invalid params")
    if notification:
        return Response(status_code=202)

    if method == "initialize":
        requested = params.get("protocolVersion")
        if not isinstance(requested, str) or not isinstance(params.get("capabilities"), dict) or not isinstance(
            params.get("clientInfo"), dict
        ):
            return _error(request_id, -32602, "Invalid initialize params")
        return _result(request_id, {
            "protocolVersion": requested if requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "innograd_teacher", "version": "1"},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        tools = await run_in_threadpool(_list_tools, engine.sessions, token)
        return _result(request_id, {"tools": tools})
    if method == "tools/call":
        if any(params.get("name") == tool["name"] for tool in TOOLS):
            result = await run_in_threadpool(
                _call_teacher_tool, engine.sessions, token, params["name"], params.get("arguments", {}),
                str(request.base_url).rstrip("/"),
            )
            return _result(request_id, result)
        return await _call_paper_tool(engine, request_id, params, token)
    return _error(request_id, -32601, "Method not found")
