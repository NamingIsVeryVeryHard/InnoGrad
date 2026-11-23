import pytest

from app.teacher_agent.contract import BreakdownRow, METRIC_CATALOG, MetricCard, PaperQuerySpec, ResultEnvelope
from app.teacher_agent.privacy import render_agent_response


def paper_result(run_id, count, student_count, *, group_counts=None):
    grouped = group_counts is not None
    metric = "paper_published_record_count"
    definition = METRIC_CATALOG[metric]
    return ResultEnvelope(
        query_run_id=run_id,
        applied_query=PaperQuerySpec(
            operation="aggregate" if grouped else "list",
            group_by=["degree"] if grouped else [],
            filters=[{"field": "publication_status", "value": "published"}],
        ),
        summary={
            "headline": f"当前有效归档中有 {count} 条符合条件的论文申报记录，涉及 {student_count} 名学生。",
            "metrics": [MetricCard(key=metric, label=definition.label, value=count,
                                   unit=definition.unit, subject=definition.subject)],
            "breakdown": [
                BreakdownRow(group_key={"degree": degree}, label=degree, record_count=papers, student_count=students)
                for degree, papers, students in group_counts or ()
            ],
            "data_as_of": "2026-11-20",
            "basis": "current_effective_archives",
            "scope_student_count": 4,
            "notice": "",
        },
        pagination={"page": 1, "page_size": 50, "total": count, "has_more": False},
    )


@pytest.mark.parametrize(("group_counts", "count", "students", "text"), [
    ([("博士", 5, 2), ("硕士", 1, 1)], 6, 3,
     "博士发表了 [overview:paper_published_record_count] 篇。硕士发表了 [overview:paper_published_record_count] 篇。"),
    ([("博士", 6, 2)], 6, 2, "博士发表了 6 篇 [overview:paper_published_record_count]。"),
    ([], 0, 0, "博士发表了 [overview:paper_published_record_count] 篇。"),
])
def test_grouped_analysis_guides_to_card_even_when_total_matches_a_group(group_counts, count, students, text):
    overview = paper_result("overview", count, students, group_counts=group_counts)

    assert render_agent_response(text, [overview]) == ("各组统计请查看分组结果卡 [overview]。", None)


def test_mixed_analysis_keeps_the_list_total_with_its_card():
    overview = paper_result("overview", 6, 3, group_counts=[("博士", 5, 2), ("硕士", 1, 1)])
    listing = paper_result("listing", 2, 1)
    text = (
        "博士发表了 [overview:paper_published_record_count] 篇。"
        "硕士发表了 [listing:paper_published_record_count] 篇。"
        "硕士名单匹配 [listing:paper_published_record_count] 篇。"
    )

    assert render_agent_response(text, [overview, listing]) == (
        "各组统计请查看分组结果卡 [overview]。\n"
        "未分组查询 [listing]：当前有效归档中有 2 条符合条件的论文申报记录，涉及 1 名学生。",
        None,
    )
