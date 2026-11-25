"""Teacher-agent query, planner, evidence, and conversation contracts."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Final, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from pydantic.json_schema import models_json_schema


CONTRACT_SCHEMA_VERSION: Final[Literal["teacher-agent-result-1"]] = "teacher-agent-result-1"
ISO_DATE_PATTERN: Final[str] = r"^\d{4}-\d{2}-\d{2}$"

DomainName = Literal["paper", "scholarship"]
QueryOperation = Literal["aggregate", "list", "portrait"]
QueryBasis = Literal["current_effective_archives", "submitted_latest"]

# Slice 1 paper enums (derived from existing main.py; `draft` & `period` are unrepresentable)
PublicationStatus = Literal["submitted", "accepted", "published"]
VisibleReviewStatus = Literal["pending_review", "returned", "approved", "archived"]
StudentDegree = Literal["博士", "硕士", "未标注"]
ReviewActorType = Literal["human", "agent", "simulation"]

PaperExplicitDateField = Literal["submission_date", "acceptance_date", "publication_date"]
PaperTimeField = Literal[
    "status_date",
    "submission_date",
    "acceptance_date",
    "publication_date",
    "archived_at",
]

# Single authoritative status -> date key map (immune to stale dates copied by POST /updates)
PAPER_STATUS_DATE_FIELD: Final[dict[PublicationStatus, PaperExplicitDateField]] = {
    "submitted": "submission_date",
    "accepted": "acceptance_date",
    "published": "publication_date",
}

PaperGroupByField = Literal["publication_status", "review_status", "degree", "major", "year", "stage"]
PaperDistinctSubject = Literal["paper_record", "student"]
PaperSortField = Literal["status_date", "archived_at", "student_name", "year"]
IncludeOption = Literal["metrics", "items", "students", "portrait", "sources"]

# Slice 2 scholarship enums (contract frozen upfront; DB tables arrive in Slice 2 after #29)
ScholarshipTimeField = Literal["submitted_at", "campaign_year", "reviewed_at"]
ScholarshipApplicationStatus = Literal["pending_review", "returned", "approved", "archived", "rejected"]
ScholarshipGroupByField = Literal["award_name", "award_level", "application_status", "degree", "major", "year"]
ScholarshipDistinctSubject = Literal["applicant", "application", "award_application"]
ScholarshipSortField = Literal["submitted_at", "student_name", "year"]

MetricUnit = Literal["条", "人", "份", "项"]
MetricSubject = Literal["paper_record", "student", "applicant", "application", "award_application"]
MetricKey = Literal[
    # Slice 1: Paper
    "paper_record_count",
    "paper_student_count",
    "paper_published_record_count",
    "paper_published_student_count",
    "paper_accepted_record_count",
    "paper_accepted_student_count",
    "paper_submitted_record_count",
    "paper_submitted_student_count",
    # Slice 2: Scholarship (5 frozen metrics)
    "applicant_count",
    "application_count",
    "award_application_count",
    "pending_review_count",
    "correction_required_count",
]


class _StrictModel(BaseModel):
    """Immutable strict contract model: forbids unknown keys and strips whitespace."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class MetricDefinition(_StrictModel):
    key: MetricKey
    domain: DomainName
    label: str
    unit: MetricUnit
    subject: MetricSubject
    definition: str


METRIC_CATALOG: Final[dict[MetricKey, MetricDefinition]] = {
    "paper_record_count": MetricDefinition(
        key="paper_record_count",
        domain="paper",
        label="论文申报记录数",
        unit="条",
        subject="paper_record",
        definition="当前授权范围与筛选条件下的论文申报记录总数（尚未完成成果主档去重）。",
    ),
    "paper_student_count": MetricDefinition(
        key="paper_student_count",
        domain="paper",
        label="涉及学生人数",
        unit="人",
        subject="student",
        definition="至少命中一条论文申报记录的去重学生人数。",
    ),
    "paper_published_record_count": MetricDefinition(
        key="paper_published_record_count",
        domain="paper",
        label="已发表论文记录数",
        unit="条",
        subject="paper_record",
        definition="publication_status 为 published 的论文申报记录数。",
    ),
    "paper_published_student_count": MetricDefinition(
        key="paper_published_student_count",
        domain="paper",
        label="已发表涉及学生数",
        unit="人",
        subject="student",
        definition="至少有一条已发表论文记录的去重学生人数。",
    ),
    "paper_accepted_record_count": MetricDefinition(
        key="paper_accepted_record_count",
        domain="paper",
        label="已录用论文记录数",
        unit="条",
        subject="paper_record",
        definition="publication_status 为 accepted 的论文申报记录数。",
    ),
    "paper_accepted_student_count": MetricDefinition(
        key="paper_accepted_student_count",
        domain="paper",
        label="已录用涉及学生数",
        unit="人",
        subject="student",
        definition="至少有一条已录用论文记录的去重学生人数。",
    ),
    "paper_submitted_record_count": MetricDefinition(
        key="paper_submitted_record_count",
        domain="paper",
        label="已投稿论文记录数",
        unit="条",
        subject="paper_record",
        definition="publication_status 为 submitted 的论文申报记录数。",
    ),
    "paper_submitted_student_count": MetricDefinition(
        key="paper_submitted_student_count",
        domain="paper",
        label="已投稿涉及学生数",
        unit="人",
        subject="student",
        definition="至少有一条已投稿论文记录的去重学生人数。",
    ),
    "applicant_count": MetricDefinition(
        key="applicant_count",
        domain="scholarship",
        label="申请学生人数",
        unit="人",
        subject="applicant",
        definition="去重后的奖学金申请学生人数。",
    ),
    "application_count": MetricDefinition(
        key="application_count",
        domain="scholarship",
        label="申请记录总份数",
        unit="份",
        subject="application",
        definition="奖学金申请记录总份数。",
    ),
    "award_application_count": MetricDefinition(
        key="award_application_count",
        domain="scholarship",
        label="学生-奖项申报关系数",
        unit="项",
        subject="award_application",
        definition="学生与奖项的多对多申报关系展开总数。",
    ),
    "pending_review_count": MetricDefinition(
        key="pending_review_count",
        domain="scholarship",
        label="待审核申请数",
        unit="份",
        subject="application",
        definition="当前状态为待审（pending_review）的申请记录数。",
    ),
    "correction_required_count": MetricDefinition(
        key="correction_required_count",
        domain="scholarship",
        label="待补正申请数",
        unit="份",
        subject="application",
        definition="当前状态为待补正（returned）的申请记录数。",
    ),
}


def _check_op_shape(operator: str, value: Any) -> None:
    if operator == "in":
        if not isinstance(value, list) or not (1 <= len(value) <= 50):
            raise ValueError("operator 'in' requires a non-empty list of up to 50 values")
    elif isinstance(value, list):
        raise ValueError(f"operator '{operator}' requires a scalar value")


def _normalize_year(raw: str) -> str:
    """Normalize '2023' -> '2023级' to match StudentProfile.year in seed_scenarios.py."""
    cleaned = raw.strip()
    if len(cleaned) == 4 and cleaned.isdigit():
        return f"{cleaned}级"
    return cleaned


# --- Discriminated Typed Filters (Zero Hand-Synced Allowlists) ---


class PublicationStatusFilter(_StrictModel):
    field: Literal["publication_status"] = "publication_status"
    operator: Literal["eq", "neq", "in"] = "eq"
    value: PublicationStatus | list[PublicationStatus]

    @model_validator(mode="after")
    def _shape(self) -> PublicationStatusFilter:
        _check_op_shape(self.operator, self.value)
        return self


class ReviewStatusFilter(_StrictModel):
    field: Literal["review_status"] = "review_status"
    operator: Literal["eq", "in"] = "eq"
    value: VisibleReviewStatus | list[VisibleReviewStatus]

    @model_validator(mode="after")
    def _shape(self) -> ReviewStatusFilter:
        _check_op_shape(self.operator, self.value)
        return self

    def requires_submitted_latest(self) -> bool:
        statuses = self.value if isinstance(self.value, list) else [self.value]
        return any(status in ("pending_review", "returned") for status in statuses)


class StudentIdFilter(_StrictModel):
    field: Literal["student_id"] = "student_id"
    operator: Literal["eq", "in"] = "eq"
    value: Annotated[str, Field(min_length=1, max_length=64)] | list[Annotated[str, Field(min_length=1, max_length=64)]]

    @model_validator(mode="after")
    def _shape(self) -> StudentIdFilter:
        _check_op_shape(self.operator, self.value)
        return self


class StudentNameFilter(_StrictModel):
    field: Literal["student_name"] = "student_name"
    operator: Literal["eq", "contains"] = "contains"
    value: str = Field(min_length=1, max_length=100)


class StudentNumberFilter(_StrictModel):
    field: Literal["student_number"] = "student_number"
    operator: Literal["eq", "contains"] = "eq"
    value: str = Field(min_length=1, max_length=100)


class YearFilter(_StrictModel):
    field: Literal["year"] = "year"
    operator: Literal["eq", "in"] = "eq"
    value: Annotated[str, Field(min_length=1, max_length=30)] | list[Annotated[str, Field(min_length=1, max_length=30)]]

    @field_validator("value", mode="after")
    @classmethod
    def _norm(cls, v: str | list[str]) -> str | list[str]:
        return [_normalize_year(x) for x in v] if isinstance(v, list) else _normalize_year(v)

    @model_validator(mode="after")
    def _shape(self) -> YearFilter:
        _check_op_shape(self.operator, self.value)
        return self


class DegreeFilter(_StrictModel):
    field: Literal["degree"] = "degree"
    operator: Literal["eq", "in"] = "eq"
    value: StudentDegree | list[StudentDegree]

    @model_validator(mode="after")
    def _shape(self) -> DegreeFilter:
        _check_op_shape(self.operator, self.value)
        return self


class MajorFilter(_StrictModel):
    field: Literal["major"] = "major"
    operator: Literal["eq", "in", "contains"] = "eq"
    value: Annotated[str, Field(min_length=1, max_length=100)] | list[Annotated[str, Field(min_length=1, max_length=100)]]

    @model_validator(mode="after")
    def _shape(self) -> MajorFilter:
        _check_op_shape(self.operator, self.value)
        return self


class DirectionFilter(_StrictModel):
    field: Literal["direction"] = "direction"
    operator: Literal["eq", "contains"] = "contains"
    value: str = Field(min_length=1, max_length=200)


class StageFilter(_StrictModel):
    field: Literal["stage"] = "stage"
    operator: Literal["eq", "in"] = "eq"
    value: Annotated[str, Field(min_length=1, max_length=60)] | list[Annotated[str, Field(min_length=1, max_length=60)]]

    @model_validator(mode="after")
    def _shape(self) -> StageFilter:
        _check_op_shape(self.operator, self.value)
        return self


class JournalFilter(_StrictModel):
    field: Literal["journal"] = "journal"
    operator: Literal["eq", "contains"] = "contains"
    value: str = Field(min_length=1, max_length=200)


class TitleFilter(_StrictModel):
    field: Literal["title"] = "title"
    operator: Literal["contains"] = "contains"
    value: str = Field(min_length=1, max_length=200)


class HasDoiFilter(_StrictModel):
    field: Literal["has_doi"] = "has_doi"
    operator: Literal["eq"] = "eq"
    value: bool


class SimulationFilter(_StrictModel):
    field: Literal["simulation"] = "simulation"
    operator: Literal["eq"] = "eq"
    value: bool


PaperFilter = Annotated[
    Union[
        PublicationStatusFilter,
        ReviewStatusFilter,
        StudentIdFilter,
        StudentNameFilter,
        StudentNumberFilter,
        YearFilter,
        DegreeFilter,
        MajorFilter,
        DirectionFilter,
        StageFilter,
        JournalFilter,
        TitleFilter,
        HasDoiFilter,
        SimulationFilter,
    ],
    Field(discriminator="field"),
]


# Slice 2 scholarship filters (reserved without premature DB tables)
class CampaignYearFilter(_StrictModel):
    field: Literal["campaign_year"] = "campaign_year"
    operator: Literal["eq", "in"] = "eq"
    value: Annotated[str, Field(min_length=4, max_length=30)] | list[Annotated[str, Field(min_length=4, max_length=30)]]

    @model_validator(mode="after")
    def _shape(self) -> CampaignYearFilter:
        _check_op_shape(self.operator, self.value)
        return self


class AwardNameFilter(_StrictModel):
    field: Literal["award_name"] = "award_name"
    operator: Literal["eq", "in", "contains"] = "eq"
    value: Annotated[str, Field(min_length=1, max_length=120)] | list[Annotated[str, Field(min_length=1, max_length=120)]]

    @model_validator(mode="after")
    def _shape(self) -> AwardNameFilter:
        _check_op_shape(self.operator, self.value)
        return self


class AwardLevelFilter(_StrictModel):
    field: Literal["award_level"] = "award_level"
    operator: Literal["eq", "in"] = "eq"
    value: Annotated[str, Field(min_length=1, max_length=60)] | list[Annotated[str, Field(min_length=1, max_length=60)]]

    @model_validator(mode="after")
    def _shape(self) -> AwardLevelFilter:
        _check_op_shape(self.operator, self.value)
        return self


class ApplicationStatusFilter(_StrictModel):
    field: Literal["application_status"] = "application_status"
    operator: Literal["eq", "in"] = "eq"
    value: ScholarshipApplicationStatus | list[ScholarshipApplicationStatus]

    @model_validator(mode="after")
    def _shape(self) -> ApplicationStatusFilter:
        _check_op_shape(self.operator, self.value)
        return self


ScholarshipFilter = Annotated[
    Union[
        CampaignYearFilter,
        AwardNameFilter,
        AwardLevelFilter,
        ApplicationStatusFilter,
        StudentIdFilter,
        StudentNameFilter,
        StudentNumberFilter,
        YearFilter,
        DegreeFilter,
        MajorFilter,
    ],
    Field(discriminator="field"),
]

QueryFilter = Annotated[
    Union[
        PublicationStatusFilter,
        ReviewStatusFilter,
        StudentIdFilter,
        StudentNameFilter,
        StudentNumberFilter,
        YearFilter,
        DegreeFilter,
        MajorFilter,
        DirectionFilter,
        StageFilter,
        JournalFilter,
        TitleFilter,
        HasDoiFilter,
        SimulationFilter,
        CampaignYearFilter,
        AwardNameFilter,
        AwardLevelFilter,
        ApplicationStatusFilter,
    ],
    Field(discriminator="field"),
]


def _extract_filter_fields(annotated_union: Any) -> frozenset[str]:
    union_type = get_args(annotated_union)[0]
    fields: set[str] = set()
    for model in get_args(union_type):
        lit_args = get_args(model.model_fields["field"].annotation)
        name = lit_args[0] if lit_args else model.model_fields["field"].default
        assert isinstance(name, str) and name
        fields.add(name)
    return frozenset(fields)


# Derived once from union types — zero hand-synced allowlists!
PAPER_FILTER_FIELDS: Final[frozenset[str]] = _extract_filter_fields(PaperFilter)
SCHOLARSHIP_FILTER_FIELDS: Final[frozenset[str]] = _extract_filter_fields(ScholarshipFilter)
ALL_FILTER_FIELDS: Final[frozenset[str]] = _extract_filter_fields(QueryFilter)


# --- Time Range, Sort & QuerySpec ---


class _DateRangeBase(_StrictModel):
    date_from: str = Field(alias="from", pattern=ISO_DATE_PATTERN)
    date_to: str = Field(alias="to", pattern=ISO_DATE_PATTERN)

    @model_validator(mode="after")
    def _chronological(self) -> _DateRangeBase:
        if date.fromisoformat(self.date_from) > date.fromisoformat(self.date_to):
            raise ValueError("'from' date must be <= 'to' date")
        return self


class PaperTimeRange(_DateRangeBase):
    field: PaperTimeField = "status_date"


class ScholarshipTimeRange(_DateRangeBase):
    field: ScholarshipTimeField = "submitted_at"


class PaperSort(_StrictModel):
    field: PaperSortField = "status_date"
    direction: Literal["asc", "desc"] = "desc"


class ScholarshipSort(_StrictModel):
    field: ScholarshipSortField = "submitted_at"
    direction: Literal["asc", "desc"] = "desc"


class PaperQuerySpec(_StrictModel):
    domain: Literal["paper"] = "paper"
    operation: QueryOperation = "aggregate"
    basis: QueryBasis = "current_effective_archives"
    time_range: PaperTimeRange | None = None
    filters: list[PaperFilter] = Field(default_factory=list, max_length=16)
    group_by: list[PaperGroupByField] = Field(default_factory=list, max_length=2)
    distinct_subject: PaperDistinctSubject = "paper_record"
    include: list[IncludeOption] = Field(default_factory=lambda: ["metrics", "items", "sources"], max_length=5)
    sort: PaperSort = Field(default_factory=PaperSort)
    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def _invariants(self) -> PaperQuerySpec:
        seen: set[str] = set()
        has_student_selector = False
        for flt in self.filters:
            if flt.field in seen:
                raise ValueError(f"duplicate filter field '{flt.field}'; use operator 'in'")
            seen.add(flt.field)
            if flt.field in ("student_id", "student_name", "student_number"):
                has_student_selector = True
            if isinstance(flt, ReviewStatusFilter) and flt.requires_submitted_latest() and self.basis == "current_effective_archives":
                raise ValueError("filtering pending_review/returned requires basis='submitted_latest'")
        if self.time_range and self.time_range.field == "archived_at" and self.basis != "current_effective_archives":
            raise ValueError("time_range.field='archived_at' requires basis='current_effective_archives'")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by must not contain duplicates")
        if len(set(self.include)) != len(self.include):
            raise ValueError("include must not contain duplicates")
        if self.operation == "portrait":
            if not has_student_selector:
                raise ValueError("operation='portrait' requires a student_id, student_name, or student_number filter")
            if self.group_by:
                raise ValueError("operation='portrait' does not support group_by")
        return self


class ScholarshipQuerySpec(_StrictModel):
    domain: Literal["scholarship"] = "scholarship"
    operation: QueryOperation = "aggregate"
    basis: QueryBasis = "submitted_latest"
    time_range: ScholarshipTimeRange | None = None
    filters: list[ScholarshipFilter] = Field(default_factory=list, max_length=16)
    group_by: list[ScholarshipGroupByField] = Field(default_factory=list, max_length=2)
    distinct_subject: ScholarshipDistinctSubject = "application"
    include: list[IncludeOption] = Field(default_factory=lambda: ["metrics", "items", "sources"], max_length=5)
    sort: ScholarshipSort = Field(default_factory=ScholarshipSort)
    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=50, ge=1, le=100)


QuerySpec = Annotated[Union[PaperQuerySpec, ScholarshipQuerySpec], Field(discriminator="domain")]
QuerySpecAdapter: Final[TypeAdapter[QuerySpec]] = TypeAdapter(QuerySpec)


def validate_query_spec(raw: Any) -> QuerySpec:
    return QuerySpecAdapter.validate_python(raw)


# --- Unified QueryPatch Algebra & PlannerOutput ---


class QueryPatch(_StrictModel):
    """Single algebraic delta shared by UI metric cards / filter chips AND NL follow-ups."""

    operation: QueryOperation | None = None
    basis: QueryBasis | None = None
    time_range: PaperTimeRange | ScholarshipTimeRange | None = None
    clear_time_range: bool = False
    set_filters: list[QueryFilter] = Field(default_factory=list, max_length=16)
    remove_filter_fields: list[str] = Field(default_factory=list, max_length=16)
    group_by: list[PaperGroupByField | ScholarshipGroupByField] | None = None
    distinct_subject: PaperDistinctSubject | ScholarshipDistinctSubject | None = None
    include: list[IncludeOption] | None = None
    sort: PaperSort | ScholarshipSort | None = None
    page: int | None = Field(default=None, ge=1, le=500)
    page_size: int | None = Field(default=None, ge=1, le=100)
    reset_page: bool = True

    @field_validator("remove_filter_fields", mode="after")
    @classmethod
    def _validate_remove_fields(cls, fields: list[str]) -> list[str]:
        unknown = [f for f in fields if f not in ALL_FILTER_FIELDS]
        if unknown:
            raise ValueError(f"unknown filter fields in remove_filter_fields: {unknown}")
        return list(dict.fromkeys(fields))


def export_paper_tool_input_schema() -> dict[str, Any]:
    models = {"spec": PaperQuerySpec, "patch": QueryPatch}
    refs, definitions = models_json_schema([(model, "validation") for model in models.values()], by_alias=True)
    return {
        "type": "object",
        "properties": {name: refs[(model, "validation")] for name, model in models.items()},
        "additionalProperties": False,
        "minProperties": 1,
        "maxProperties": 1,
        **definitions,
    }


class ReplaceSpecAction(_StrictModel):
    action: Literal["replace"] = "replace"
    spec: QuerySpec


class PatchSpecAction(_StrictModel):
    action: Literal["patch"] = "patch"
    patch: QueryPatch


class ClarifyAction(_StrictModel):
    action: Literal["clarify"] = "clarify"
    message: str = Field(min_length=1, max_length=1000)
    suggestions: list[str] = Field(default_factory=list, max_length=5)


class UnsupportedAction(_StrictModel):
    action: Literal["unsupported"] = "unsupported"
    requested_domain: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=1000)


PlannerOutput = Annotated[
    Union[ReplaceSpecAction, PatchSpecAction, ClarifyAction, UnsupportedAction],
    Field(discriminator="action"),
]
PlannerOutputAdapter: Final[TypeAdapter[PlannerOutput]] = TypeAdapter(PlannerOutput)


def apply_patch(previous: QuerySpec, patch: QueryPatch) -> QuerySpec:
    """Remove filters, upsert replacements, and validate the merged query in its original domain."""
    allowed = PAPER_FILTER_FIELDS if previous.domain == "paper" else SCHOLARSHIP_FILTER_FIELDS
    for field in patch.remove_filter_fields:
        if field not in allowed:
            raise ValueError(f"cannot remove filter '{field}' from a {previous.domain} query")

    original_filters = {predicate.field: predicate for predicate in previous.filters}
    filters = original_filters.copy()
    for field in patch.remove_filter_fields:
        filters.pop(field, None)
    for predicate in patch.set_filters:
        filters[predicate.field] = predicate

    data = previous.model_dump()
    changes = patch.model_dump(
        include={"operation", "basis", "time_range", "group_by", "distinct_subject", "include", "sort"},
        exclude_none=True,
        exclude_unset=True,
    )
    if patch.clear_time_range:
        changes["time_range"] = None
    review_status = filters.get("review_status")
    if (
        patch.basis is None
        and isinstance(review_status, ReviewStatusFilter)
        and review_status in patch.set_filters
        and review_status.requires_submitted_latest()
    ):
        changes["basis"] = "submitted_latest"

    data.update(changes)
    data["filters"] = [predicate.model_dump() for predicate in filters.values()]
    if patch.page_size is not None:
        data["page_size"] = patch.page_size
    if patch.page is not None:
        data["page"] = patch.page
    result = validate_query_spec(data)
    if patch.page is None and patch.reset_page and previous.page != 1:
        if filters != original_filters or any(getattr(result, field) != getattr(previous, field) for field in changes):
            return result.model_copy(update={"page": 1})
    return result


# --- ResultEnvelope & Evidence Provenance ---


class EvidenceFile(_StrictModel):
    """Public downloadable attachment metadata exposed to authorized teachers."""

    file_id: str
    name: str
    media_type: str
    size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    download_url: str = Field(pattern=r"^/api/v1/files/[A-Za-z0-9-]+/download$")


class EvidenceLinks(_StrictModel):
    portrait_url: str = Field(pattern=r"^/api/v1/students/[A-Za-z0-9-]+/portrait$")
    submission_url: str | None = Field(default=None, pattern=r"^/api/v1/submissions/[A-Za-z0-9-]+$")


class FieldPointer(_StrictModel):
    """JSON Pointer trace matching `portraits.py` `/form/<field>` provenance."""

    field: str
    pointer: str = Field(pattern=r"^/form/[A-Za-z0-9_/-]+$")
    value: str
    verification: Literal[
        "human_approved_submission",
        "agent_approved_submission",
        "simulated_approved_submission",
        "submitted_unarchived_version",
    ]


class EvidenceSource(_StrictModel):
    source_id: str
    kind: Literal["paper", "annual", "scholarship"]
    student_id: str
    submission_id: str
    version_id: str
    version_number: int = Field(ge=1)
    archive_id: str | None = None
    snapshot_id: str | None = None
    decision_id: str | None = None
    review_actor_type: ReviewActorType | None = None
    ai_job_id: str | None = None
    archived_at: str | None = None
    simulation: bool = False
    field_pointers: list[FieldPointer] = Field(default_factory=list)
    files: list[EvidenceFile] = Field(default_factory=list)
    submission_url: str = Field(pattern=r"^/api/v1/submissions/[A-Za-z0-9-]+$")
    portrait_url: str = Field(pattern=r"^/api/v1/students/[A-Za-z0-9-]+/portrait$")


class MetricCard(_StrictModel):
    """KPI card with ONE canonical drill-down action (`drilldown_patch`)."""

    key: MetricKey
    label: str
    value: int = Field(ge=0)
    unit: MetricUnit
    subject: MetricSubject
    group_key: dict[str, str] | None = None
    drilldown_patch: QueryPatch | None = None


class BreakdownRow(_StrictModel):
    group_key: dict[str, str]
    label: str
    record_count: int = Field(ge=0)
    student_count: int = Field(ge=0)
    drilldown_patch: QueryPatch | None = None


class ResultSummary(_StrictModel):
    headline: str
    metrics: list[MetricCard] = Field(default_factory=list)
    breakdown: list[BreakdownRow] = Field(default_factory=list)
    data_as_of: str
    basis: QueryBasis
    scope_student_count: int = Field(ge=0)
    scope_recomputed: bool = False
    notice: str


class PaperAuthor(_StrictModel):
    name: str
    order: int = Field(ge=1)
    is_self: bool = False


class PaperRecordItem(_StrictModel):
    item_kind: Literal["paper_record"] = "paper_record"
    submission_id: str
    version_id: str
    version_number: int = Field(ge=1)
    archive_id: str | None = None
    student_id: str
    student_name: str
    student_number: str
    year: str
    degree: StudentDegree
    major: str
    direction: str
    stage: str
    title: str
    publication_status: PublicationStatus
    status_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    submission_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    acceptance_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    publication_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    journal: str = ""
    doi: str = ""
    article_url: str = ""
    authors: list[PaperAuthor] = Field(default_factory=list)
    author_order: int | None = Field(default=None, ge=1)
    author_identity: str = ""
    external_article_key: str = ""
    contribution: str = ""
    review_status: VisibleReviewStatus
    review_actor_type: ReviewActorType | None = None
    archived_at: str | None = None
    simulation: bool = False
    source_ids: list[str] = Field(min_length=1)
    links: EvidenceLinks


class StudentSummaryItem(_StrictModel):
    item_kind: Literal["student_summary"] = "student_summary"
    student_id: str
    student_name: str
    student_number: str
    year: str
    degree: StudentDegree
    major: str
    direction: str
    stage: str
    matched_record_count: int = Field(ge=1)
    status_counts: dict[str, int] = Field(default_factory=dict)
    latest_status_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    source_ids: list[str] = Field(min_length=1)
    links: EvidenceLinks


class ScholarshipRecordItem(_StrictModel):
    item_kind: Literal["scholarship_record"] = "scholarship_record"
    application_id: str
    campaign_year: str
    award_names: list[str] = Field(default_factory=list)
    student_id: str
    student_name: str
    student_number: str
    degree: StudentDegree
    major: str
    application_status: ScholarshipApplicationStatus
    submitted_at: str
    source_ids: list[str] = Field(default_factory=list)
    links: EvidenceLinks


ResultItem = Annotated[
    Union[PaperRecordItem, StudentSummaryItem, ScholarshipRecordItem],
    Field(discriminator="item_kind"),
]


class PortraitPaperRecord(_StrictModel):
    """Hydrates `journal` and `doi` from `Version.snapshot['form']` alongside verified facts."""

    source_id: str
    archive_id: str
    snapshot_id: str | None = None
    submission_id: str
    version_id: str
    version_number: int = Field(ge=1)
    decision_id: str
    review_actor_type: ReviewActorType
    archived_at: str
    title: str
    publication_status: PublicationStatus
    status_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    journal: str = ""
    doi: str = ""
    article_url: str = ""
    authors: list[PaperAuthor] = Field(default_factory=list)
    author_order: int | None = Field(default=None, ge=1)
    author_identity: str = ""
    external_article_key: str = ""
    contribution: str = ""
    simulation: bool = False
    field_pointers: list[FieldPointer] = Field(default_factory=list)
    files: list[EvidenceFile] = Field(default_factory=list)


class PortraitCounts(_StrictModel):
    paper_records: int = Field(ge=0)
    annual_records: int = Field(ge=0)


class TeacherRef(_StrictModel):
    id: str
    name: str


class StudentPortraitPanel(_StrictModel):
    student_id: str
    student_name: str
    student_number: str
    year: str
    degree: StudentDegree
    major: str
    direction: str
    stage: str
    teachers: list[TeacherRef] = Field(default_factory=list)
    basis: Literal["current_effective_archives"] = "current_effective_archives"
    counts: PortraitCounts
    pending_snapshot_count: int = Field(default=0, ge=0)
    ability_assessment: Literal["待评价"] = "待评价"
    inferences: list[str] = Field(default_factory=list, max_length=0)
    records: list[PortraitPaperRecord] = Field(default_factory=list)
    portrait_url: str = Field(pattern=r"^/api/v1/students/[A-Za-z0-9-]+/portrait$")
    notice: str


class Pagination(_StrictModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    has_more: bool


class DisambiguationCandidate(_StrictModel):
    student_id: str
    student_name: str
    year: str
    degree: StudentDegree
    major: str


class ClarificationPrompt(_StrictModel):
    message: str
    suggestions: list[str] = Field(default_factory=list)
    student_candidates: list[DisambiguationCandidate] = Field(default_factory=list)


class ResultEnvelope(_StrictModel):
    schema_version: Literal["teacher-agent-result-1"] = CONTRACT_SCHEMA_VERSION
    conversation_id: str | None = None
    turn_id: str | None = None
    query_run_id: str | None = None
    status: Literal["ok", "clarification_needed", "unsupported_domain"] = "ok"
    applied_query: QuerySpec | None = None
    summary: ResultSummary | None = None
    items: list[ResultItem] = Field(default_factory=list)
    portrait: StudentPortraitPanel | None = None
    pagination: Pagination | None = None
    sources: list[EvidenceSource] = Field(default_factory=list)
    clarification: ClarificationPrompt | None = None

    @model_validator(mode="after")
    def _enforce_invariants(self) -> ResultEnvelope:
        if self.status == "ok":
            if self.applied_query is None or self.summary is None or self.pagination is None or self.query_run_id is None:
                raise ValueError("status='ok' requires query_run_id, applied_query, summary, and pagination")
            src_ids = {s.source_id for s in self.sources}
            for item in self.items:
                missing = [sid for sid in item.source_ids if sid not in src_ids]
                if missing:
                    raise ValueError(f"item references unknown source_ids: {missing}")
            if self.portrait is not None:
                for rec in self.portrait.records:
                    if rec.source_id not in src_ids:
                        raise ValueError(f"portrait record references unknown source_id: {rec.source_id}")
        else:
            if self.clarification is None:
                raise ValueError(f"status='{self.status}' requires clarification payload")
        return self


# --- Turn & Conversation I/O Models ---


class NaturalLanguageTurnInput(_StrictModel):
    mode: Literal["natural_language"] = "natural_language"
    message: str = Field(min_length=1, max_length=2000)


class DrilldownPatchTurnInput(_StrictModel):
    mode: Literal["drilldown_patch"] = "drilldown_patch"
    parent_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    patch: QueryPatch
    label: str = Field(default="", max_length=200)


class StructuredSpecTurnInput(_StrictModel):
    mode: Literal["structured_spec"] = "structured_spec"
    spec: QuerySpec
    label: str = Field(default="", max_length=200)


TurnInput = Annotated[
    Union[NaturalLanguageTurnInput, DrilldownPatchTurnInput, StructuredSpecTurnInput],
    Field(discriminator="mode"),
]


class CreateConversationRequest(_StrictModel):
    domain: DomainName = "paper"
    title: str | None = Field(default=None, min_length=1, max_length=200)


class TurnRequest(_StrictModel):
    expected_lock_version: int | None = Field(default=None, ge=0)
    input: TurnInput


class ConversationSummary(_StrictModel):
    id: str
    title: str
    active_domain: DomainName
    status: Literal["active", "archived"]
    turn_count: int = Field(ge=0)
    lock_version: int = Field(ge=0)
    created_at: str
    updated_at: str


class TurnTimelineItem(_StrictModel):
    id: str
    turn_index: int = Field(ge=1)
    input_mode: Literal["natural_language", "drilldown_patch", "structured_spec"]
    user_message: str
    resolved_query: QuerySpec | None = None
    status: Literal["succeeded", "clarification_needed", "unsupported_domain", "failed"]
    run_id: str | None = None
    access_revoked: bool = False
    run_ids: list[str] = Field(default_factory=lambda data: (
        [data["run_id"]] if data["run_id"] and not data["access_revoked"] else []
    ))
    clarification: ClarificationPrompt | None = None
    error_code: str | None = None
    created_at: str


class ConversationDetail(_StrictModel):
    conversation: ConversationSummary
    active_query: QuerySpec | None = None
    turns: list[TurnTimelineItem] = Field(default_factory=list)
    latest_result: ResultEnvelope | None = None
    latest_results: list[ResultEnvelope] = Field(default_factory=lambda data: (
        [data["latest_result"]] if data["latest_result"] and data["latest_result"].query_run_id else []
    ))


class VisualArtifact(_StrictModel):
    kind: Literal["html_sandbox"] = "html_sandbox"
    title: str = Field(default="", max_length=80)
    html: str = Field(min_length=1, max_length=16384)
    source_run_ids: list[str] = Field(min_length=1)


class TurnResponse(_StrictModel):
    conversation_id: str
    conversation_lock_version: int = Field(ge=0)
    turn: TurnTimelineItem
    result: ResultEnvelope
    analysis: str | None = Field(default=None, description="Generated summary for the initial response only.")
    analysis_notice: str | None = Field(
        default=None, description="Initial-response notice when the analysis cannot be verified but the result cards are valid."
    )
    visual: VisualArtifact | None = Field(
        default=None, description="Initial-response sandboxed HTML visualization grounded in results."
    )
    results: list[ResultEnvelope] = Field(default_factory=lambda data: (
        [data["result"]] if data["result"].query_run_id else []
    ))


def export_schemas() -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "query_spec_schema": QuerySpecAdapter.json_schema(by_alias=True),
        "result_envelope_schema": ResultEnvelope.model_json_schema(by_alias=True),
        "turn_request_schema": TurnRequest.model_json_schema(by_alias=True),
        "turn_response_schema": TurnResponse.model_json_schema(by_alias=True),
        "conversation_detail_schema": ConversationDetail.model_json_schema(by_alias=True),
        "planner_output_schema": PlannerOutputAdapter.json_schema(by_alias=True),
        "metric_catalog": {k: v.model_dump(mode="json") for k, v in METRIC_CATALOG.items()},
    }
