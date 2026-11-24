"""Plan teacher queries or analyze scoped results using the dedicated Pi deployment."""

import asyncio
import calendar
import json
import os
import re
import stat
import time
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import BoundedSemaphore
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from .budget import TurnBudget
from .contract import (
    ClarifyAction, DegreeFilter, DomainName, PaperQuerySpec, PaperTimeRange, PatchSpecAction,
    PlannerOutput, PlannerOutputAdapter, PublicationStatusFilter, QueryPatch, QuerySpec,
    ReplaceSpecAction, ReviewStatusFilter, StudentIdFilter, UnsupportedAction, YearFilter, apply_patch,
    export_paper_tool_input_schema,
)
from .errors import PlannerConfigError, PlannerInvalidOutputError, PlannerUnavailableError
from .privacy import SELECTED_STUDENT, SUBJECT_FIELDS, planner_view, safe_language, with_subject


PlannerMode = Literal["rules", "innoagent", "chat"]
TOOL_NAME = "mcp"
MCP_SERVER = "innograd_teacher"
MCP_QUERY_TOOL = "query_papers"
MCP_INVALID_ARGS = "TEACHER_QUERY_ARGS_INVALID: args 必须是 JSON 对象或其 JSON 字符串，并且只含一个 spec 或 patch 对象。"
SKILL_NAME = "teacher-query-planner"
CLARIFY = "请明确要查询的论文范围、筛选条件或学生。"
UNSUPPORTED = "当前仅支持论文查询，暂未开放奖学金查询。"
INVALID = "规划服务未返回有效的查询计划"
UNAVAILABLE = "规划服务暂时不可用"
INSTRUCTIONS = (
    "你是教师论文查询规划器。只生成一个结构化 action，不回答问题或生成数据。"
    "今年论文发表情况是全年 status_date、按 publication_status 分组、无发表状态筛选。"
    "明确要求已发表、已录用或已投稿时才筛选。统计用 aggregate，名单用 list。"
    "追问用 patch 保留原条件；待审和待补正用 submitted_latest。"
    "博士、硕士用 degree 筛选，值保留中文。并列提出的各项筛选都要保留。"
    "指定学生仅用 student_id eq selected-student；画像用 portrait 并清空 group_by。"
    "域未启用用 unsupported，不明确用 clarify。禁止猜测姓名、学号或其他筛选值。"
)
REPAIR = "上一轮缺少唯一有效的结构化计划。请依据原问题和契约重新提交一次。replace 只传 action 和 spec，patch 只传 action 和 patch。"


@dataclass(frozen=True, slots=True)
class PlanRequest:
    user_message: str
    previous_spec: QuerySpec | None
    today: date
    enabled_domains: tuple[DomainName, ...] = ("paper",)
    budget: TurnBudget = TurnBudget()


@dataclass(frozen=True, slots=True)
class PlannerTrace:
    mode: PlannerMode
    action: Literal["replace", "patch", "clarify", "unsupported", "direct"]
    latency_ms: int
    skill: str | None = None
    skill_hash: str | None = None
    repair_attempts: int = 0
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PlanResult:
    output: PlannerOutput
    trace: PlannerTrace


class QueryPlanner(Protocol):
    mode: PlannerMode

    def plan(self, request: PlanRequest) -> PlanResult: ...


def _result(mode, start, output, repairs=0):
    return PlanResult(output, PlannerTrace(
        mode, output.action, round((time.monotonic() - start) * 1000),
        skill=SKILL_NAME if mode == "innoagent" else None, repair_attempts=repairs,
    ))


def _unsupported(domain):
    return UnsupportedAction(requested_domain=domain, message=UNSUPPORTED)


_SEARCH_QUOTES = str.maketrans(dict.fromkeys("‘’“”「」『』《》'", '"'))
_PAPER_SEARCH_TEXT = re.compile(
    r'(?:论文)?(?:标题|题目|主题)(?:中)?(?:包含|含有|为|是)'
    r'(?:"[^"]*"|[^，。！？；,.!?;]+?(?=的论文|[，。！？；,.!?;]|并|且|以及|同时|$))'
    r'|(?:关于|有关)(?:"[^"]*"|[\u4e00-\u9fff]{0,8}奖学金'
    r'(?:申请|申报|评审|评选|发放|政策|制度|流程|研究)*)(?=的论文)'
)
_AWARD_DATA = re.compile(
    r"(?:学生|同学)的?获奖|论文(?:曾|是否)?获奖"
    r"|获奖的?(?:学生|同学|论文|名单|人数|记录|情况)"
)


def requests_scholarship(message: str) -> bool:
    """Recognize common Chinese requests that require scholarship data."""
    text = "".join(message.split()).rstrip("。！？.!?").translate(_SEARCH_QUOTES)
    question = _PAPER_SEARCH_TEXT.sub("。", text)
    return "奖学金" in question or bool(_AWARD_DATA.search(question))


def requests_only_published(message: str) -> bool:
    return _requests_published(message)


def _requests_published(message: str, *, allow_combined_statuses: bool = False) -> bool:
    text = re.sub(r"[^\S\n]+", "", message).translate(_SEARCH_QUOTES)
    question = re.sub(r'"[^"]*"', "", _PAPER_SEARCH_TEXT.sub("", text)).strip("。！？.!?；;\n")
    published = r"已(?:经)?发表|发表[过了]"
    if allow_combined_statuses:
        other_status = r"(?<![未没不])(?:已(?:经)?)?(?:录用|投稿)"
        conjunction = r"(?:和|与|以及|及|、|或者?)"
        question = re.sub(
            rf"(?:{other_status}{conjunction})*({published})(?:{conjunction}{other_status})*",
            r"\1",
            question,
        )
    return bool(re.search(published, question)) and not re.search(
        r"[。！？!?；;\n]|(?<!\d)\.(?!\d)"
        r"|发表状态|发表情况|录用|投稿|未发表|未曾|从未|尚未|还未|没有|并未|还没|没发表|不曾|不含|不包括|排除"
        r"|(?:再|另|同时|并且?)(?:看|列|查|统计|汇总|对比|比较)",
        question,
    )


def _period(message, today):
    year_match = re.search(r"((?:19|20)\d{2})年(?!级)", message)
    if year_match or any(term in message for term in ("今年", "本年", "去年", "上一年")):
        year = int(year_match[1]) if year_match else today.year - int("去年" in message or "上一年" in message)
        first, last = date(year, 1, 1), date(year, 12, 31)
    elif any(term in message for term in ("本月", "这个月", "上个月")):
        month = today.replace(day=1) - timedelta(days=1) if "上个月" in message else today
        first, last = month.replace(day=1), month.replace(day=calendar.monthrange(month.year, month.month)[1])
    else:
        return None
    return PaperTimeRange(date_from=first.isoformat(), date_to=last.isoformat())


def _previous_view(spec):
    if spec and any(item.field in SUBJECT_FIELDS for item in spec.filters):
        spec = with_subject(spec, [SELECTED_STUDENT])
    return planner_view(spec)


def _rule_action(request):
    message = "".join(request.user_message.split())
    previous = _previous_view(request.previous_spec)
    clarify = ClarifyAction(message=CLARIFY)
    if requests_scholarship(message):
        return _unsupported("scholarship")
    if not safe_language(message) or re.search(r"学期|学年|还没|没有|清除|移除|取消|近一年", message):
        return clarify
    selected = "指定学生" in message
    subject = StudentIdFilter(value=SELECTED_STUDENT)
    if "画像" in message:
        if selected or (previous and any(item.field == "student_id" for item in previous.filters)):
            return ReplaceSpecAction(spec=PaperQuerySpec(
                operation="portrait", filters=[subject], include=["portrait", "sources"],
            ))
        return clarify
    if previous and re.search(r"(上一页|下一页|第一页)", message):
        page = 1 if "第一页" in message else previous.page + (1 if "下一页" in message else -1)
        return PatchSpecAction(patch=QueryPatch(page=max(1, min(page, 500))))

    filters = [subject] if selected else []
    summary = "发表情况" in message
    publication_status_grouping = bool(re.search(r"按(?:照)?发表状态|发表状态(?:分组|分布)", message))
    includes_published = _requests_published(message, allow_combined_statuses=True)
    if publication_status_grouping:
        includes_published = includes_published or _requests_published(
            re.sub(r"按(?:照)?发表状态(?:分组|分布)?", "", message), allow_combined_statuses=True,
        )
    for field_type, terms in (
        (PublicationStatusFilter, (("发表", "published"), ("录用", "accepted"), ("投稿", "submitted"))),
        (ReviewStatusFilter, (("待审", "pending_review"), ("待补正", "returned"), ("退回", "returned"),
                              ("已归档", "archived"), ("通过审核", "approved"))),
        (DegreeFilter, (("硕士", "硕士"), ("博士", "博士"), ("未标注", "未标注"))),
    ):
        values = list(dict.fromkeys(value for term, value in terms
                                    if term in message and not (term == "发表" and not includes_published)))
        if values:
            filters.append(field_type(value=values[0]) if len(values) == 1
                           else field_type(operator="in", value=values))
    cohort = re.search(r"((?:19|20)\d{2})级", message)
    if cohort:
        filters.append(YearFilter(value=cohort[1]))
    changes = {}
    period = _period(message, request.today)
    if period:
        changes["time_range"] = period
    if re.search("名单|列表|列出|哪些", message):
        changes.update(operation="list", group_by=[])
    elif summary or re.search("统计|汇总|数量|多少|人数|分组|分布", message):
        changes["operation"] = "aggregate"
    if re.search("人数|多少人|几个人|每人|去重", message):
        changes["distinct_subject"] = "student"
    for term, field in (("学位", "degree"), ("年级", "year"), ("专业", "major"),
                        ("阶段", "stage"), ("审核状态", "review_status"), ("(?:发表)?状态", "publication_status")):
        if re.search(f"按(?:照)?{term}|{term}(?:分组|分布)", message):
            changes["group_by"] = [field]
            break
    if summary and "group_by" not in changes:
        changes["group_by"] = ["publication_status"]
    if "最新" in message or any(isinstance(item, ReviewStatusFilter) and item.requires_submitted_latest()
                                for item in filters):
        changes["basis"] = "submitted_latest"
    if previous and previous.domain == "paper" and (not summary or "只看" in message):
        if changes or filters:
            return PatchSpecAction(patch=QueryPatch(set_filters=filters, **changes))
        return clarify
    if "论文" not in message and not filters:
        return clarify
    return ReplaceSpecAction(spec=PaperQuerySpec(filters=filters, **changes))


class RuleQueryPlanner:
    mode = "rules"

    def plan(self, request: PlanRequest) -> PlanResult:
        start = time.monotonic()
        return _result(self.mode, start, _rule_action(request))


@dataclass(frozen=True, slots=True)
class TeacherAgentConfig:
    mode: PlannerMode
    base_url: str = ""
    model: str = ""
    skill: str = SKILL_NAME
    expected_skill_hash: str | None = None
    timeout_seconds: int | None = None
    queue_timeout_seconds: int = 5
    max_attempts: int = 1
    max_concurrency: int = 4
    shares_review_endpoint: bool = False
    allow_internal_http: bool = False
    grant_dir: str = ""

    def __post_init__(self):
        if self.timeout_seconds is None:
            object.__setattr__(self, "timeout_seconds", 120 if self.mode == "innoagent" else 25)


def validate_endpoint_url(base_url: str, *, allow_internal_http: bool = False) -> str:
    url = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if (parsed.scheme not in ("https", "http") or not parsed.hostname or port == 0
                or parsed.username is not None or parsed.password is not None
                or any(char in url for char in "?#\\") or any(char.isspace() for char in url)):
            raise ValueError
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "::1", "127.0.0.1") and not allow_internal_http:
            raise ValueError
    except ValueError:
        raise PlannerConfigError("规划服务地址无效或未启用安全传输") from None
    return url


def teacher_agent_config() -> tuple[TeacherAgentConfig, str]:
    mode = os.getenv("TEACHER_AGENT_MODE", "innoagent").strip().lower()
    if mode == "rules":
        return TeacherAgentConfig("rules"), ""
    if mode not in ("innoagent", "chat"):
        raise PlannerConfigError("未知的教师规划模式")
    review_url = os.getenv("AI_BASE_URL", "").strip().rstrip("/")
    allow_http = os.getenv("TEACHER_AGENT_ALLOW_INTERNAL_HTTP", os.getenv("AI_ALLOW_INTERNAL_HTTP", "")
                           if mode == "chat" else "") == "1"
    url = validate_endpoint_url(os.getenv("TEACHER_AGENT_BASE_URL", review_url if mode == "chat" else ""),
                                allow_internal_http=allow_http)
    shared = url == review_url
    grant_dir = os.getenv("TEACHER_AGENT_GRANT_DIR", "") if mode == "innoagent" else ""
    if mode == "innoagent" and (shared or not Path(grant_dir).is_absolute()):
        raise PlannerConfigError("请配置教师专用服务地址和授权目录")
    model = os.getenv("TEACHER_AGENT_MODEL", os.getenv("AI_MODEL", "") if shared and mode == "chat" else "")
    if mode == "chat" and not model.strip():
        raise PlannerConfigError("聊天规划模式需要指定模型")
    try:
        timeout_value = os.getenv("TEACHER_AGENT_TIMEOUT_SECONDS")
        timeout = int(timeout_value) if timeout_value is not None else None
        queue = int(os.getenv("TEACHER_AGENT_QUEUE_TIMEOUT_SECONDS", "5"))
        concurrency = int(os.getenv("TEACHER_AGENT_MAX_CONCURRENCY", "4"))
        if (timeout is not None and timeout < 1) or concurrency < 1 or queue < 0:
            raise ValueError
    except ValueError:
        raise PlannerConfigError("规划服务超时或并发配置无效") from None
    key = os.getenv("TEACHER_AGENT_API_KEY", os.getenv("AI_API_KEY", "") if shared and mode == "chat" else "")
    return TeacherAgentConfig(
        mode=mode,
        base_url=url,
        model=model.strip(),
        timeout_seconds=timeout,
        queue_timeout_seconds=queue,
        max_concurrency=concurrency,
        shares_review_endpoint=shared,
        allow_internal_http=allow_http,
        grant_dir=grant_dir,
    ), key


@lru_cache
def _service_slots(base_url, capacity):
    return BoundedSemaphore(capacity)


def _http_status(response):
    if response.status_code in (409, 429, 503):
        raise PlannerUnavailableError("规划服务繁忙", retry_after_seconds=1)
    if response.status_code in (401, 403, 404) or response.is_redirect:
        raise PlannerConfigError("请检查规划服务地址、权限和协议")
    if not response.is_success:
        raise PlannerUnavailableError(UNAVAILABLE)


def _validate(raw, request):
    output = PlannerOutputAdapter.validate_python(raw)
    if isinstance(output, ClarifyAction):
        return ClarifyAction(message=CLARIFY)
    if isinstance(output, UnsupportedAction):
        return _unsupported("scholarship") if output.requested_domain == "scholarship" else ClarifyAction(message=CLARIFY)
    if isinstance(output, PatchSpecAction):
        if request.previous_spec is None:
            raise ValueError("missing previous spec")
        spec = apply_patch(request.previous_spec, output.patch)
    else:
        spec = output.spec
    if spec.domain not in request.enabled_domains:
        return _unsupported(spec.domain)
    selectors = [item for item in spec.filters if item.field in SUBJECT_FIELDS]
    needs_subject = "指定学生" in request.user_message
    previous_subject = request.previous_spec and any(item.field in SUBJECT_FIELDS for item in request.previous_spec.filters)
    if selectors or needs_subject:
        if (not (needs_subject or previous_subject) or len(selectors) != 1 or selectors[0].field != "student_id"
                or selectors[0].value != SELECTED_STUDENT or selectors[0].operator != "eq"):
            raise ValueError("invalid local selector")
    return output


def _payload(request):
    return json.dumps({
        "user_message": request.user_message, "today": request.today.isoformat(),
        "previous_spec": request.previous_spec.model_dump(mode="json", by_alias=True) if request.previous_spec else None,
        "enabled_domains": request.enabled_domains,
    }, ensure_ascii=False, separators=(",", ":"))


class _ExternalTransport:
    mode: PlannerMode

    def __init__(self, config: TeacherAgentConfig, *, api_key="", transport=None):
        self.config = config
        self._url = validate_endpoint_url(config.base_url, allow_internal_http=config.allow_internal_http)
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._transport = transport
        self._slots = _service_slots(self._url, 1 if self.mode == "innoagent" else config.max_concurrency)

    def _call(self, operation, *args):
        if not self._slots.acquire(timeout=self.config.queue_timeout_seconds):
            raise PlannerUnavailableError("规划服务繁忙", retry_after_seconds=1)
        try:
            return asyncio.run(self._run(operation, args))
        except (TimeoutError, httpx.TimeoutException):
            raise PlannerUnavailableError("规划服务超时", retry_after_seconds=1) from None
        except httpx.HTTPError:
            raise PlannerUnavailableError(UNAVAILABLE) from None
        finally:
            self._slots.release()

    async def _run(self, operation, args):
        async with httpx.AsyncClient(base_url=self._url, headers=self._headers, timeout=self.config.timeout_seconds,
                                     transport=self._transport, trust_env=False, follow_redirects=False) as client:
            return await operation(client, *args)


class ChatCompletionQueryPlanner(_ExternalTransport):
    mode = "chat"

    def plan(self, request: PlanRequest) -> PlanResult:
        start = time.monotonic()
        if safe_language(request.user_message) is None:
            return _result(self.mode, start, ClarifyAction(message=CLARIFY))
        request = replace(request, previous_spec=_previous_view(request.previous_spec))
        output, repairs = self._call(self._plan, request)
        return _result(self.mode, start, output, repairs)

    async def _plan(self, client, request):
        async with asyncio.timeout(self.config.timeout_seconds), self._conversation(client, request) as submit:
            for repair in range(2):
                try:
                    return _validate(await submit(repair), request), repair
                except (KeyError, IndexError, TypeError, ValueError):
                    if repair:
                        raise PlannerInvalidOutputError(INVALID) from None

    @asynccontextmanager
    async def _conversation(self, client, request):
        schema = json.dumps(PlannerOutputAdapter.json_schema(by_alias=True), ensure_ascii=False, separators=(",", ":"))
        messages = [{"role": "system", "content": f"{INSTRUCTIONS} 只返回符合以下 JSON Schema 的 JSON 对象：{schema}"},
                    {"role": "user", "content": _payload(request)}]

        async def submit(repair):
            if repair:
                messages.append({"role": "user", "content": REPAIR})
            response = await client.post("chat/completions", json={
                "model": self.config.model, "messages": messages, "temperature": 0,
                "response_format": {"type": "json_object"},
            })
            _http_status(response)
            choice = response.json()["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("incomplete")
            text = choice["message"]["content"]
            if not isinstance(text, str) or len(text) > 64_000:
                raise ValueError("invalid content")
            messages.append({"role": "assistant", "content": text})
            return json.loads(text)

        yield submit


async def _object(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    _http_status(response)
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError
        return value
    except ValueError:
        raise PlannerConfigError("规划服务返回了不兼容的协议") from None


def _resource_id(value):
    return isinstance(value, str) and re.fullmatch(r"[\w.-]{1,255}", value) and value not in (".", "..", "tmp")


async def _delete_session(client, session_id):
    path = f"api/sessions/{quote(session_id, safe='')}"
    response = await client.delete(path)
    if response.status_code == 409:
        status = await _object(client, "GET", f"api/chat/status/{session_id}")
        turn = (status.get("stream") or {}).get("turnId")
        if _resource_id(turn):
            await _object(client, "POST", f"api/chat/{session_id}/{turn}/abort")
        response = await client.delete(path)
        while response.status_code == 409:
            await asyncio.sleep(0.1)
            response = await client.delete(path)
    if response.status_code != 404:
        _http_status(response)


@contextmanager
def _session_grant(directory, session_id, issue_token: Callable[[], str]):
    root = Path(directory)
    if not root.is_absolute():
        raise PlannerConfigError("请配置教师查询授权专用绝对目录")
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise PlannerConfigError("教师查询授权目录必须为服务账户私有")
        target = root / session_id
        with NamedTemporaryFile(dir=root) as staging:
            staging.write(issue_token().encode("ascii"))
            staging.flush()
            os.link(staging.name, target)
    except (OSError, UnicodeError):
        raise PlannerConfigError("无法创建本次教师查询授权") from None
    try:
        yield
    finally:
        target.unlink(missing_ok=True)


def _reject_json_constant(_value):
    raise ValueError("Nonfinite JSON constant")


@lru_cache(maxsize=1)
def _compact_domain_schema() -> str:
    schema = export_paper_tool_input_schema()
    definitions = schema["$defs"]
    spec = definitions[schema["properties"]["spec"]["$ref"].rsplit("/", 1)[1]]["properties"]
    patch = definitions[schema["properties"]["patch"]["$ref"].rsplit("/", 1)[1]]["properties"]
    time_range = definitions["PaperTimeRange"]
    filters = {}
    for field, ref in spec["filters"]["items"]["discriminator"]["mapping"].items():
        properties = definitions[ref.rsplit("/", 1)[1]]["properties"]
        value = properties["value"]
        scalar = next(choice for choice in value.get("anyOf", [value]) if choice["type"] != "array")
        operator = properties["operator"]
        filters[field] = {
            "operator": operator["enum"] if "enum" in operator else [operator["const"]],
            "value": scalar.get("enum", scalar["type"]),
        }
    return json.dumps({
        "spec_fields": list(spec),
        "patch_fields": list(patch),
        "operation": spec["operation"]["enum"],
        "basis": spec["basis"]["enum"],
        "time_range": {
            **dict.fromkeys(time_range["required"], "YYYY-MM-DD"),
            "field": time_range["properties"]["field"]["enum"],
        },
        "group_by": spec["group_by"]["items"]["enum"],
        "distinct_subject": spec["distinct_subject"]["enum"],
        "include": spec["include"]["items"]["enum"],
        "filter_fields": filters,
    }, ensure_ascii=False, separators=(",", ":"))


def _validate_tool_target(arguments) -> bool:
    if (not isinstance(arguments, dict) or arguments.keys() != {"server", "tool", "args"}
            or arguments["server"] != MCP_SERVER or arguments["tool"] != MCP_QUERY_TOOL):
        raise PlannerInvalidOutputError("论文查询工具参数无效")
    inner = arguments["args"]
    if isinstance(inner, str):
        try:
            inner = json.loads(inner, parse_constant=_reject_json_constant)
        except (ValueError, RecursionError):
            return False
    return (isinstance(inner, dict) and inner.keys() in ({"spec"}, {"patch"})
            and isinstance(next(iter(inner.values())), dict))


_MCP_SCHEMA_ERROR = re.compile(
    r"data(?: must NOT have (?:(?:more|fewer) than [0-9]+ |additional )properties|"
    r"/(?:spec|patch)(?:/[A-Za-z0-9_~-]+)* (?:"
    r"must be (?:object|array|string|integer|number|boolean|null|equal to (?:constant|one of the allowed values))|"
    r"must match (?:a schema in (?:anyOf|oneOf)|exactly one schema in oneOf|pattern \"[^\n\"]+\")|"
    r"must have required property '[A-Za-z0-9_]+'|must NOT have additional properties|"
    r"must NOT have (?:more|fewer) than [0-9]+ (?:items|characters)|must [<>]=? -?[0-9]+))"
)


def _local_validation_error(event, invalid_args: bool):
    result = event.get("result")
    if not isinstance(result, dict):
        return False
    details = result.get("details")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return False
    part = content[0]
    if not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str):
        return False
    text = part["text"]
    if details == {}:
        if invalid_args and text == MCP_INVALID_ARGS:
            return True
        return text.startswith(f'Validation failed for tool "{TOOL_NAME}":\n') and "\n\nReceived arguments:\n" in text
    if (not isinstance(details, dict) or details.get("mode") != "call"
            or details.get("server") != MCP_SERVER or details.get("tool") != MCP_QUERY_TOOL
            or details.get("error") != "call_failed" or "mcpResult" in details
            or not isinstance(message := details.get("message"), str)):
        return False
    return (text.startswith(f"Failed to call tool: {message}\n\nExpected parameters:\n")
            and all(_MCP_SCHEMA_ERROR.fullmatch(error) for error in message.split(", ")))


def _tool_outcome(event, invalid_args: bool) -> Literal["query", "clarification", "retry"]:
    is_error = event.get("isError")
    if is_error is True and _local_validation_error(event, invalid_args):
        return "retry"

    result = event.get("result")
    details = result.get("details") if isinstance(result, dict) else None
    if (not isinstance(details, dict) or details.get("mode") != "call"
            or details.get("server") != MCP_SERVER or details.get("tool") != MCP_QUERY_TOOL):
        raise PlannerInvalidOutputError("论文查询工具未成功执行")
    receipt = details.get("mcpResult")
    if not isinstance(receipt, dict) or not isinstance(is_error, bool) or receipt.get("isError") is not is_error:
        raise PlannerInvalidOutputError("论文查询工具未成功执行")
    structured = receipt.get("structuredContent")
    if not isinstance(structured, dict):
        raise PlannerInvalidOutputError("论文查询工具缺少有效结果")
    code = structured.get("code")
    if is_error:
        if details.get("error") == "tool_error" and code == "RETRYABLE_TOOL_INPUT":
            return "retry"
    elif "error" not in details:
        if code == "CLARIFICATION_NEEDED" and "query_run_id" not in structured:
            return "clarification"
        run_id = structured.get("query_run_id")
        if code is None and isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            return "query"
    raise PlannerInvalidOutputError("论文查询工具未成功执行")


class InnoAgentQueryPlanner(_ExternalTransport):
    mode = "innoagent"

    def analyze(self, request: PlanRequest, issue_token: Callable[[], str]) -> str:
        return self._call(self._analyze, request, issue_token)

    async def _analyze(self, client, request, issue_token):
        defaults = PaperQuerySpec().model_dump_json(by_alias=True, exclude_none=True)
        budget = request.budget
        proxy_query = json.dumps(
            {"server": MCP_SERVER, "tool": MCP_QUERY_TOOL, "args": {"spec": {}}}, separators=(",", ":"),
        )
        prompt = (
            f"/skill:{SKILL_NAME} 通过 mcp({proxy_query}) 查询论文，args 只包含一个 spec 或 patch 对象。"
            f"最多 {budget.max_queries} 次成功查询，"
            f"同一轮最多纠错 {budget.max_tool_retries} 次。用中文直接给出结论，每句都带对应查询的引用。"
            "计数只用工具返回的 metric_refs 完整值，系统会填入数值。省略开场、过程和额外总结。"
            "正文使用带引用的纯文本。成功查询有数据时，主动按技能为当轮问题设计一个响应式、可交互的 visual-html，"
            "从 window.__INNOGRAD_DATA__.runs 读取实际数据。短标题最多突出一个关键数字。"
            "首屏先放回答问题的主视图和主要操作，避免重复指标卡，标签清楚，图表关闭入场动画。"
            "正文、标题和界面使用教师日常用语。写「查看已发表论文」，不要写「下钻」或「可下钻」。"
            "年度发表概览和博士生追问直接遍历 run.breakdown，逐行渲染原生按钮，直接用已中文化的 row.label"
            "（如「已发表」）作为可见文字和可访问名称，点击时原样传入 row.drilldownPatch。"
            "不要按推测的英文状态键预筛选或重建分组。"
            "论文列表中用「材料详情」按钮打开对应材料。问题不明确时直接询问。"
            f"\n{MCP_SERVER}/{MCP_QUERY_TOOL} 的参数字段和可选值：\n{_compact_domain_schema()}"
            f"\n默认查询：{defaults}\n{_payload(request)}"
        )
        async with AsyncExitStack() as cleanup, asyncio.timeout(self.config.timeout_seconds):
            session_id = await cleanup.enter_async_context(self._session(client))
            with _session_grant(self.config.grant_dir, session_id, issue_token):
                return await self._analysis_stream(client, session_id, prompt, budget)

    @asynccontextmanager
    async def _session(self, client):
        settings = await _object(client, "GET", "api/settings")
        memory = settings.get("memory")
        if not isinstance(memory, dict) or not all(memory.get(f"l{level}Enabled") is False for level in (1, 2, 3)):
            raise PlannerConfigError("教师规划实例需要关闭跨会话记忆")
        name = f"teacher-query-{uuid4().hex}"
        workspace = await _object(client, "POST", "api/workspaces", json={"name": name, "isTemp": False})
        workspace_id = workspace.get("id")
        if not _resource_id(workspace_id) or workspace.get("name") != name or workspace.get("isTemp") is not False:
            raise PlannerConfigError("规划服务未创建独立工作区")
        session_id = None
        terminal_error = False
        try:
            session = await _object(client, "POST", "api/sessions", json={"workspaceId": workspace_id})
            if not _resource_id(session.get("id")):
                raise PlannerConfigError("规划会话标识无效")
            session_id = session["id"]
            if session.get("workspaceId") != workspace_id:
                raise PlannerConfigError("规划会话未绑定到独立工作区")
            yield session_id
        except (PlannerConfigError, PlannerInvalidOutputError):
            terminal_error = True
            raise
        finally:
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    try:
                        if session_id:
                            await _delete_session(client, session_id)
                    finally:
                        response = await client.delete(f"api/workspaces/{workspace_id}", params={"removeFiles": 1})
                        if response.status_code != 404:
                            _http_status(response)
            except PlannerUnavailableError:
                if not terminal_error:
                    raise
            except (TimeoutError, httpx.HTTPError):
                if not terminal_error:
                    raise PlannerUnavailableError("规划工作区清理未完成") from None

    async def _analysis_stream(self, client, session_id, prompt, budget: TurnBudget):
        request_id = str(uuid4())
        body = {"prompt": prompt, "sessionId": session_id, "clientRequestId": request_id}
        async with client.stream("POST", "api/chat/stream", json=body) as response:
            _http_status(response)
            started = set()
            finished = set()
            proposed = set()
            invalid_args = set()
            successful_queries = 0
            tool_retries = 0
            text = []
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    raise PlannerInvalidOutputError("规划流缺少回合结束事件")
                try:
                    envelope = json.loads(data)
                except ValueError:
                    raise PlannerInvalidOutputError("规划事件格式无效") from None
                if (not isinstance(envelope, dict) or envelope.get("sessionId") != session_id
                        or envelope.get("clientRequestId") != request_id or not isinstance(envelope.get("event"), dict)):
                    raise PlannerInvalidOutputError("规划事件与请求不匹配")
                event = envelope["event"]
                kind = event.get("type")
                if not isinstance(kind, str):
                    raise PlannerInvalidOutputError("规划事件类型无效")
                if kind == "error":
                    raise PlannerUnavailableError(UNAVAILABLE)
                if kind in ("aborted", "question", "permission_request"):
                    raise PlannerInvalidOutputError("规划回合中止或需要额外授权")
                if kind in ("tool_call_start", "tool_call_delta"):
                    name = event.get("toolName")
                    if name is not None and (not isinstance(name, str) or not TOOL_NAME.startswith(name)):
                        raise PlannerConfigError("规划实例启用了额外工具")
                elif kind in ("tool_call_end", "tool_start", "tool_update", "tool_end"):
                    if event.get("toolName") != TOOL_NAME:
                        raise PlannerConfigError("规划实例启用了额外工具")
                    call_id = event.get("toolCallId")
                    if not isinstance(call_id, str) or not call_id:
                        raise PlannerInvalidOutputError("查询调用缺少标识")
                    if kind in ("tool_call_end", "tool_start") and not _validate_tool_target(event.get("args")):
                        invalid_args.add(call_id)
                    if kind == "tool_call_end":
                        if call_id in proposed or call_id in started:
                            raise PlannerInvalidOutputError("重复的查询调用")
                        proposed.add(call_id)
                    elif kind == "tool_start":
                        if call_id in started:
                            raise PlannerInvalidOutputError("重复的查询调用")
                        if successful_queries + len(started) - len(finished) >= budget.max_queries:
                            raise PlannerInvalidOutputError("本次论文查询次数超限")
                        started.add(call_id)
                        text.clear()
                    elif kind in ("tool_update", "tool_end"):
                        if call_id not in started or call_id in finished:
                            raise PlannerInvalidOutputError("查询调用未正确配对")
                        if kind == "tool_end":
                            outcome = _tool_outcome(event, call_id in invalid_args)
                            if call_id in invalid_args and outcome != "retry":
                                raise PlannerInvalidOutputError("论文查询工具参数无效")
                            if outcome == "query":
                                successful_queries += 1
                            elif outcome == "retry":
                                tool_retries += 1
                                if tool_retries > budget.max_tool_retries:
                                    raise PlannerInvalidOutputError("本次论文查询纠错次数超限")
                            finished.add(call_id)
                            text.clear()
                elif kind == "system_event" and event.get("eventType") in ("message_start", "auto_retry_start"):
                    text.clear()
                elif kind == "text_delta":
                    delta = event.get("delta")
                    if not isinstance(delta, str) or started != finished:
                        raise PlannerInvalidOutputError("无效的分析文本")
                    text.append(delta)
                elif kind == "done":
                    analysis = "".join(text).strip()
                    if started != finished or not proposed <= finished or not analysis:
                        raise PlannerInvalidOutputError("论文分析未完成")
                    return analysis
            raise PlannerUnavailableError("规划服务连接提前结束")


def build_planner() -> QueryPlanner | InnoAgentQueryPlanner:
    config, api_key = teacher_agent_config()
    if config.mode == "rules":
        return RuleQueryPlanner()
    planner = InnoAgentQueryPlanner if config.mode == "innoagent" else ChatCompletionQueryPlanner
    return planner(config, api_key=api_key)
