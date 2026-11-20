import json
from pathlib import Path

import pytest

from app.teacher_agent.contract import BreakdownRow, PaperQuerySpec, PaperTimeRange, ResultEnvelope
from app.teacher_agent.errors import PlannerInvalidOutputError, ResourceNotFoundError, RetryableToolInputError, TeacherAgentError
from app.teacher_agent.privacy import (
    Student, agent_clarification_subjects, agent_tool_view, prepare_agent_question, prepare_question,
    render_agent_analysis, render_agent_response,
    resolve_agent_spec, student_ids,
)


ROSTER = [Student("id-a", "李四", "A100"), Student("id-b", "王宁", "B200")]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "teacher-agent" / "schemas_and_mocks.json"


@pytest.fixture
def portrait():
    return ResultEnvelope.model_validate(json.loads(FIXTURES.read_text())["mocks"]["student_portrait_trace"])


def test_school_question_preserves_prose_and_legacy_planner_keeps_its_boundary():
    question = "李四：你觉得投稿前后的研究节奏有什么变化？\n请结合导师反馈。"
    assert prepare_agent_question(f" {question} ", ROSTER) == (question, ["id-a"])
    assert prepare_question(question, ROSTER) == (None, ["id-a"])
    assert prepare_question("查看李四的论文", ROSTER) == ("查看指定学生的论文", ["id-a"])
    assert prepare_agent_question(" \t", ROSTER) == (None, [])


def test_same_name_requires_an_unambiguous_teacher_selection():
    students = [*ROSTER, Student("id-c", "李四", "C300")]
    assert agent_clarification_subjects("查看李四的论文", students) == ["id-a", "id-c"]
    assert agent_clarification_subjects("查看李四 C300 的论文", students) == []
    assert agent_clarification_subjects("对比李四和王宁", students) == ["id-a", "id-c"]
    assert agent_clarification_subjects("查看 id-c 的论文", students) == []


@pytest.mark.parametrize(("field", "value"), [
    ("student_id", "id-a"), ("student_name", "李四"), ("student_number", "A100"),
    ("student_id", "selected-student"),
])
def test_authorized_selectors_preserve_query_filters(field, value):
    spec = PaperQuerySpec(filters=[{"field": field, "value": value}, {"field": "major", "value": "物理"}])
    resolved = resolve_agent_spec(spec, ["id-a"], ROSTER)
    assert student_ids(resolved) == ["id-a"]
    assert resolved.filters[0].value == "物理"


def test_named_student_and_group_can_be_compared_in_one_turn():
    _, selected = prepare_agent_question("李四与全组的表现有何差异？", ROSTER)
    group = PaperQuerySpec(filters=[{"field": "degree", "value": "博士"}])
    assert resolve_agent_spec(group, selected, ROSTER) == group
    for field, value in (("student_id", "id-b"), ("student_name", ROSTER[1].name), ("student_number", "B200")):
        spec = PaperQuerySpec(filters=[{"field": field, "value": value}])
        assert student_ids(resolve_agent_spec(spec, selected, ROSTER)) == ["id-b"]
    combined = PaperQuerySpec(filters=[{"field": "student_id", "operator": "in",
                                        "value": ["selected-student", "id-b"]}])
    assert student_ids(resolve_agent_spec(combined, selected, ROSTER)) == ["id-a", "id-b"]


@pytest.mark.parametrize(("field", "value", "selected"), [
    ("student_id", "hidden", []),
    ("student_id", "hidden", ["id-a"]), ("student_number", "hidden", ["id-a"]),
    ("student_id", "selected-student", ["revoked"]),
])
def test_scope_is_checked_before_execution(field, value, selected):
    with pytest.raises(ResourceNotFoundError):
        resolve_agent_spec(PaperQuerySpec(filters=[{"field": field, "value": value}]), selected, ROSTER)


def test_unknown_names_have_identical_neutral_feedback():
    messages = []
    for name in ("校外学生", "未登记姓名"):
        spec = PaperQuerySpec(filters=[{"field": "student_name", "operator": "eq", "value": name}])
        with pytest.raises(RetryableToolInputError) as caught:
            resolve_agent_spec(spec, [], ROSTER)
        messages.append(str(caught.value))
        assert name not in messages[-1]
    assert messages[0] == messages[1]


@pytest.mark.parametrize("field", ["student_id", "student_number"])
def test_unknown_name_cannot_mask_a_denied_identifier(field):
    spec = PaperQuerySpec(filters=[
        {"field": "student_name", "value": "校外学生"}, {"field": field, "value": "hidden"},
    ])
    with pytest.raises(ResourceNotFoundError):
        resolve_agent_spec(spec, [], ROSTER)


def test_sentinel_cannot_discard_other_subject_selectors():
    spec = PaperQuerySpec(filters=[{"field": "student_id", "value": "selected-student"},
                                   {"field": "student_name", "value": ROSTER[1].name}])
    with pytest.raises(ResourceNotFoundError):
        resolve_agent_spec(spec, ["id-a"], ROSTER)
    with pytest.raises(PlannerInvalidOutputError):
        resolve_agent_spec(spec, [], ROSTER)


def test_view_is_stable_between_preview_and_materialized_turn(portrait):
    view = agent_tool_view(portrait)
    assert set(view) == {"query_run_id", "metrics", "breakdown", "items", "portrait"}
    assert view["portrait"]["student_id"] == portrait.portrait.student_id
    assert view["items"][0]["student_name"] == portrait.items[0].student_name
    assert view["metrics"] == {card.key: card.value for card in portrait.summary.metrics}
    stored = portrait.model_copy(update={
        "conversation_id": "conversation", "turn_id": "turn",
        "summary": portrait.summary.model_copy(update={"data_as_of": "later", "scope_recomputed": True}),
    })
    assert agent_tool_view(stored) == view
    changed = stored.model_copy(update={"portrait": portrait.portrait.model_copy(update={"major": "新专业"})})
    assert agent_tool_view(changed) != view


def test_aggregate_view_suppresses_detail_and_ui_metadata(portrait):
    row = BreakdownRow(group_key={"publication_status": "submitted"}, label="已投稿", record_count=3, student_count=2)
    aggregate = portrait.model_copy(update={"applied_query": PaperQuerySpec(),
                                            "summary": portrait.summary.model_copy(update={"breakdown": [row]})})
    view = agent_tool_view(aggregate)
    assert view["items"] == [] and view["portrait"] is None
    assert view["breakdown"] == [{"group_key": row.group_key, "record_count": 3, "student_count": 2}]
    with pytest.raises(TeacherAgentError):
        agent_tool_view(ResultEnvelope(status="clarification_needed", clarification={"message": "请选择学生"}))


def test_render_uses_real_counts_and_allows_queried_years_and_names(portrait):
    spec = portrait.applied_query.model_copy(update={"time_range": PaperTimeRange(
        date_from="2025-09-01", date_to="2026-07-01")})
    panel = portrait.portrait.model_copy(update={"student_name": "李四"})
    result = portrait.model_copy(update={"query_run_id": "r1", "applied_query": spec, "portrait": panel})
    count = agent_tool_view(result)["metrics"]["paper_record_count"]
    text = "2025年/2026年，李四的论文记录为 [r1:paper_record_count]。建议结合投稿节奏进一步分析。"
    assert render_agent_analysis(text, [result]) == text.replace("[r1:paper_record_count]", f"{count} [r1]")
    followup = "2025 年度（沿用上一个年度）已发表的论文共 [r1:paper_published_record_count] 篇。"
    published = agent_tool_view(result)["metrics"]["paper_published_record_count"]
    assert render_agent_response(followup, [result]) == (
        f"2025 年度（沿用上一个年度）已发表的论文共 {published} [r1] 篇。", None)


@pytest.mark.parametrize("text", [
    "缺少引用", "[r1:invented_count]", "[unrelated:paper_record_count]", "参见 [S1] [r1]",
    "论文共 [r1:paper_record_count] 篇（5 篇）。",
    "涉及三十二人 [r1]", "共两篇 [r1]", "共５篇 [r1]", "2022年 [r1]",
    "共 ２.５％ [r1]", "three papers [r1]", "See paper_fake_count [r1]", "记录数为零 [r1]",
])
def test_render_rejects_unverified_quantities_and_references(portrait, text):
    with pytest.raises(PlannerInvalidOutputError):
        render_agent_analysis(text, [portrait.model_copy(update={"query_run_id": "r1"})])


def test_partial_analysis_preserves_six_metric_references_and_separates_notice(portrait):
    results = [portrait.model_copy(update={"query_run_id": run}) for run in ("before", "after")]
    claims = [
        f"{label}的{period}记录为 [{run}:{metric}]。"
        for label, metric in (("投稿", "paper_submitted_record_count"), ("录用", "paper_accepted_record_count"),
                              ("发表", "paper_published_record_count"))
        for period, run in (("本期", "after"), ("上期", "before"))
    ]
    samples = ["按 status_date 归属年度。", *claims[:2], "已按自然年各查一次；",
               *claims[2:4], "3 条均为 submitted。", *claims[4:]]
    answer, notice = render_agent_response("\n".join(samples), results)
    assert answer.splitlines() == [render_agent_analysis(claim, results) for claim in claims]
    assert notice == "部分分析未能核实，请以结果卡为准。"


def test_valid_model_sentences_keep_layout_and_have_no_notice(portrait):
    result = portrait.model_copy(update={"query_run_id": "r1"})
    text = "- 论文记录为 [r1:paper_record_count]。\n\n- 可结合投稿节奏分析。 [r1]"
    assert render_agent_response(text, [result]) == (render_agent_analysis(text, [result]), None)


@pytest.mark.parametrize("text", [
    "", "3 条均为 submitted。 [r1]", "[r1]", "结论尚待核实。\n[r1]",
    "包含两篇 [r1]。另一项为 [r1:unknown]。", "按 status_date 归属年度。已按自然年各查一次。",
])
def test_all_invalid_returns_only_a_backend_notice(portrait, text):
    result = portrait.model_copy(update={"query_run_id": "r1"})
    assert render_agent_response(text, [result]) == (None, "本次分析未能核实，请以结果卡为准。")


def test_status_date_requires_same_sentence_source_with_matching_query_field(portrait):
    period = PaperTimeRange(date_from="2025-01-01", date_to="2025-12-31")
    def run(ident, field):
        spec = PaperQuerySpec(time_range=period.model_copy(update={"field": field}))
        return portrait.model_copy(update={"query_run_id": ident, "applied_query": spec})

    results = [run("r1", "status_date"), run("r2", "submission_date")]
    valid = "按 `status_date` 归属年度 [r1]。"
    assert render_agent_response(valid, results) == (valid, None)
    for invalid in ("按 status_date 归属年度 [r2]。", "按 status_date 归属年度 [r1] [r2]。",
                    "按 latest_status_date 归属年度 [r1]。", "按 status_date 归属年度。"):
        assert render_agent_response(valid + invalid, results) == (valid, "部分分析未能核实，请以结果卡为准。")


def test_literal_count_requires_adjacent_correct_run_metric_value_and_unit(portrait):
    result = portrait.model_copy(update={"query_run_id": "r1"})
    count = agent_tool_view(result)["metrics"]["paper_record_count"]
    ref = "[r1:paper_record_count]"
    valid = f"共 {count} 篇 {ref}。"
    assert render_agent_response(valid, [result]) == (f"共 {count} 篇 [r1]。", None)
    for invalid in (f"共 {count} 篇 [r1]。", f"共 {count + 1} 篇 {ref}。", f"共 {count} 人 {ref}。",
                    f"{count} 条均为 submitted {ref}。", f"共 {count} 篇 [unknown:paper_record_count]。"):
        assert render_agent_response(invalid, [result])[0] is None
