from datetime import date

import pytest
from sqlalchemy import select

from app.db import Archive, Base, Decision, File, PortraitSnapshot, Submission, User, Version, connect
from app.policy import relation
from app.seed import seed
from app.seed_scenarios import ident, seed_scenarios
from app.teacher_agent.contract import PaperQuerySpec, apply_patch
from app.teacher_agent.errors import ForbiddenRoleError, ResourceNotFoundError
from app.teacher_agent.papers import materialize


STAMP = "2026-11-19T02:00:00+00:00"
YEAR = {"field": "status_date", "from": "2026-01-01", "to": "2026-12-31"}


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    root = tmp_path_factory.mktemp("paper-queries")
    engine, factory = connect(f"sqlite:///{root / 'cohort.db'}")
    Base.metadata.create_all(engine)
    seed(factory)
    seed_scenarios(factory, root / "files", root / "bundle", date(2026, 11, 19))
    yield factory
    engine.dispose()


@pytest.fixture
def session(cohort):
    with cohort() as session:
        yield session


def actor(session, username):
    return session.scalar(select(User).where(User.username == username))


def run(session, spec=None, *, username="teacher", scope_recomputed=False, **query):
    return materialize(session, actor(session, username), spec or PaperQuerySpec(**query),
                       run_id="run-1", data_as_of=STAMP, scope_recomputed=scope_recomputed)


def predicate(field, value, operator="eq"):
    return {"field": field, "operator": operator, "value": value}


def test_visible_student_excluded_by_roster_filter(session):
    filters = [predicate("student_id", ident("s01")), predicate("degree", "硕士")]
    assert run(session, filters=filters).pagination.total == 0
    with pytest.raises(ResourceNotFoundError):
        run(session, operation="portrait", filters=filters)


def test_group_totals_survive_an_empty_sources_page(session):
    filters = [predicate("student_id", ident("s01")), predicate("has_doi", False)]
    result = run(session, filters=filters, time_range=YEAR, group_by=["publication_status"],
                 include=["sources"], page=20, page_size=1)
    assert result.pagination.total == 2 and not result.pagination.has_more
    assert not result.sources and not result.items and not result.summary.metrics
    assert [(row.group_key, row.record_count, row.student_count) for row in result.summary.breakdown] == [
        ({"publication_status": "accepted"}, 1, 1), ({"publication_status": "published"}, 1, 1)]


@pytest.mark.parametrize(("reviewer", "verification"), [
    ("human", "human_approved_submission"), ("agent", "agent_approved_submission")])
def test_archived_evidence_uses_actual_review_actor(session, reviewer, verification):
    sub = session.get(Submission, ident("submission/s01/paper0"))
    version = session.get(Version, sub.current_version_id)
    version.snapshot = {**version.snapshot, "simulation": False}
    archive = session.get(Archive, sub.effective_archive_id)
    session.get(Decision, archive.decision_id).actor_type = reviewer
    result = run(session, filters=[predicate("student_id", sub.student_id)])
    source = next(source for source in result.sources if source.version_id == version.id)
    assert {pointer.verification for pointer in source.field_pointers} == {verification}


def test_real_seed_2026_metrics_and_executable_drilldowns(session):
    spec = PaperQuerySpec(time_range=YEAR, group_by=["publication_status", "degree"], page=2, page_size=2)
    result = run(session, spec)
    assert result.summary.scope_student_count == 14
    assert result.summary.data_as_of == STAMP
    assert result.applied_query == spec
    assert result.query_run_id == "run-1"
    assert {card.key: card.value for card in result.summary.metrics} == {
        "paper_record_count": 18, "paper_student_count": 12,
        "paper_published_record_count": 3, "paper_published_student_count": 3,
        "paper_accepted_record_count": 12, "paper_accepted_student_count": 9,
        "paper_submitted_record_count": 3, "paper_submitted_student_count": 3,
    }
    for card in result.summary.metrics:
        target = apply_patch(spec, card.drilldown_patch)
        listing = run(session, target)
        assert target.operation == "list" and target.page == 1 and target.time_range == spec.time_range
        assert listing.pagination.total == card.value
        expected_kind = "student_summary" if card.subject == "student" else "paper_record"
        assert all(item.item_kind == expected_kind for item in listing.items)
        if card.subject == "student":
            for item in listing.items:
                assert len(item.source_ids) == item.matched_record_count == sum(item.status_counts.values())
                assert {source.student_id for source in listing.sources if source.source_id in item.source_ids} == {
                    item.student_id}
    assert sum(row.record_count for row in result.summary.breakdown) == 18
    for row in result.summary.breakdown:
        listing = run(session, apply_patch(spec, row.drilldown_patch))
        assert listing.pagination.total == row.record_count
        assert next(card.value for card in listing.summary.metrics if card.key == "paper_student_count") == row.student_count
        assert all(getattr(item, field) == value for item in listing.items for field, value in row.group_key.items())


def test_controlled_filters_and_status_dates(session):
    student = session.get(User, ident("s01"))
    result = run(session, filters=[
        predicate("student_id", [student.id, ident("s02")], "in"),
        predicate("student_name", student.name), predicate("student_number", "202300", "contains"),
        predicate("degree", ["博士"], "in"), predicate("major", "智能", "contains"),
        predicate("direction", "学习分析", "contains"), predicate("year", ["2023"], "in"),
        predicate("stage", ["毕业研究"], "in"), predicate("journal", "非真实", "contains"),
        predicate("has_doi", False), predicate("title", "验证", "contains"), predicate("simulation", True),
        predicate("publication_status", "submitted", "neq"), predicate("review_status", ["archived"], "in"),
    ])
    assert [item.submission_id for item in result.items] == [ident("submission/s01/paper0")]
    for field, value in [("journal", "%"), ("major", "_"), ("title", "缺失"), ("has_doi", True), ("simulation", False)]:
        operator = "contains" if isinstance(value, str) else "eq"
        assert run(session, filters=[predicate(field, value, operator)]).pagination.total == 0
    item = result.items[0]
    for field, expected_date in (("status_date", item.publication_date), ("publication_date", item.publication_date),
                                 ("archived_at", item.archived_at[:10])):
        exact = run(session, time_range={"from": expected_date, "to": expected_date, "field": field},
                    filters=[predicate("student_id", student.id)])
        assert [row.version_id for row in exact.items] == [item.version_id]


@pytest.mark.parametrize("sort_field", ["status_date", "student_name", "year", "archived_at"])
def test_ordered_pages_and_page_local_sources(session, sort_field):
    query = {"sort": {"field": sort_field, "direction": "desc"}, "page_size": 5}
    pages = [run(session, page=page, **query) for page in range(1, 6)]
    items = [item for page in pages for item in page.items]
    assert len({item.submission_id for item in items}) == len(items) == 18
    assert [page.pagination.has_more for page in pages] == [True, True, True, False, False]
    assert all(page.pagination.total == 18 for page in pages)
    assert items == sorted(sorted(items, key=lambda item: item.submission_id),
                           key=lambda item: getattr(item, sort_field), reverse=True)
    for page in pages:
        assert [source.source_id for source in page.sources] == [item.source_ids[0] for item in page.items]
    ascending = run(session, sort={"field": sort_field, "direction": "asc"})
    assert ascending.items == sorted(sorted(items, key=lambda item: item.submission_id),
                                     key=lambda item: getattr(item, sort_field))


def test_includes_and_pagination_of_distinct_students(session):
    metrics = run(session, include=["metrics"])
    assert metrics.summary.metrics and metrics.pagination.total == 18
    assert not metrics.items and not metrics.sources and metrics.portrait is None
    students = run(session, include=["students"], filters=[predicate("year", "2023")],
                   page=2, page_size=1, sort={"field": "year", "direction": "asc"})
    assert not students.summary.metrics and students.pagination.total == 3 and students.pagination.has_more
    student = students.items[0]
    assert student.item_kind == "student_summary" and student.matched_record_count == 2
    assert student.student_id == sorted(ident(key) for key in ("s01", "s02", "s03"))[1]
    assert student.latest_status_date == max(
        session.get(Version, source.version_id).snapshot["form"][key]
        for source in students.sources for key in ("publication_date", "acceptance_date")
        if key in session.get(Version, source.version_id).snapshot["form"])
    assert sorted(student.source_ids) == sorted(source.source_id for source in students.sources)
    sources = run(session, include=["sources"], page_size=1)
    assert not sources.items and len(sources.sources) == 1 and not sources.summary.metrics


def latest_revision(session):
    sub = session.get(Submission, ident("submission/s01/paper0"))
    first = session.get(Version, sub.current_version_id)
    file = session.get(File, first.snapshot["file_ids"][0])
    attachment = File(owner_id=sub.student_id, submission_id=sub.id, name="revision.pdf", media_type="application/pdf",
                      storage_key="revision", sha256=file.sha256, size=20)
    session.add(attachment)
    session.flush()
    snapshot = {**first.snapshot, "simulation": False, "period": None, "file_ids": [attachment.id],
                "form": {**first.snapshot["form"], "title": "Revision", "journal": "Revision Journal",
                         "publication_status": "accepted", "acceptance_date": "2025-01-03", "doi": "10.0/paper"}}
    second = Version(submission_id=sub.id, number=2, snapshot=snapshot)
    session.add(second)
    session.flush()
    sub.current_version_id = second.id
    sub.status = "pending_review"
    sub.draft = {"form": {"title": "unsubmitted draft"}, "file_ids": [ident("file/s02/paper0")]}
    return sub, first, second, attachment


def test_basis_selects_one_version_for_status_date_links_and_files(session):
    sub, first, second, attachment = latest_revision(session)
    selector = [predicate("student_number", "SIM20230001")]
    latest = {"basis": "submitted_latest", "filters": selector + [predicate("review_status", "pending_review")]}
    assert not run(session, time_range=YEAR, **latest).items
    result = run(session, time_range={**YEAR, "field": "publication_date"}, **latest)
    item, = result.items
    source, = result.sources
    assert (item.submission_id, item.version_id, item.version_number) == (sub.id, second.id, 2)
    assert (item.review_status, item.publication_status, item.status_date) == ("pending_review", "accepted", "2025-01-03")
    assert (item.title, item.journal, item.doi) == ("Revision", "Revision Journal", "10.0/paper")
    assert source.archive_id is source.snapshot_id is source.decision_id is source.review_actor_type is None
    assert [file.file_id for file in source.files] == [attachment.id]
    assert {pointer.verification for pointer in source.field_pointers} == {"submitted_unarchived_version"}
    assert "unsubmitted draft" not in result.model_dump_json()
    assert "storage_key" not in result.model_dump_json()

    portrait_result = run(session, operation="portrait", **latest)
    panel = portrait_result.portrait
    assert panel.counts.paper_records == 2 and panel.counts.annual_records == 2
    assert panel.ability_assessment == "待评价" and panel.inferences == []
    assert [teacher.id for teacher in panel.teachers] == [actor(session, "teacher").id]
    record = next(record for record in panel.records if record.submission_id == sub.id)
    assert (record.version_id, record.archive_id, record.decision_id) == (
        first.id, sub.effective_archive_id, ident("decision/s01/paper0"))
    assert record.snapshot_id and record.journal == first.snapshot["form"]["journal"]
    assert record.doi == first.snapshot["form"]["doi"] and record.title == first.snapshot["form"]["title"]
    assert [file.file_id for file in record.files] == first.snapshot["file_ids"]
    assert record.files[0].download_url == f"/api/v1/files/{record.files[0].file_id}/download"
    assert {pointer.verification for pointer in record.field_pointers} == {"simulated_approved_submission"}
    assert {source.source_id for source in portrait_result.sources} == {
        second.id, *(record.source_id for record in panel.records)}
    archived = run(session, filters=selector + [predicate("publication_status", "published")])
    assert archived.items[0].review_status == "archived" and archived.items[0].version_id == first.id


def test_file_provenance_and_dangling_references(session):
    sub, first, second, attachment = latest_revision(session)
    real_file = session.get(File, first.snapshot["file_ids"][0])
    bad_file = File(owner_id=ident("s02"), submission_id=sub.id, name="wrong owner", media_type=real_file.media_type,
                    size=1, storage_key="wrong-owner", sha256=real_file.sha256)
    session.add(bad_file)
    session.flush()
    second.snapshot = {**second.snapshot, "file_ids": [
        attachment.id, ident("file/s02/paper0"), ident("file/s01/paper1"), "missing", bad_file.id, attachment.id]}
    result = run(session, basis="submitted_latest", filters=[predicate("review_status", "pending_review")])
    assert [file.file_id for file in result.sources[0].files] == [attachment.id]

    selector = [predicate("student_id", sub.student_id), predicate("publication_status", "published")]
    for wrong_archive in (ident("archive/s02/paper0"), "missing"):
        sub.effective_archive_id = wrong_archive
        assert run(session, filters=selector).pagination.total == 0
    sub.effective_archive_id = ident("archive/s01/paper0")
    for wrong_version in (ident("version/s02/paper0"), "missing", None):
        sub.current_version_id = wrong_version
        for basis in ("current_effective_archives", "submitted_latest"):
            assert run(session, basis=basis, filters=selector).pagination.total == 0
    sub.current_version_id = first.id
    sub.status = "draft"
    assert run(session, filters=selector).pagination.total == 0
    assert run(session, basis="submitted_latest", filters=selector).pagination.total == 0


def test_missing_snapshot_is_pending_and_wrong_decision_cannot_approve_archive(session):
    sub = session.get(Submission, ident("submission/s01/paper0"))
    archive = session.get(Archive, sub.effective_archive_id)
    snapshot = session.scalar(select(PortraitSnapshot).where(PortraitSnapshot.archive_id == archive.id))
    session.delete(snapshot)
    result = run(session, filters=[predicate("student_id", sub.student_id)], include=["portrait"])
    assert result.pagination.total == 2
    assert result.portrait.pending_snapshot_count == 1 and result.portrait.counts.paper_records == 1
    assert {source.version_id for source in result.sources} == {ident("version/s01/paper1")}
    other_decision = Decision(version_id=ident("version/s04/review-task"), reviewer_id=actor(session, "teacher").id,
                              outcome="approved", opinion="unrelated")
    other_decision.version_id = ident("version/s05/review")
    session.add(other_decision)
    session.flush()
    archive.decision_id = other_decision.id
    result = run(session, filters=[predicate("student_id", sub.student_id)], include=["portrait", "items"])
    assert result.pagination.total == 1 and result.portrait.pending_snapshot_count == 0
    assert all(source.decision_id != other_decision.id for source in result.sources)


def test_live_scope_roles_and_portrait_ambiguity_precede_paper_lookup(session):
    teacher, manager = actor(session, "teacher"), actor(session, "manager")
    with_papers, without_papers = session.get(User, ident("s01")), actor(session, "student1")
    without_papers.name = with_papers.name
    outsider = session.get(User, ident("s02"))
    outsider.name = with_papers.name
    relation(session, teacher.id, outsider.id).valid_to = "2000-01-01"
    relation(session, manager.id, outsider.id).valid_from = "9999-01-01"
    for username in ("teacher", "manager"):
        for selector in (predicate("student_name", with_papers.name, "contains"),
                         predicate("student_id", [with_papers.id, without_papers.id], "in")):
            result = run(session, operation="portrait", filters=[selector], username=username)
            assert result.status == "clarification_needed"
            assert sorted(item.student_id for item in result.clarification.student_candidates) == sorted(
                [with_papers.id, without_papers.id])
            assert not result.sources and not result.items and result.portrait is None
        for selector in (predicate("student_id", outsider.id), predicate("student_number", "SIM20230002"),
                         predicate("student_name", "不存在的学生")):
            with pytest.raises(ResourceNotFoundError):
                run(session, operation="portrait", filters=[selector], username=username)
    result = run(session, operation="portrait", filters=[predicate("student_number", "student1")])
    assert result.portrait.student_id == without_papers.id
    assert result.portrait.counts.paper_records == 0 and not result.portrait.records
    assert result.summary.scope_student_count == 13
    relation(session, teacher.id, with_papers.id).valid_to = "2000-01-01"
    refreshed = run(session, scope_recomputed=True)
    assert refreshed.summary.scope_recomputed and refreshed.summary.scope_student_count == 12
    assert {source.student_id for source in refreshed.sources}.isdisjoint({with_papers.id, outsider.id})
    teacher.enabled = 0
    for username in ("teacher", "student1", "operator", "__innograd_simulation__"):
        with pytest.raises(ForbiddenRoleError):
            run(session, username=username)
