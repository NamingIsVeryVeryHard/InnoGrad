"""Teacher paper queries over submitted versions and effective archives."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from operator import attrgetter
from typing import get_args

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased, load_only

from ..db import AIJob, Archive, Decision, File, PortraitSnapshot, StudentProfile, Submission
from ..db import Supervision, User, Version, now
from ..policy import can_read, relation
from ..portraits import FIELDS
from ..workspace import scope_ids
from .contract import (
    METRIC_CATALOG, PAPER_STATUS_DATE_FIELD, BreakdownRow, ClarificationPrompt,
    DisambiguationCandidate, EvidenceFile, EvidenceLinks, EvidenceSource, FieldPointer,
    MetricCard, Pagination, PaperQuerySpec, PaperRecordItem, PortraitCounts,
    PortraitPaperRecord, QueryPatch, ResultEnvelope, ResultSummary, StudentPortraitPanel,
    StudentSummaryItem, TeacherRef, VisibleReviewStatus,
)
from .errors import ForbiddenRoleError, ResourceNotFoundError


_STUDENT_COLUMNS = {
    "student_id": User.id,
    "student_name": User.name,
    "student_number": func.coalesce(StudentProfile.number, User.username),
    "year": func.coalesce(StudentProfile.year, "待补录"),
    "degree": func.coalesce(StudentProfile.degree, "未标注"),
    "major": func.coalesce(StudentProfile.major, "待补录"),
    "direction": func.coalesce(StudentProfile.direction, "待补录"),
    "stage": func.coalesce(StudentProfile.stage, "待补录"),
}
_STUDENT_SELECTORS = {"student_id", "student_name", "student_number"}
_NOTICE = "按论文申报记录计数，涉及学生按学生身份去重；同一成果可能有多条申报记录。"


def _sql_filter(column, predicate):
    if predicate.operator == "in":
        return column.in_(predicate.value)
    if predicate.operator == "contains":
        return column.contains(predicate.value, autoescape=True)
    return column == predicate.value


def _roster(session, ids, filters):
    query = (select(*(column.label(field) for field, column in _STUDENT_COLUMNS.items()))
             .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
             .where(User.role == "student", User.id.in_(ids))
             .order_by(User.name, User.id))
    for predicate in filters:
        if predicate.field in _STUDENT_COLUMNS:
            query = query.where(_sql_filter(_STUDENT_COLUMNS[predicate.field], predicate))
    return {row["student_id"]: row for row in session.execute(query).mappings()}


def _versions(session, user, student_ids, basis, kinds, review_filter=None):
    """Read owned pointer chains. Neither drafts nor referenced submissions are projected."""
    archived = basis == "current_effective_archives"
    query = (select(
        Submission, Version.id.label("version_id"), Version.number, Version.snapshot["form"].label("form"),
        Version.snapshot["file_ids"].label("file_ids"), Version.snapshot["simulation"].as_boolean().label("simulation"),
        Archive.id.label("archive_id"), Archive.created_at.label("archived_at"),
        Decision.id.label("decision_id"), Decision.actor_type, AIJob.id.label("ai_job_id"),
        PortraitSnapshot.id.label("snapshot_id"),
    ).select_from(Submission).options(load_only(Submission.student_id, Submission.kind, Submission.status,
                                               Submission.current_version_id))
      .where(Submission.student_id.in_(student_ids), Submission.kind.in_(kinds),
             Submission.status.in_(get_args(VisibleReviewStatus))))
    if archived:
        current = aliased(Version)
        query = (query.join(current, and_(current.id == Submission.current_version_id,
                                          current.submission_id == Submission.id))
                 .join(Archive, Archive.id == Submission.effective_archive_id)
                 .join(Version, and_(Version.id == Archive.version_id, Version.submission_id == Submission.id))
                 .join(Decision, and_(Decision.id == Archive.decision_id, Decision.version_id == Version.id,
                                      Decision.outcome == "approved")))
    else:
        query = (query.join(Version, and_(Version.id == Submission.current_version_id,
                                          Version.submission_id == Submission.id))
                 .outerjoin(Decision, Decision.version_id == Version.id)
                 .outerjoin(Archive, and_(Archive.id == Submission.effective_archive_id,
                                          Archive.version_id == Version.id, Archive.decision_id == Decision.id,
                                          Decision.outcome == "approved"))
                 .where((Submission.status != "archived") | Archive.id.is_not(None)))
    if review_filter is not None:
        if archived and not _matches("archived", review_filter):
            return
        if not archived:
            query = query.where(_sql_filter(Submission.status, review_filter))
    query = (query.outerjoin(AIJob, and_(AIJob.id == Decision.ai_job_id, AIJob.version_id == Version.id,
                                         AIJob.submission_id == Submission.id))
             .outerjoin(PortraitSnapshot, and_(
                 PortraitSnapshot.archive_id == Archive.id,
                 PortraitSnapshot.payload["submission_id"].as_string() == Submission.id,
                 PortraitSnapshot.payload["version_id"].as_string() == Version.id,
                 PortraitSnapshot.payload["decision_id"].as_string() == Decision.id,
             )).order_by(Submission.student_id, Submission.id))
    # Each row already joins a valid current version. The remaining can_read check is per student.
    for _, rows in groupby(session.execute(query), key=lambda row: row.Submission.student_id):
        first = next(rows)
        if can_read(session, user, first.Submission):
            yield first
            yield from rows


def _form_date(value):
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return None


@dataclass
class _Paper:
    item: PaperRecordItem
    form: dict
    file_ids: tuple
    snapshot_id: str | None
    decision_id: str | None
    ai_job_id: str | None


def _paper(row, student, basis):
    form = row.form or {}
    status = form.get("publication_status")
    if status not in PAPER_STATUS_DATE_FIELD:
        return None
    dates = {field: _form_date(form.get(field)) for field in PAPER_STATUS_DATE_FIELD.values()}
    text = {field: form[field] if isinstance(form.get(field), str) else ""
            for field in ("title", "journal", "doi", "contribution")}
    sub = row.Submission
    item = PaperRecordItem(
        **student, **text, **dates, publication_status=status, status_date=dates[PAPER_STATUS_DATE_FIELD[status]],
        submission_id=sub.id, version_id=row.version_id, version_number=row.number, archive_id=row.archive_id,
        review_status="archived" if basis == "current_effective_archives" else sub.status,
        review_actor_type=row.actor_type, archived_at=row.archived_at, simulation=bool(row.simulation),
        source_ids=[row.version_id], links=EvidenceLinks(portrait_url=f"/api/v1/students/{sub.student_id}/portrait",
                                                        submission_url=f"/api/v1/submissions/{sub.id}"),
    )
    return _Paper(item, form, tuple(dict.fromkeys(row.file_ids or ())), row.snapshot_id, row.decision_id, row.ai_job_id)


def _matches(value, predicate):
    if predicate.operator == "in":
        return value in predicate.value
    if predicate.operator == "neq":
        return value != predicate.value
    if predicate.operator == "contains":
        return predicate.value.casefold() in value.casefold()
    return value == predicate.value


def _papers(session, user, roster, spec):
    review = next((predicate for predicate in spec.filters if predicate.field == "review_status"), None)
    predicates = [predicate for predicate in spec.filters
                  if predicate.field not in _STUDENT_COLUMNS and predicate.field != "review_status"]
    papers = []
    for row in _versions(session, user, roster, spec.basis, ["paper"], review):
        paper = _paper(row, roster[row.Submission.student_id], spec.basis)
        if paper is None:
            continue
        item = paper.item
        if spec.time_range:
            value = getattr(item, spec.time_range.field)
            if not value or not spec.time_range.date_from <= value[:10] <= spec.time_range.date_to:
                continue
        if all(_matches(bool(item.doi) if predicate.field == "has_doi" else getattr(item, predicate.field),
                        predicate) for predicate in predicates):
            papers.append(paper)
    return papers


def _drilldown(subject, filters):
    return QueryPatch(operation="list", group_by=[], page=1, distinct_subject=subject,
                      include=["metrics", "items", "sources"],
                      set_filters=[{"field": field, "operator": "eq", "value": value}
                                   for field, value in filters.items()])


def _summary(papers, spec, data_as_of, scope_size, recomputed):
    students = {paper.item.student_id for paper in papers}
    metrics = []
    if "metrics" in spec.include:
        by_status = defaultdict(list)
        for paper in papers:
            by_status[paper.item.publication_status].append(paper)
        for status in (None, *PAPER_STATUS_DATE_FIELD):
            records = by_status[status] if status else papers
            student_count = len({record.item.student_id for record in records})
            prefix = f"paper_{status}_" if status else "paper_"
            filters = {"publication_status": status} if status else {}
            for key, count in ((prefix + "record_count", len(records)), (prefix + "student_count", student_count)):
                definition = METRIC_CATALOG[key]
                metrics.append(MetricCard(key=key, label=definition.label, unit=definition.unit, value=count,
                                          subject=definition.subject,
                                          drilldown_patch=_drilldown(definition.subject, filters) if count else None))
    groups = defaultdict(list)
    if spec.group_by:
        for paper in papers:
            groups[tuple(getattr(paper.item, field) for field in spec.group_by)].append(paper)
    breakdown = []
    for values, records in sorted(groups.items()):
        key = dict(zip(spec.group_by, values))
        breakdown.append(BreakdownRow(group_key=key, label=" / ".join(values), record_count=len(records),
                                      student_count=len({record.item.student_id for record in records}),
                                      drilldown_patch=_drilldown(spec.distinct_subject, key)))
    basis_label = "当前有效归档" if spec.basis == "current_effective_archives" else "最新提交版本"
    return ResultSummary(
        headline=f"{basis_label}中有 {len(papers)} 条符合条件的论文申报记录，涉及 {len(students)} 名学生。",
        metrics=metrics, breakdown=breakdown, data_as_of=data_as_of, basis=spec.basis,
        scope_student_count=scope_size, scope_recomputed=recomputed, notice=_NOTICE,
    )


def _page(papers, spec, roster):
    students = spec.distinct_subject == "student" or "students" in spec.include
    if students:
        grouped = defaultdict(list)
        for paper in papers:
            grouped[paper.item.student_id].append(paper)
        groups = sorted(grouped.items())
    else:
        groups = sorted((paper.item.submission_id, [paper]) for paper in papers)

    def sort_value(group):
        values = (getattr(paper.item, spec.sort.field) for paper in group[1])
        return max((value for value in values if value is not None), default=None)

    dated, undated = [], []
    for group in groups:
        value = sort_value(group)
        if value is None:
            undated.append(group)
        else:
            dated.append((value, group))
    dated.sort(key=lambda entry: entry[0], reverse=spec.sort.direction == "desc")
    ordered = [group for _, group in dated] + undated
    start = (spec.page - 1) * spec.page_size
    end = start + spec.page_size
    page_papers, items = [], []
    for ident, records in ordered[start:end]:
        if set(spec.include).intersection(("items", "students", "sources")):
            page_papers.extend(records)
        if "items" not in spec.include and "students" not in spec.include:
            continue
        if students:
            items.append(StudentSummaryItem(
                **roster[ident], matched_record_count=len(records),
                status_counts=Counter(record.item.publication_status for record in records),
                latest_status_date=max((record.item.status_date for record in records if record.item.status_date),
                                       default=None),
                source_ids=[record.item.version_id for record in records],
                links=EvidenceLinks(portrait_url=records[0].item.links.portrait_url),
            ))
        else:
            items.append(records[0].item)
    return items, page_papers, Pagination(page=spec.page, page_size=spec.page_size,
                                         total=len(groups), has_more=end < len(groups))


def _sources(session, papers):
    files_by_submission = {}
    file_ids = {fid for paper in papers for fid in paper.file_ids}
    if file_ids:
        query = (select(File.id, File.submission_id, File.name, File.media_type, File.size, File.sha256)
                 .join(Submission, Submission.id == File.submission_id)
                 .where(File.id.in_(file_ids), File.owner_id == Submission.student_id, File.status == "ready",
                        File.submission_id.in_({paper.item.submission_id for paper in papers})))
        for row in session.execute(query):
            files_by_submission[row.submission_id, row.id] = EvidenceFile(
                file_id=row.id, name=row.name, media_type=row.media_type, size=row.size, sha256=row.sha256,
                download_url=f"/api/v1/files/{row.id}/download",
            )
    sources = {}
    for paper in papers:
        item = paper.item
        verification = "submitted_unarchived_version"
        if item.archive_id:
            if item.simulation or item.review_actor_type == "simulation":
                verification = "simulated_approved_submission"
            elif item.review_actor_type == "agent":
                verification = "agent_approved_submission"
            else:
                verification = "human_approved_submission"
        pointers = [FieldPointer(field=field, pointer=f"/form/{field}", value=paper.form[field],
                                 verification=verification)
                    for field in (*FIELDS["paper"], "journal", "doi")
                    if isinstance(paper.form.get(field), str) and paper.form[field].strip()]
        sources[item.version_id] = EvidenceSource(
            source_id=item.version_id, kind="paper", student_id=item.student_id, version_id=item.version_id,
            submission_id=item.submission_id, version_number=item.version_number, archive_id=item.archive_id,
            snapshot_id=paper.snapshot_id, decision_id=paper.decision_id, review_actor_type=item.review_actor_type,
            ai_job_id=paper.ai_job_id, archived_at=item.archived_at, simulation=item.simulation, field_pointers=pointers,
            files=[files_by_submission[item.submission_id, fid] for fid in paper.file_ids
                   if (item.submission_id, fid) in files_by_submission],
            portrait_url=item.links.portrait_url, submission_url=item.links.submission_url,
        )
    return sources


def _portrait_papers(session, user, student):
    student_id = student["student_id"]
    if not relation(session, user.id, student_id):
        raise ResourceNotFoundError("学生不存在或无权访问")
    papers = []
    annual = pending = 0
    for row in _versions(session, user, [student_id], "current_effective_archives", ["annual", "paper"]):
        if not row.snapshot_id:
            pending += 1
        elif row.Submission.kind == "annual":
            annual += 1
        else:
            paper = _paper(row, student, "current_effective_archives")
            if paper:
                papers.append(paper)
    papers.sort(key=attrgetter("item.archived_at", "item.submission_id"))
    return papers, annual, pending


def _portrait(session, student, papers, sources, annual, pending):
    student_id = student["student_id"]
    timestamp = now()
    teachers = session.execute(
        select(User.id, User.name).join(Supervision, Supervision.teacher_id == User.id)
        .where(Supervision.student_id == student_id, User.role == "teacher", User.enabled == 1,
               Supervision.valid_from <= timestamp, (Supervision.valid_to.is_(None)) | (Supervision.valid_to > timestamp))
        .order_by(User.name, User.id))
    records = []
    for paper in papers:
        source = sources[paper.item.version_id]
        records.append(PortraitPaperRecord(
            **source.model_dump(include=set(PortraitPaperRecord.model_fields)),
            **paper.item.model_dump(include={"title", "publication_status", "status_date", "journal",
                                             "doi", "contribution"}),
        ))
    return StudentPortraitPanel(**student, teachers=[TeacherRef(id=row.id, name=row.name) for row in teachers],
                                counts=PortraitCounts(paper_records=len(records), annual_records=annual),
                                pending_snapshot_count=pending, records=records,
                                portrait_url=f"/api/v1/students/{student_id}/portrait", notice=_NOTICE)


def materialize(session: Session, user: User, spec: PaperQuerySpec, *, run_id: str, data_as_of: str,
                scope_recomputed: bool = False) -> ResultEnvelope:
    if not user or not user.enabled or user.role not in ("teacher", "manager"):
        raise ForbiddenRoleError("仅导师或管理教师可查询论文")
    scope = scope_ids(session, user)
    visible_ids = set(scope)
    for predicate in spec.filters:
        if predicate.field != "student_id":
            continue
        requested_ids = set(predicate.value if isinstance(predicate.value, list) else [predicate.value])
        if not requested_ids <= visible_ids:
            raise ResourceNotFoundError("学生不存在或无权访问")
    roster = _roster(session, scope, spec.filters)
    want_portrait = spec.operation == "portrait" or "portrait" in spec.include
    selectors = [predicate for predicate in spec.filters if predicate.field in _STUDENT_SELECTORS]
    if not roster and selectors and not _roster(session, scope, selectors):
        raise ResourceNotFoundError("学生不存在或无权访问")
    if want_portrait and not roster and selectors:
        raise ResourceNotFoundError("学生不存在或无权访问")
    if want_portrait and len(roster) != 1:
        candidates = [DisambiguationCandidate(**{field: student[field] for field in DisambiguationCandidate.model_fields})
                      for student in roster.values()]
        return ResultEnvelope(status="clarification_needed", applied_query=spec, clarification=ClarificationPrompt(
            message="请选择一位学生查看画像。", student_candidates=candidates))
    papers = _papers(session, user, roster, spec)
    summary = _summary(papers, spec, data_as_of, len(scope), scope_recomputed)
    items, page_papers, pagination = _page(papers, spec, roster)
    portrait = None
    evidence = {paper.item.version_id: paper for paper in page_papers}
    if want_portrait:
        student = next(iter(roster.values()))
        portrait_papers, annual, pending = _portrait_papers(session, user, student)
        evidence.update((paper.item.version_id, paper) for paper in portrait_papers)
    sources = _sources(session, evidence.values())
    if want_portrait:
        portrait = _portrait(session, student, portrait_papers, sources, annual, pending)
    return ResultEnvelope(query_run_id=run_id, applied_query=spec, summary=summary, items=items,
                          pagination=pagination, sources=list(sources.values()), portrait=portrait)
