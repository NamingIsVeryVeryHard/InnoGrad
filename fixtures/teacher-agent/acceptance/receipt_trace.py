"""Capture MCP, Pi, and planner receipt correlation for teacher acceptance."""

from contextvars import ContextVar
import ast
from functools import lru_cache
import inspect
import json
import os
from pathlib import Path
import re
from threading import Lock
import textwrap
from uuid import uuid4

import httpx


MCP_PATH = "/api/v1/teacher-agent/mcp"
TURN_PATH = re.compile(r"/api/v1/teacher-agent/conversations/[^/]+/turns")
RECEIPT_META = "innograd.dev/acceptanceReceipt"
CODES = {"INVALID_PLANNER_OUTPUT", "RETRYABLE_TOOL_INPUT", "CLARIFICATION_NEEDED"}
FIELD_NAMES = {
    "spec", "patch", "basis", "operation", "domain", "time_range", "group_by",
    "distinct_subject", "filters", "field", "value", "values", "projection",
    "include", "metrics", "sources", "items", "start", "end",
}
TURN = ContextVar("issue43_turn", default=None)
CALLS = {}
ARGUMENTS = {}
RECEIPTS = set()
LOCK = Lock()
TRACE = None


def trace_output(path):
    """Reset trace state and select the trace.jsonl output path for a run."""
    global TRACE
    TRACE = Path(path)
    TRACE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(TRACE, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with LOCK:
        CALLS.clear()
        ARGUMENTS.clear()
        RECEIPTS.clear()
    TURN.set(None)
    return TRACE


def obj(value):
    return value if isinstance(value, dict) else {}


def code(value):
    return value if isinstance(value, str) and value in CODES else None if value is None else "other"


def decode(data):
    try:
        return obj(json.loads(data))
    except (ValueError, UnicodeError, RecursionError):
        return {}


def call_tag(identifier):
    if isinstance(identifier, str) and identifier:
        with LOCK:
            if identifier not in CALLS:
                CALLS[identifier] = f"call-{len(CALLS) + 1}"
            return CALLS[identifier]
    return None


def receipt_tag(receipt):
    candidate = obj(obj(receipt).get("_meta")).get(RECEIPT_META)
    with LOCK:
        return candidate if isinstance(candidate, str) and candidate in RECEIPTS else None


def emit(event, **fields):
    if TRACE is None:
        raise RuntimeError("Call trace_output() before emitting trace events.")
    line = json.dumps({"event": event, **fields}, separators=(",", ":")) + "\n"
    descriptor = os.open(TRACE, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, line.encode())
    finally:
        os.close(descriptor)


def argument_shape(value):
    parsed = decode(value) if isinstance(value, str) else obj(value)
    return {
        "type": type(value).__name__,
        "fields": sorted(parsed.keys() & FIELD_NAMES),
        "other_fields": len(parsed.keys() - FIELD_NAMES),
    }


def validation_error(item, arguments):
    path, description = item[4:].split(" ", 1)
    keywords = {
        "required": "must have required property",
        "additional_properties": "additional properties",
        "enum": "one of the allowed values",
        "constant": "equal to constant",
        "type": "must be ",
        "schema": "must match",
        "bounds": "must NOT have",
        "minimum": "must >",
        "maximum": "must <",
    }
    keyword = next((name for name, text in keywords.items() if text in description), "other")
    components = path.split("/")[1:]
    if not all(component in FIELD_NAMES or re.fullmatch(r"[0-9]{1,3}", component) for component in components):
        return {"keyword": keyword, "path": None, "value_type": None}
    value = arguments
    for component in components:
        if isinstance(value, list) and component.isdecimal() and int(component) < len(value):
            value = value[int(component)]
        else:
            value = obj(value).get(component)
    return {"keyword": keyword, "path": path or "/", "value_type": type(value).__name__}


def receipt_shape(receipt):
    data = obj(receipt).get("structuredContent")
    flag = obj(receipt).get("isError")
    run_id = obj(data).get("query_run_id")
    return {
        "receipt_tag": receipt_tag(receipt),
        "receipt_type": type(receipt).__name__,
        "receipt_flag_type": type(flag).__name__,
        "receipt_is_error": flag if type(flag) is bool else None,
        "structured_type": type(data).__name__,
        "structured_empty": isinstance(data, dict) and not data,
        "has_code": "code" in obj(data),
        "code": code(obj(data).get("code")),
        "run_id_present": "query_run_id" in obj(data),
        "run_id_type": type(run_id).__name__,
        "run_id_matches": isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", run_id) is not None,
    }


def tool_end_shape(event):
    details = obj(event.get("result")).get("details")
    fields = obj(details)
    flag = event.get("isError")
    receipt = fields.get("mcpResult")
    receipt_flag = obj(receipt).get("isError")
    return {
        "call_tag": call_tag(event.get("toolCallId")),
        "details_type": type(details).__name__,
        "mode_matches": fields.get("mode") == "call",
        "server_matches": fields.get("server") == "innograd_teacher",
        "tool_matches": fields.get("tool") == "query_papers",
        "details_error_present": "error" in fields,
        "details_tool_error": fields.get("error") == "tool_error",
        "details_call_failed": fields.get("error") == "call_failed",
        "flag_type": type(flag).__name__,
        "is_error": flag if type(flag) is bool else None,
        "flags_match": type(flag) is bool and receipt_flag is flag,
        **receipt_shape(receipt),
    }


@lru_cache
def guards(check):
    try:
        source, start = inspect.getsourcelines(check)
        function = ast.parse(textwrap.dedent("".join(source))).body[0]
    except (OSError, TypeError, SyntaxError, IndexError):
        return {}
    result = {}
    for statement in function.body:
        if isinstance(statement, ast.If) and statement.body and isinstance(statement.body[0], ast.Raise):
            expression = ast.unparse(statement.test)
            if "isinstance(details, dict)" in expression:
                result[start + statement.body[0].lineno - 1] = "target"
            elif "isinstance(receipt, dict)" in expression:
                result[start + statement.body[0].lineno - 1] = "receipt_flag"
            elif "isinstance(structured, dict)" in expression:
                result[start + statement.body[0].lineno - 1] = "structured_content"
        if isinstance(statement, ast.Raise):
            result[start + statement.lineno - 1] = "receipt_semantics"
    return result


def validation_shape(check, event, branch, arguments):
    result = obj(event.get("result"))
    details = obj(result.get("details"))
    if branch != "retry" or details.get("mcpResult") is not None:
        return {}
    module = check.__globals__
    message = details.get("message")
    errors = message.split(", ") if isinstance(message, str) else []
    if errors and all(module["_MCP_SCHEMA_ERROR"].fullmatch(item) for item in errors):
        return {
            "validator": "mcp_adapter_schema",
            "validation_errors": [validation_error(item, arguments) for item in errors],
        }
    part = obj(result["content"][0]).get("text")
    return {"validator": "proxy_args" if part == module["MCP_INVALID_ARGS"] else "pi_tool_schema"}


def observe_outcome(check, event, invalid_args):
    fields = {"turn_tag": TURN.get(), "invalid_args": invalid_args, **tool_end_shape(event)}
    with LOCK:
        arguments = ARGUMENTS.pop(fields["call_tag"], None)
    try:
        branch = check(event, invalid_args)
    except Exception as error:
        frame = error.__traceback__
        while frame and frame.tb_frame.f_code is not check.__code__:
            frame = frame.tb_next
        outcome_line = frame.tb_lineno if frame else None
        guard = guards(check).get(outcome_line)
        missing_run_id = (
            guard == "receipt_semantics" and fields["is_error"] is False
            and not fields["details_error_present"] and fields["code"] is None
            and not fields["run_id_present"]
        )
        emit("planner_outcome", branch="exception", guard=guard, outcome_line=outcome_line,
             guard_reason="missing_run_id" if missing_run_id else None,
             invalid_planner_output=getattr(error, "code", None) == "INVALID_PLANNER_OUTPUT", **fields)
        raise
    emit("planner_outcome", branch=branch, **fields, **validation_shape(check, event, branch, arguments))
    return branch


class PiStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        pending = b""
        async for chunk in self.stream:
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            for line in lines:
                if not line.startswith(b"data:"):
                    continue
                event = obj(decode(line[5:]).get("event"))
                kind = event.get("type")
                if kind in ("tool_call_end", "tool_start"):
                    args = obj(event.get("args"))
                    tag = call_tag(event.get("toolCallId"))
                    value = args.get("args")
                    if tag:
                        with LOCK:
                            ARGUMENTS[tag] = decode(value) if isinstance(value, str) else value
                    emit(f"pi_{kind}", turn_tag=TURN.get(), call_tag=tag,
                         target_matches=args.get("server") == "innograd_teacher" and args.get("tool") == "query_papers",
                         arguments=argument_shape(value))
                elif kind == "tool_end":
                    emit("pi_tool_end", turn_tag=TURN.get(), **tool_end_shape(event))
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PiTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)
        if request.method == "POST" and request.url.path == "/api/chat/stream":
            emit("planner_dispatch", turn_tag=TURN.get(), status=response.status_code)
            response.stream = PiStream(response.stream)
        return response


class BoundaryCapture:
    def __init__(self, app, invalid_receipt):
        self.app = app
        self.invalid_receipt = invalid_receipt
        self.fixture_used = False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if TURN_PATH.fullmatch(path):
            marker = TURN.set(uuid4().hex)
            try:
                await self.capture_turn(scope, receive, send)
            finally:
                TURN.reset(marker)
        elif path == MCP_PATH:
            await self.capture_mcp(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def capture_turn(self, scope, receive, send):
        status = None
        chunks = []

        async def observe(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    emit("turn_http", turn_tag=TURN.get(), status=status, code=code(decode(b"".join(chunks)).get("code")))
                    chunks.clear()
            await send(message)

        await self.app(scope, receive, observe)

    async def capture_mcp(self, scope, receive, send):
        request = []
        response = []
        paper_call = False
        tag = None
        start = None
        receipt_injected = False

        async def observe_request():
            nonlocal paper_call, tag
            message = await receive()
            if message["type"] == "http.request":
                request.append(message.get("body", b""))
                if not message.get("more_body"):
                    packet = decode(b"".join(request))
                    request.clear()
                    params = obj(packet.get("params"))
                    paper_call = packet.get("method") == "tools/call" and params.get("name") == "query_papers"
                    if paper_call:
                        tag = call_tag(obj(params.get("_meta")).get("pi-mcp-adapter/toolCallId"))
                        emit("mcp_ingress", call_tag=tag, arguments=argument_shape(params.get("arguments")))
            return message

        async def observe_response(message):
            nonlocal receipt_injected, start
            if not paper_call:
                return await send(message)
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body":
                return await send(message)
            response.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(response)
            packet = decode(body)
            receipt = packet.get("result")
            if isinstance(receipt, dict):
                if self.invalid_receipt and not self.fixture_used and receipt_shape(receipt)["run_id_matches"]:
                    self.fixture_used = True
                    receipt_injected = True
                    receipt.update(structuredContent={}, content=[{"type": "text", "text": "{}"}])
                identifier = uuid4().hex
                with LOCK:
                    RECEIPTS.add(identifier)
                receipt["_meta"] = {**obj(receipt.get("_meta")), RECEIPT_META: identifier}
                body = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode()
                headers = [(key, value) for key, value in start["headers"] if key != b"content-length"]
                start = {**start, "headers": headers + [(b"content-length", str(len(body)).encode())]}
            error = obj(packet.get("error")).get("code")
            emit("mcp_response", call_tag=tag, status=start["status"],
                 rpc_error=error if type(error) is int and -32700 <= error <= -32000 else None,
                 receipt_injected=receipt_injected,
                 **receipt_shape(receipt))
            await send(start)
            await send({**message, "body": body})

        await self.app(scope, observe_request, observe_response)


def evidence(output, invalid_receipt):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in TRACE.read_text().splitlines()] if TRACE and TRACE.exists() else []
    by_event = {}
    for row in rows:
        by_event.setdefault(row["event"], []).append(row)

    def matching(event, field, tag):
        return [row for row in by_event.get(event, []) if tag and row.get(field) == tag]

    correlated = []
    for response in by_event.get("mcp_response", []):
        tag = response["receipt_tag"]
        chain = []
        for event in ("pi_tool_end", "planner_outcome"):
            matches = matching(event, "receipt_tag", tag)
            if len(matches) != 1 or matches[0]["call_tag"] != response["call_tag"]:
                break
            chain.append(matches[0])
        ingress = matching("mcp_ingress", "call_tag", response["call_tag"])
        same_turn = (
            len(chain) == 2
            and chain[0].get("turn_tag") is not None
            and chain[0].get("turn_tag") == chain[1].get("turn_tag")
        )
        if len(chain) == 2 and len(ingress) == 1 and same_turn:
            correlated.append((response, *chain))

    failures = []
    for reply in by_event.get("turn_http", []):
        if reply["status"] != 502:
            continue
        turn = reply["turn_tag"]
        outcomes = matching("planner_outcome", "turn_tag", turn)
        call_tags = {row["call_tag"] for row in matching("pi_tool_start", "turn_tag", turn)} - {None}
        failures.append({
            "http": reply,
            "events": [row for row in rows if row.get("turn_tag") == turn and row is not reply
                       or row["event"] in ("mcp_ingress", "mcp_response") and row.get("call_tag") in call_tags],
            "correlated_exception": any(outcome in outcomes and outcome["branch"] == "exception"
                                        for _, _, outcome in correlated),
        })
    if failures:
        (output / "failure.json").write_text(json.dumps(failures, indent=2) + "\n")

    verification = {
        "ingress": len(by_event.get("mcp_ingress", [])),
        "mcp_responses": len(by_event.get("mcp_response", [])),
        "correlated_receipts": len(correlated),
        "query": sum(outcome["branch"] == "query" for _, _, outcome in correlated),
        "http_200": sum(row["status"] == 200 for row in by_event.get("turn_http", [])),
        "http_502": len(failures),
    }
    if invalid_receipt:
        verification["expected_failure_observed"] = (
            len(failures) == len(correlated) == 1
            and verification["correlated_receipts"] == verification["mcp_responses"] == verification["ingress"]
            and failures[0]["correlated_exception"]
            and failures[0]["http"]["code"] == "INVALID_PLANNER_OUTPUT"
            and correlated[0][0]["status"] == 200
            and correlated[0][0]["receipt_injected"] is True
            and correlated[0][0]["structured_empty"] and correlated[0][1]["structured_empty"]
            and correlated[0][2]["guard_reason"] == "missing_run_id"
            and correlated[0][2]["flags_match"] and correlated[0][2]["invalid_planner_output"]
        )
    (output / "trace-summary.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps(verification), flush=True)
    if invalid_receipt:
        return verification["expected_failure_observed"]
    return (
        verification["query"] >= 4
        and verification["correlated_receipts"] == verification["mcp_responses"] == verification["ingress"]
    )
