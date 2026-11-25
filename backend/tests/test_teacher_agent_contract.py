import json
from pathlib import Path
import re
import runpy

import pytest
from pydantic import ValidationError

from app.teacher_agent.contract import (
    METRIC_CATALOG,
    ConversationDetail,
    PaperQuerySpec,
    PlannerOutputAdapter,
    QueryPatch,
    ResultEnvelope,
    ScholarshipQuerySpec,
    TurnRequest,
    TurnResponse,
    TurnTimelineItem,
    apply_patch,
    export_schemas,
    validate_query_spec,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "teacher-agent"
YEAR = {"field": "year", "value": "2023"}
DEGREE = {"field": "degree", "value": "博士"}
DATE_RANGE = {"from": "2026-01-01", "to": "2026-12-31"}


@pytest.mark.parametrize("invalid", [
    {"period": "2026"},
    {"filters": [{"field": "period", "value": "2026"}]},
    {"filters": [{"field": "review_status", "value": "draft"}]},
    {"filters": [{"field": "review_status", "operator": "in", "value": ["archived", "returned"]}]},
    {"filters": [YEAR, YEAR]},
    {"filters": [{"field": "degree", "operator": "in", "value": "博士"}]},
    {"filters": [{"field": "degree", "operator": "in", "value": []}]},
    {"filters": [{"field": "degree", "operator": "in", "value": ["博士"] * 51}]},
    {"filters": [{"field": "degree", "value": ["博士"]}]},
    {"filters": [{"field": "award_name", "value": "奖学金"}]},
    {"filters": [{"field": "publication_status", "value": "approved"}]},
    {"basis": "submitted_latest", "time_range": {**DATE_RANGE, "field": "archived_at"}},
    {"time_range": {**DATE_RANGE, "from": "2026-02-29"}},
    {"time_range": {**DATE_RANGE, "to": "2025-01-01"}},
    {"operation": "portrait"},
    {"operation": "portrait", "filters": [{"field": "student_id", "value": "s01"}], "group_by": ["degree"]},
    {"group_by": ["year", "year"]},
    {"include": ["sources", "sources"]},
    {"page": 0},
    {"page_size": 101},
])
def test_reject_invalid_paper_query(invalid):
    with pytest.raises(ValidationError):
        validate_query_spec({"domain": "paper", **invalid})


def test_patch_removes_then_upserts_by_field_without_mutating_inputs():
    previous = PaperQuerySpec(filters=[YEAR, DEGREE], page=6)
    patch = QueryPatch(
        remove_filter_fields=["degree", "degree", "major"],
        set_filters=[
            {"field": "year", "operator": "in", "value": [" 2024 ", "2025级"]},
            {"field": "student_number", "value": "SIM20240004"},
            {"field": "degree", "value": "硕士"},
        ],
        operation="list",
        time_range=DATE_RANGE,
        group_by=["year"],
        distinct_subject="student",
        include=["students", "sources"],
        sort={"field": "year", "direction": "asc"},
        page_size=3,
    )
    before_query = previous.model_dump()
    before_patch = patch.model_dump()
    updated = apply_patch(previous, patch)
    assert updated == PaperQuerySpec(
        operation="list", filters=patch.set_filters, time_range=DATE_RANGE, group_by=["year"],
        distinct_subject="student", include=["students", "sources"], sort=patch.sort, page=1, page_size=3,
    )
    assert updated.filters[0].value == ["2024级", "2025级"]
    assert updated.time_range.model_dump(by_alias=True)["from"] == DATE_RANGE["from"]
    assert apply_patch(updated, patch) == updated
    updated.filters.clear()
    assert previous.model_dump() == before_query
    assert patch.model_dump() == before_patch


@pytest.mark.parametrize(("delta", "page"), [
    ({}, 7),
    ({"page_size": 1}, 7),
    ({"time_range": DATE_RANGE, "set_filters": [YEAR]}, 7),
    ({"clear_time_range": True}, 1),
    ({"remove_filter_fields": ["major"]}, 7),
    ({"set_filters": [DEGREE], "reset_page": False}, 7),
    ({"set_filters": [DEGREE], "page": 2}, 2),
])
def test_patch_pagination_depends_on_semantic_change(delta, page):
    previous = PaperQuerySpec(filters=[YEAR], time_range=DATE_RANGE, page=7)
    updated = apply_patch(previous, QueryPatch(**delta))
    assert updated.page == page
    if delta.get("clear_time_range"):
        assert updated.time_range is None


@pytest.mark.parametrize("predicate", [
    {"field": "review_status", "value": "returned"},
    {"field": "review_status", "operator": "in", "value": ["approved", "pending_review"]},
])
def test_only_implicit_basis_upgrades(predicate):
    previous = PaperQuerySpec(page=5)
    patch = QueryPatch(set_filters=[predicate])
    assert apply_patch(previous, patch).basis == "submitted_latest"
    assert apply_patch(previous, QueryPatch(set_filters=[{"field": "review_status", "value": "archived"}])).basis == previous.basis
    with pytest.raises(ValidationError):
        apply_patch(previous, QueryPatch(set_filters=[predicate], basis="current_effective_archives"))
    with pytest.raises(ValidationError):
        apply_patch(PaperQuerySpec(time_range={**DATE_RANGE, "field": "archived_at"}), patch)


def test_patch_validates_in_original_domain():
    paper = PaperQuerySpec()
    scholarship = ScholarshipQuerySpec()
    award = {"field": "award_name", "value": "奖学金"}
    delta = QueryPatch(set_filters=[award], group_by=["award_name"], distinct_subject="applicant")
    assert apply_patch(scholarship, delta).filters[0].field == "award_name"
    with pytest.raises(ValidationError):
        QueryPatch(remove_filter_fields=["period"])
    for previous, invalid in [
        (paper, delta),
        (paper, QueryPatch(remove_filter_fields=["award_name"])),
        (scholarship, QueryPatch(remove_filter_fields=["title"])),
        (paper, QueryPatch(sort={"field": "submitted_at"})),
        (scholarship, QueryPatch(time_range={**DATE_RANGE, "field": "status_date"})),
        (paper, QueryPatch(operation="portrait")),
    ]:
        with pytest.raises(ValueError):
            apply_patch(previous, invalid)
    updated = apply_patch(scholarship, QueryPatch(time_range=DATE_RANGE, sort={"direction": "asc"}))
    assert updated.time_range.field == updated.sort.field == "submitted_at"


def test_planner_and_drilldown_use_the_same_patch():
    delta = {"set_filters": [YEAR], "page_size": 10}
    plan = PlannerOutputAdapter.validate_python({"action": "patch", "patch": delta})
    turn = TurnRequest(input={"mode": "drilldown_patch", "patch": delta}, expected_lock_version=1)
    assert apply_patch(PaperQuerySpec(), plan.patch) == apply_patch(PaperQuerySpec(), turn.input.patch)
    with pytest.raises(ValidationError):
        PlannerOutputAdapter.validate_python({"action": "run_sql", "query": "SELECT 1"})


@pytest.mark.parametrize("status", ["unsupported_domain", "clarification_needed"])
def test_clarification_payload_required(status):
    with pytest.raises(ValidationError):
        ResultEnvelope(status=status)
    assert ResultEnvelope(status=status, clarification={"message": "请选择学生"}).clarification.message == "请选择学生"


def test_frozen_schemas_and_result_evidence():
    artifact = json.loads((FIXTURES / "schemas_and_mocks.json").read_text())
    schemas = export_schemas()
    assert {key: artifact[key] for key in schemas} == schemas
    for payload in artifact["mocks"].values():
        result = ResultEnvelope.model_validate(payload)
        assert result.model_dump(mode="json", by_alias=True) == payload
        assert all(card.unit == METRIC_CATALOG[card.key].unit for card in result.summary.metrics)
        with pytest.raises(ValidationError, match="unknown source_ids"):
            ResultEnvelope.model_validate({**payload, "sources": []})
        if result.portrait:
            with pytest.raises(ValidationError, match="portrait record references unknown source_id"):
                ResultEnvelope.model_validate({**payload, "items": [], "sources": []})


def test_multirun_turn_and_legacy_readers():
    artifact = json.loads((FIXTURES / "schemas_and_mocks.json").read_text())
    payload = artifact["turn_mocks"]["paper_multirun_turn"]
    response = TurnResponse.model_validate(payload)
    assert response.model_dump(mode="json", by_alias=True) == payload
    overview, published = response.results
    assert [card.applied_query.operation for card in response.results] == ["aggregate", "list"]
    assert response.result == published
    assert response.turn.run_id == published.query_run_id != overview.query_run_id
    assert response.turn.run_ids == [overview.query_run_id, published.query_run_id]
    assert "analysis" not in payload["turn"]
    assert response.analysis_notice is None
    assert re.findall(r"\[([^\]]+)\]", response.analysis) == response.turn.run_ids
    for card in response.results:
        assert (card.conversation_id, card.turn_id) == (response.conversation_id, response.turn.id)
        assert card.sources

    legacy_turn = response.turn.model_dump(exclude={"run_ids"})
    legacy = TurnResponse.model_validate({
        "conversation_id": response.conversation_id, "conversation_lock_version": 1,
        "turn": legacy_turn, "result": published,
    })
    assert legacy.results == [published]
    assert legacy.turn.run_ids == [published.query_run_id]
    assert legacy.analysis is None
    assert legacy.analysis_notice is None
    conversation = dict(
        id=response.conversation_id, title="论文", active_domain="paper", status="active",
        turn_count=1, lock_version=1, created_at=response.turn.created_at, updated_at=response.turn.created_at,
    )
    detail = ConversationDetail(conversation=conversation, turns=[response.turn], latest_result=published,
                                latest_results=response.results)
    assert detail.latest_results == response.results
    assert "analysis" not in detail.model_dump()["turns"][0]
    assert "analysis_notice" not in detail.model_dump()
    assert "analysis_notice" not in detail.model_dump()["turns"][0]
    assert ConversationDetail(conversation=conversation, latest_result=published).latest_results == [published]
    assert ConversationDetail(conversation=conversation).latest_results == []


def test_unverified_analysis_notice_preserves_all_run_cards():
    artifact = json.loads((FIXTURES / "schemas_and_mocks.json").read_text())
    mocks = artifact["turn_mocks"]
    response = TurnResponse.model_validate(mocks["paper_multirun_unverified_analysis"])
    verified = TurnResponse.model_validate(mocks["paper_multirun_turn"])
    assert response.analysis is None
    assert response.analysis_notice
    assert response.turn.status == "succeeded"
    assert response.results == verified.results
    assert response.result == response.results[-1]


def test_history_and_clarification_without_visible_runs():
    timeline = dict(id="turn-1", turn_index=1, input_mode="natural_language", user_message="查看论文",
                    status="clarification_needed", created_at="2026-11-19T02:00:00Z")
    notice = ResultEnvelope(status="clarification_needed", clarification={"message": "请选择学生"})
    turn = TurnResponse(conversation_id="conv-1", conversation_lock_version=1, turn=timeline, result=notice)
    assert turn.results == turn.turn.run_ids == []
    revoked = TurnTimelineItem(**timeline, run_id="previous-run", access_revoked=True)
    assert revoked.run_ids == []


def test_fixtures_regenerate_from_fixed_seed():
    generated = runpy.run_path(str(FIXTURES / "generate.py"))["build_artifact"]()
    expected = json.loads((FIXTURES / "schemas_and_mocks.json").read_text())
    assert generated == expected
