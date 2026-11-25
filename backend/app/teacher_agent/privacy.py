import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select

from ..db import StudentProfile, User
from .contract import METRIC_CATALOG, PaperQuerySpec, ResultEnvelope, StudentIdFilter, validate_query_spec
from .errors import PlannerInvalidOutputError, ResourceNotFoundError, RetryableToolInputError, TeacherAgentError


SELECTED_STUDENT = "selected-student"
SUBJECT_FIELDS = {"student_name", "student_id", "student_number"}
TEXT_FIELDS = {"major", "direction", "stage", "journal", "title", "award_name", "award_level"}
_WORDS = """
请问 请帮我 帮忙 帮我 请 给我 帮我看一下 看一下 一下 想知道 想看 麻烦
我指导的 指导范围内 我带的 我名下的 我们 我 的 中 在 有关 按照 按 以
今年 去年 本年 上一年 近一年 本月 这个月 上个月 学年 学期 年 月 日 级
论文 学生 同学 导师 硕士 博士 未标注 研究生 学位 年级 专业 方向 阶段
发表情况 发表 发表了 已发表 录用 已录用 投稿 已投稿 待审 待审核 待补正 已退回 退回
已归档 归档 有效 历史 最新 申报 提交 通过 审核 状态 情况 如何 怎么样 怎样
统计 汇总 概览 多少 几个 几篇 数量 总数 人数 分别 各个 各有 一共 共 记录
只看 仅看 只要 只 看 查看 查询 查 筛选 过滤 所有 全部 仅 显示 列出 列表 名单
画像 详细 详情 材料 证据 原件 下钻 打开 继续 再 其中 那些 哪些 哪位 哪个 哪
指定学生 奖学金 申请 获奖 按状态 分组 分布 排序 升序 降序 分页 下一页
上一页 第一页 去重 每人 每个 每页 分开 分别 对比 比较 和 与 或者 或 以及 而且
已经 还没 还没有 没有 包含 只包含 是 我 想 要 看看 能否 可以 吗 呢 吧 了
把 将 从 到 给 做 个 都 分 成 类 下 跟进 变成 改成 换成 清除 移除 取消
篇 条 位 人 个 页 名 单 数 教师 论文题目 论文标题 期刊 有无 DOI doi
""".split()
_VOCAB = re.compile("|".join(map(re.escape, sorted(set(_WORDS), key=len, reverse=True))))
_CLARIFICATION_WORDS = set(_WORDS) | set("您 还是 明确 选择 提供 指定 范围 条件 哪一位".split())
_CLARIFICATION_VOCAB = re.compile("|".join(map(re.escape, sorted(_CLARIFICATION_WORDS, key=len, reverse=True))))
_YEAR = re.compile(r"(?<![0-9])(?:19|20)[0-9]{2}(?=\s*[年级])")
_PUNCTUATION = re.compile(r"[\s，。！？、；：,.?!：:（）()“”「」『』《》\-—]+")


@dataclass(frozen=True)
class Student:
    id: str
    name: str
    number: str


def roster(session, student_ids):
    rows = session.execute(select(User.id, User.name, StudentProfile.number)
                           .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
                           .where(User.id.in_(student_ids)))
    return [Student(row.id, row.name, row.number or "") for row in rows]


def safe_language(message, *, vocabulary=_VOCAB):
    parts = []
    cursor = 0
    while cursor < len(message):
        match = (vocabulary.match(message, cursor) or _YEAR.match(message, cursor)
                 or _PUNCTUATION.match(message, cursor))
        if match is None:
            return None
        parts.append(" " if _PUNCTUATION.fullmatch(match[0]) else match[0])
        cursor = match.end()
    return "".join(parts).strip() or None


def _roster_mentions(message, students):
    matches = {}
    for student in students:
        for identifier in (student.name, student.name.removesuffix("（模拟）"), student.number, student.id):
            if identifier and identifier in message:
                matches.setdefault(identifier, set()).add(student.id)
    if matches:
        pattern = re.compile("|".join(map(re.escape, sorted(matches, key=len, reverse=True))))
        for match in pattern.finditer(message):
            yield match, matches[match[0]]


def prepare_question(message, students):
    parts, selected, cursor = [], set(), 0
    for match, ids in _roster_mentions(message, students):
        parts.extend((message[cursor:match.start()], "指定学生"))
        selected.update(ids)
        cursor = match.end()
    parts.append(message[cursor:])
    return safe_language("".join(parts)), sorted(selected)


def subject_filter(ids):
    if not ids:
        raise ResourceNotFoundError("记录不存在或无权访问")
    if len(ids) > 50:
        raise TeacherAgentError("命中的学生超过 50 人，请缩小筛选范围")
    return StudentIdFilter(operator="eq" if len(ids) == 1 else "in", value=ids[0] if len(ids) == 1 else sorted(ids))


def resolve_subjects(spec, students, *, retry_unknown_name=False):
    selectors = [item for item in spec.filters if item.field in SUBJECT_FIELDS]
    if not selectors:
        return spec
    visible_ids = {student.id for student in students}
    matched = visible_ids.copy()
    unknown_name = False
    for item in selectors:
        if item.field == "student_id":
            requested = set(item.value if isinstance(item.value, list) else [item.value])
            if not requested <= visible_ids:
                raise ResourceNotFoundError("记录不存在或无权访问")
            matched &= requested
        else:
            attr = "number" if item.field == "student_number" else "name"
            if item.operator == "contains":
                matches = {student.id for student in students if item.value.casefold() in getattr(student, attr).casefold()}
            else:
                matches = {student.id for student in students if getattr(student, attr) == item.value}
            if not matches and item.field == "student_number":
                raise ResourceNotFoundError("记录不存在或无权访问")
            unknown_name |= not matches and item.field == "student_name"
            matched &= matches
    if retry_unknown_name and unknown_name:
        raise RetryableToolInputError("student_name 未匹配当前可查询的学生，请核对姓名或请教师确认。")
    return with_subject(spec, sorted(matched))


def with_subject(spec, ids):
    raw = spec.model_dump(by_alias=True)
    raw["filters"] = [item for item in raw["filters"] if item["field"] not in SUBJECT_FIELDS]
    raw["filters"].append(subject_filter(ids).model_dump())
    return validate_query_spec(raw)


def student_ids(spec):
    if spec:
        for item in spec.filters:
            if item.field == "student_id":
                return item.value if isinstance(item.value, list) else [item.value]
    return []


def free_text_filter(item):
    if item.field == "year":
        return any(not re.fullmatch(r"(?:19|20)[0-9]{2}级", str(value))
                   for value in (item.value if isinstance(item.value, list) else [item.value]))
    return item.field in TEXT_FIELDS


def planner_view(spec):
    if spec is None:
        return None
    safe = with_subject(spec, [SELECTED_STUDENT]) if student_ids(spec) else spec
    raw = safe.model_dump(by_alias=True)
    raw["filters"] = [item.model_dump() for item in safe.filters if not free_text_filter(item)]
    return validate_query_spec(raw)


def prepare_agent_question(message: str, students) -> tuple[str | None, list[str]]:
    matches = [ids for _, ids in _roster_mentions(message, students)]
    explicit = set().union(*(ids for ids in matches if len(ids) == 1))
    selected = set().union(*(ids & explicit or ids for ids in matches))
    return message.strip() or None, sorted(selected)


def agent_clarification_subjects(message, students):
    matches = [ids for _, ids in _roster_mentions(message, students)]
    explicit = set().union(*(ids for ids in matches if len(ids) == 1))
    return sorted(set().union(*(ids for ids in matches if len(ids) > 1 and ids.isdisjoint(explicit))))


def safe_agent_clarification(text: str) -> str | None:
    line = text.strip()
    if not line or len(line) > 200 or len(line.splitlines()) != 1 or re.search(r"[。！？.!?]", line[:-1]):
        return None
    if line.endswith(("？", "?")) or line.startswith(("请明确", "请选择", "请提供", "请指定")):
        return line if safe_language(line, vocabulary=_CLARIFICATION_VOCAB) else None
    return None


def resolve_agent_spec(spec: PaperQuerySpec, selected, visible_students) -> PaperQuerySpec:
    if not isinstance(spec, PaperQuerySpec):
        raise PlannerInvalidOutputError("当前工具仅支持论文查询")
    requested = set(student_ids(spec))
    if SELECTED_STUDENT in requested:
        if not selected:
            raise PlannerInvalidOutputError("查询中的指定学生无效")
        requested.remove(SELECTED_STUDENT)
        requested.update(selected)
        raw = spec.model_dump(by_alias=True)
        raw["filters"] = [subject_filter(sorted(requested)).model_dump() if item["field"] == "student_id" else item
                          for item in raw["filters"]]
        spec = validate_query_spec(raw)
    return resolve_subjects(spec, visible_students, retry_unknown_name=True)


def _metrics(result: ResultEnvelope) -> dict[str, int]:
    return {card.key: card.value for card in result.summary.metrics
            if card.key in METRIC_CATALOG and card.group_key is None}


def agent_tool_view(result: ResultEnvelope) -> dict:
    if result.status != "ok":
        raise TeacherAgentError("请明确查询范围或选择一位学生")
    detail = result.applied_query.operation != "aggregate"
    return {
        "query_run_id": result.query_run_id,
        "metrics": _metrics(result),
        "breakdown": [row.model_dump(include={"group_key", "record_count", "student_count"})
                      for row in result.summary.breakdown],
        "items": [item.model_dump(mode="json", by_alias=True) for item in result.items] if detail else [],
        "portrait": result.portrait.model_dump(mode="json", by_alias=True) if detail and result.portrait else None,
    }


_REFERENCE = re.compile(r"\[([A-Za-z0-9_-]+)(?::([A-Za-z0-9_]+))?\]")
_YEAR_LABEL = re.compile(r"(?<![A-Za-z0-9_])([0-9]{4})[ \t]*年(?![ \t]*级)")
_RELATIVE_PERIOD = re.compile(r"(?:上|下|这|那)一个(?:年度|学年|学期|季度|月份|月度|周期|月)")
_CN_NUMBER = r"[〇零一二两兩三四五六七八九十百千万萬亿億壹贰叁肆伍陆柒捌玖拾佰仟半]+"
_QUANTITY = re.compile(
    rf"{_CN_NUMBER}\s*(?:篇|人|项|条|名|位|次|倍|份|个|成|分之|%)|"
    rf"(?:共计?|总计|达到|为|是|有|占|增加|减少|超过|不足|等于)\s*{_CN_NUMBER}(?=\s|[，,。.;；、!！?？]|$)|"
    r"[%‰]|翻番|无人|无(?:任何|学生|论文|记录)|没有(?:任何)?(?:学生|人|论文|记录)|"
    r"(?ai:\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"[a-z]+teen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?)"
    r"\s+(?:papers?|records?|students?|percent)\b)"
)
_UNBOUND_REFERENCE = re.compile(r"[\[\]【】]|(?ai:\b(?:run[-_][a-z0-9_-]+|[a-z]+(?:_[a-z]+)+)\b)")
_INVALID_ANALYSIS = "分析包含未经查询结果验证的引用或数值"
_STATUS_DATE = re.compile(r"(?<![A-Za-z0-9_])status_date(?![A-Za-z0-9_])")
_BOUND_COUNT = re.compile(
    r"(?<![A-Za-z0-9_.+−－-])(?P<count>[0-9]+)[ \t]*(?P<unit>条|篇|人|名|份|项)[ \t]*"
    r"(?=\[(?P<run>[A-Za-z0-9_-]+):(?P<metric>[A-Za-z0-9_]+)\])"
)
_SENTENCE_END = re.compile(
    r"(?:[。！？；;]+|[.!?]+(?=\s|$))[”’」』]?(?:[ \t]*\[[A-Za-z0-9_-]+\](?=[ \t]*(?:\n|$)))*\s*|\n+|\Z"
)


def render_agent_analysis(text: str, results: list[ResultEnvelope]) -> str:
    """Resolve quantitative references locally. Qualitative interpretations remain model-authored."""
    if not isinstance(text, str) or not text.strip():
        raise PlannerInvalidOutputError(_INVALID_ANALYSIS)
    runs = {result.query_run_id: _metrics(result) for result in results if result.status == "ok"}
    text = text.strip()
    cited = {match[1] for match in _REFERENCE.finditer(text)}
    if not cited or not cited <= runs.keys():
        raise PlannerInvalidOutputError(_INVALID_ANALYSIS)
    bound = set()
    for match in _BOUND_COUNT.finditer(text):
        metric = match["metric"]
        value = runs[match["run"]].get(metric)
        if (value is None or match["count"] != str(value)
                or text[:match.start()].rstrip().endswith(("-", "+", "−", "－"))):
            raise PlannerInvalidOutputError(_INVALID_ANALYSIS)
        unit = {"篇": "条", "名": "人"}.get(match["unit"], match["unit"])
        if METRIC_CATALOG[metric].unit != unit:
            raise PlannerInvalidOutputError(_INVALID_ANALYSIS)
        bound.add(match.end())
    names, periods = set(), []
    for result in results:
        if result.query_run_id in cited:
            if result.applied_query.time_range:
                period = result.applied_query.time_range
                periods.append((int(period.date_from[:4]), int(period.date_to[:4])))
            if result.applied_query.operation != "aggregate":
                names.update(item.student_name for item in result.items)
                if result.portrait:
                    names.add(result.portrait.student_name)
    prose = _REFERENCE.sub(" ", _BOUND_COUNT.sub(" ", text))
    if all(result.applied_query.time_range and result.applied_query.time_range.field == "status_date"
           for result in results if result.query_run_id in cited):
        prose = _STATUS_DATE.sub(" ", prose)
    for name in sorted(filter(None, names), key=len, reverse=True):
        if any(char.isalpha() and not char.isnumeric() for char in name):
            prose = prose.replace(name, " ")
    prose = unicodedata.normalize("NFKC", prose)
    prose = _RELATIVE_PERIOD.sub(" ", prose)
    prose = _YEAR_LABEL.sub(
        lambda match: " " if any(start <= int(match[1]) <= end for start, end in periods) else match[0], prose)
    if (_UNBOUND_REFERENCE.search(prose) or _QUANTITY.search(prose)
            or any(char.isdigit() or unicodedata.category(char) == "Cf" for char in prose)):
        raise PlannerInvalidOutputError(_INVALID_ANALYSIS)

    def replace(match):
        run, metric = match.groups()
        if run in runs:
            if metric is None or match.start() in bound:
                return f"[{run}]"
            if metric in runs[run]:
                return f"{runs[run][metric]} [{run}]"
        raise PlannerInvalidOutputError(_INVALID_ANALYSIS)

    return _REFERENCE.sub(replace, text)


def _group_summary(card: ResultEnvelope) -> str:
    if card.applied_query.group_by == ["publication_status"]:
        labels = {"published": "已发表", "accepted": "已录用", "submitted": "已投稿"}
        rows = card.summary.breakdown
        if rows and all(row.group_key.get("publication_status") in labels for row in rows):
            counts = "，".join(f"{labels[row.group_key['publication_status']]} {row.record_count} 条" for row in rows)
            return f"{counts} [{card.query_run_id}]。"
    return f"各组统计请查看分组结果卡 [{card.query_run_id}]。"


def render_agent_response(text: str, results: list[ResultEnvelope]) -> tuple[str | None, str | None]:
    """Verify model sentences and use card summaries when the turn includes grouping."""
    kept = []
    omitted = False
    start = 0
    text = text.strip() if isinstance(text, str) else ""
    for end in _SENTENCE_END.finditer(text):
        segment = text[start:end.end()]
        start = end.end()
        sentence = segment.strip()
        if not sentence:
            if kept:
                kept.append(segment)
            continue
        try:
            if not any(char.isalpha() for char in _REFERENCE.sub("", sentence)) and not any(
                    match[2] for match in _REFERENCE.finditer(sentence)):
                raise PlannerInvalidOutputError(_INVALID_ANALYSIS)
            rendered = render_agent_analysis(sentence, results)
        except PlannerInvalidOutputError:
            omitted = True
            continue
        kept.append(segment.replace(sentence, rendered, 1))
    analysis = "".join(kept).strip()
    if not analysis:
        return None, "本次分析未能核实，请以结果卡为准。"
    cards = [result for result in results if result.status == "ok"]
    if any(card.applied_query.group_by for card in cards):
        analysis = "\n".join(
            _group_summary(card)
            if card.applied_query.group_by
            else f"未分组查询 [{card.query_run_id}]：{card.summary.headline}"
            for card in cards
        )
    return analysis, "部分分析未能核实，请以结果卡为准。" if omitted else None
