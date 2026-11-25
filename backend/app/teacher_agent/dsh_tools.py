"""Flat, independently callable paper queries for the teacher MCP endpoint."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from ..db import Audit, User, uid
from .contract import (
    ISO_DATE_PATTERN, PaperQuerySpec, PaperTimeRange, PublicationStatus, StudentDegree,
    VisibleReviewStatus,
)
from .engine import _record_run, _scope
from .errors import TeacherAgentError
from .papers import _roster


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class _PaperFilters(_Input):
    year: int | None = Field(None, ge=1, le=9999, description="整年只传 year，如 2026。按论文当前状态对应的投稿、录用或发表日期筛选。")
    date_from: Annotated[str, Field(pattern=ISO_DATE_PATTERN)] | None = Field(
        None, description="起始日期（含），与 date_to 同传，与 year 互斥。")
    date_to: Annotated[str, Field(pattern=ISO_DATE_PATTERN)] | None = Field(
        None, description="结束日期（含），格式 YYYY-MM-DD。")
    publication_status: PublicationStatus | None = Field(None, description="投稿 submitted、录用 accepted、发表 published。")
    review_status: VisibleReviewStatus | None = Field(
        None, description="默认查询当前有效归档。指定未归档的审核状态时查询最新提交版本。")
    degree: StudentDegree | None = None
    grade: str | None = Field(None, min_length=1, max_length=30, description="学生入学年级，如 2023级。")
    major: str | None = Field(None, min_length=1, max_length=100)
    keyword: str | None = Field(None, min_length=1, max_length=200, description="论文标题包含的关键词。")

    @model_validator(mode="after")
    def validate_dates(self):
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("请同时提供 date_from 和 date_to。")
        if self.year is not None and self.date_from is not None:
            raise ValueError("year 与日期范围只能选择一种。")
        return self

    def query_fields(self):
        time_range = None
        if self.year is not None:
            time_range = PaperTimeRange(date_from=f"{self.year:04}-01-01", date_to=f"{self.year:04}-12-31")
        elif self.date_from is not None:
            time_range = PaperTimeRange(date_from=self.date_from, date_to=self.date_to)
        filters = []
        for name in ("publication_status", "review_status", "degree", "major", "grade", "keyword"):
            value = getattr(self, name)
            if value is not None:
                filters.append({"field": {"grade": "year", "keyword": "title"}.get(name, name),
                                "operator": "contains" if name == "keyword" else "eq", "value": value})
        return {"time_range": time_range, "filters": filters,
                "basis": "current_effective_archives" if self.review_status in (None, "archived") else "submitted_latest"}


class _SummaryInput(_PaperFilters):
    group_by: Literal["publication_status", "review_status", "degree", "grade", "major"] | None = Field(
        None, description="可选的分组维度。每个分组返回可直接执行的 list_papers 下钻参数。")

    def spec(self):
        group = "year" if self.group_by == "grade" else self.group_by
        return PaperQuerySpec(**self.query_fields(), operation="aggregate", group_by=[group] if group else [],
                              include=["metrics"])


class _ListInput(_PaperFilters):
    subject: Literal["paper", "student"] = Field("paper", description="paper 列出论文申报记录，student 列出去重学生。")
    page: int = Field(1, ge=1, le=500)
    page_size: int = Field(50, ge=1, le=100)

    def spec(self):
        return PaperQuerySpec(**self.query_fields(), operation="list", page=self.page, page_size=self.page_size,
                              distinct_subject="student" if self.subject == "student" else "paper_record",
                              include=["items", "sources"])


class _PortraitInput(_Input):
    student_id: str | None = Field(None, min_length=1, max_length=64, description="学生 ID，精确匹配。")
    student_name: str | None = Field(None, min_length=1, max_length=100, description="学生姓名，支持部分匹配。")
    student_number: str | None = Field(None, min_length=1, max_length=100, description="学号，精确匹配。")

    @model_validator(mode="after")
    def one_selector(self):
        if sum(value is not None for value in (self.student_id, self.student_name, self.student_number)) != 1:
            raise ValueError("请提供 student_id、student_name 或 student_number 中的一项。")
        return self

    def spec(self):
        field, value = next(iter(self.model_dump(exclude_none=True).items()))
        predicate = {"field": field, "operator": "contains" if field == "student_name" else "eq", "value": value}
        return PaperQuerySpec(operation="portrait", filters=[predicate], include=["portrait"])


_DEFINITIONS = {
    "summarize_papers": (_SummaryInput, "统计当前导师范围内的论文申报记录数和去重学生数，可按一个维度分组。"
                         "默认统计有效归档。追问时传入本轮全部筛选条件，包括先前年份和新增条件。"),
    "list_papers": (_ListInput, "分页列出论文申报记录或去重学生。列出「这些论文」时照传上一轮统计的筛选条件，"
                    "包括年份和学位。仅在教师选定某个分组时使用该组的 drilldown.arguments。"
                    "items 中的 student_id 可查画像，files 中的 download_url 指向原件。"),
    "get_student_portrait": (_PortraitInput, "用学生 ID、姓名或学号中的一项查询学生画像及已归档论文原件。"
                             "如匹配多人，展示 candidates 中的学号供教师区分，再用选中的 student_id 查询。"),
}
TOOLS = [{"name": name, "description": description, "inputSchema": model.model_json_schema()}
         for name, (model, description) in _DEFINITIONS.items()]


def _summary_row(row, filters):
    data = row.model_dump(exclude={"drilldown_patch"}, exclude_none=True)
    if data.get("subject") == "paper_record":
        data["subject"] = "paper"
    if "group_key" in data and "year" in data["group_key"]:
        data["group_key"]["grade"] = data["group_key"].pop("year")
    patch = row.drilldown_patch
    if patch is not None:
        arguments = {**filters, "subject": "student" if patch.distinct_subject == "student" else "paper"}
        for predicate in patch.set_filters:
            arguments["grade" if predicate.field == "year" else predicate.field] = predicate.value
        data["drilldown"] = {"tool": "list_papers", "arguments": arguments}
    return data


def _file(file, base_url):
    return file.model_dump() | {"download_url": base_url + file.download_url}


def _payload(result, params, base_url):
    summary = result.summary
    data = {"status": result.status, "summary": summary.headline, "data_as_of": summary.data_as_of,
            "basis": summary.basis}
    if isinstance(params, _SummaryInput):
        filters = params.model_dump(exclude={"group_by"}, exclude_none=True)
        data.update(metrics=[_summary_row(card, filters) for card in summary.metrics],
                    breakdown=[_summary_row(row, filters) for row in summary.breakdown])
    elif isinstance(params, _ListInput):
        sources = {source.source_id: source for source in result.sources}
        items = []
        for item in result.items:
            row = item.model_dump(exclude={"source_ids", "links", "year"}, exclude_none=True)
            row["grade"] = item.year
            files = {file.file_id: _file(file, base_url)
                     for source_id in item.source_ids for file in sources[source_id].files}
            items.append({**row, "files": list(files.values())})
        data.update(items=items, pagination=result.pagination.model_dump())
    else:
        portrait = result.portrait.model_dump(
            exclude={"portrait_url": True, "records": {"__all__": {"source_id", "field_pointers", "files"}}},
            exclude_none=True,
        )
        portrait["grade"] = portrait.pop("year")
        for row, record in zip(portrait["records"], result.portrait.records):
            row["files"] = [_file(file, base_url) for file in record.files]
        data.update(portrait=portrait,
                    summary=f"{portrait['student_name']}的画像中有 {portrait['counts']['paper_records']} 条论文记录。")
    return data


def call_tool(session: Session, user: User, name: str, arguments: dict, base_url: str) -> dict:
    """The caller owns the transaction and catches input/domain errors inside it."""
    request_id = uid()
    try:
        model, _ = _DEFINITIONS[name]
        params = model.model_validate(arguments)
        result = _record_run(session, user, params.spec(), _scope(session, user), run_id=request_id)
    except (ValidationError, TeacherAgentError):
        session.add(Audit(actor_id=user.id, action="teacher_agent.query.error", object_id=request_id))
        raise
    if result.clarification:
        session.add(Audit(actor_id=user.id, action="teacher_agent.query.clarification", object_id=request_id))
        matches = result.clarification.student_candidates
        roster = _roster(session, [entry.student_id for entry in matches], [])
        candidates = [
            entry.model_dump(exclude={"year"}) | {"grade": entry.year, "student_number": roster[entry.student_id]["student_number"]}
            for entry in matches if entry.student_id in roster
        ]
        return {"status": result.status, "summary": result.clarification.message, "candidates": candidates}
    return _payload(result, params, base_url)
