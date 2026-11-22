import pytest
from sqlalchemy import bindparam, text

from app.db import Archive, Decision, QueryRun, StudentProfile, Submission, Supervision, User, Version, now, uid
from app.teacher_agent.api import _ConfiguredPlanner
from app.teacher_agent.contract import PAPER_STATUS_DATE_FIELD
from test_teacher_agent_conversations import CONVERSATIONS, ROOT, question
from test_teacher_agent_tools import agent, assert_persisted, clock, tool_result
from test_workflow import env, post


PUBLISHED = {"field": "publication_status", "operator": "eq", "value": "published"}


@pytest.fixture
def mixed_papers(env):
    app, _, ids = env
    teacher = ids["teacher"]
    with app.state.sessions.begin() as session:
        for name, degree, supervised in [
            ("accepted_only", "博士", True), ("submitted_only", "硕士", True), ("outside", "博士", False),
        ]:
            student = User(id=uid(), username=name, name=name, role="student", password_hash="unused")
            session.add(student)
            ids[name] = student.id
            session.flush()
            session.add(StudentProfile(user_id=student.id, number=name, degree=degree,
                                       year="2025级", major="合成专业", direction="合成方向"))
            if supervised:
                session.add(Supervision(teacher_id=teacher, student_id=student.id, valid_from=now()))

        for owner, status, title in [
            ("student1", "published", "合成甲"), ("student1", "published", "合成乙"),
            ("student2", "published", "合成丙"), ("accepted_only", "accepted", "发表过的研究"),
            ("submitted_only", "submitted", "合成投稿"), ("outside", "published", "组外论文"),
        ]:
            paper = Submission(id=uid(), student_id=ids[owner], reviewer_id=teacher,
                               kind="paper", status="archived")
            session.add(paper)
            session.flush()
            version = Version(id=uid(), submission_id=paper.id, number=1, snapshot={"form": {
                "title": title, "publication_status": status, PAPER_STATUS_DATE_FIELD[status]: "2026-05-01",
            }})
            session.add(version)
            session.flush()
            decision = Decision(id=uid(), version_id=version.id, reviewer_id=teacher, outcome="approved", opinion="")
            session.add(decision)
            session.flush()
            archive = Archive(id=uid(), version_id=version.id, decision_id=decision.id)
            session.add(archive)
            paper.current_version_id, paper.effective_archive_id = version.id, archive.id
    return env


def check_query(agent, view, card, *, filters, records, students, breakdown):
    assert view["metrics"]["paper_record_count"] == records
    assert view["metrics"]["paper_student_count"] == students
    assert view["breakdown"] == breakdown
    assert card["query_run_id"] == view["query_run_id"]
    assert card["applied_query"]["filters"] == filters
    with agent.sessions() as session:
        assert session.get(QueryRun, view["query_run_id"]).applied_query == card["applied_query"]
    replay = agent.teacher.get(f"{ROOT}/runs/{view['query_run_id']}")
    assert replay.status_code == 200, replay.text
    assert replay.json()["applied_query"] == card["applied_query"]


def group(field, value, records, students):
    return {"group_key": {field: value}, "record_count": records, "student_count": students}


@pytest.mark.parametrize(("message", "statuses", "group_by"), [
    ("统计已发表和已录用的论文", ["published", "accepted"], []),
    ("按发表状态统计论文", [], ["publication_status"]),
    ("只看已发表的论文", ["published"], []),
    ("按发表状态分组统计论文", [], ["publication_status"]),
], ids=["combined-statuses", "implicit-group", "published-only", "explicit-group"])
def test_configured_rules_publication_status(mixed_papers, message, statuses, group_by):
    app, clients, ids = mixed_papers
    teacher = clients["teacher"]
    created = post(teacher, CONVERSATIONS, {})
    assert created.status_code == 201, created.text
    response = post(teacher, f"{CONVERSATIONS}/{created.json()['id']}/turns", question(message, 0))
    assert response.status_code == 200, response.text
    card, = response.json()["results"]

    statement = text("""
        SELECT paper.id AS submission_id, paper.student_id, archive.id AS archive_id,
               version.id AS version_id, json_extract(version.snapshot, '$.form.title') AS title,
               json_extract(version.snapshot, '$.form.publication_status') AS publication_status
        FROM submissions AS paper
        JOIN supervisions AS supervision ON supervision.student_id = paper.student_id
        JOIN archives AS archive ON archive.id = paper.effective_archive_id
        JOIN submission_versions AS version ON version.id = archive.version_id
            AND version.submission_id = paper.id
        JOIN review_decisions AS decision ON decision.id = archive.decision_id
            AND decision.version_id = version.id AND decision.outcome = 'approved'
        WHERE paper.kind = 'paper' AND paper.status = 'archived'
            AND supervision.teacher_id = :teacher_id AND supervision.valid_from <= :as_of
            AND (supervision.valid_to IS NULL OR supervision.valid_to > :as_of)
            AND (:all_statuses OR json_extract(version.snapshot, '$.form.publication_status') IN :statuses)
    """).bindparams(bindparam("statuses", expanding=True))
    with app.state.sessions() as session:
        rows = session.execute(statement, {
            "teacher_id": ids["teacher"], "as_of": card["summary"]["data_as_of"],
            "all_statuses": not statuses, "statuses": statuses,
        }).mappings().all()

    expected_filters = []
    if statuses:
        expected_filters = [PUBLISHED] if len(statuses) == 1 else [
            {"field": "publication_status", "operator": "in", "value": statuses},
        ]
    expected_breakdown = []
    if group_by:
        for status in sorted({row["publication_status"] for row in rows}):
            records = [row for row in rows if row["publication_status"] == status]
            expected_breakdown.append(group("publication_status", status, len(records),
                                            len({row["student_id"] for row in records})))

    query = card["applied_query"]
    summary = card["summary"]
    metrics = {item["key"]: item["value"] for item in summary["metrics"]}
    actual = {
        "basis": query["basis"], "filters": query["filters"], "group_by": query["group_by"],
        "record_count": metrics["paper_record_count"], "student_count": metrics["paper_student_count"],
        "breakdown": [{key: item[key] for key in ("group_key", "record_count", "student_count")}
                      for item in summary["breakdown"]],
    }
    assert actual == {
        "basis": "current_effective_archives", "filters": expected_filters, "group_by": group_by,
        "record_count": len(rows), "student_count": len({row["student_id"] for row in rows}),
        "breakdown": expected_breakdown,
    }
    fields = rows[0].keys()
    assert sorted(tuple(item[field] for field in fields) for item in card["items"]) == sorted(
        tuple(row[field] for field in fields) for row in rows
    )


@pytest.mark.parametrize(("message", "spec", "metric", "unit", "breakdown"), [
    ("学生发表了多少篇论文？", {}, "paper_record_count", "篇", []),
    ("有多少名学生发表过论文？", {"distinct_subject": "student"}, "paper_student_count", "人", []),
    ("按学位分组，博士生和硕士生各发表了多少篇论文？", {"group_by": ["degree"]},
     "paper_record_count", "篇", [group("degree", "博士", 2, 1), group("degree", "硕士", 1, 1)]),
    ("已发表的论文有多少篇？", {}, "paper_record_count", "篇", []),
])
def test_missing_published_filter_is_applied_before_materializing(mixed_papers, agent, message, spec, metric, unit, breakdown):
    views = []

    def analyze(token):
        view = tool_result(agent.query(token, spec=spec))
        views.append(view)
        return f"共 {view['metric_refs'][metric]} {unit}。"

    response = agent.ask(analyze, message=message)
    assert response.status_code == 200, response.text
    body = response.json()
    view, = views
    card, = body["results"]
    check_query(agent, view, card, filters=[PUBLISHED], records=3, students=2, breakdown=breakdown)
    assert body["turn"]["resolved_query"] == card["applied_query"]
    assert card["applied_query"]["distinct_subject"] == spec.get("distinct_subject", "paper_record")
    if metric == "paper_student_count":
        assert {item["student_id"]: item["matched_record_count"] for item in card["items"]} == {
            agent.ids["student1"]: 2, agent.ids["student2"]: 1,
        }
    else:
        assert {item["title"] for item in card["items"]} == {"合成甲", "合成乙", "合成丙"}
    if not breakdown:
        count = 2 if unit == "人" else 3
        assert body["analysis"] == f"共 {count} [{view['query_run_id']}] {unit}。"
    assert_persisted(agent, turns=1, runs=1)


@pytest.mark.parametrize(("message", "spec", "records", "students", "breakdown"), [
    ("各种发表状态共有多少篇论文？", {}, 5, 4, []),
    ("各种发表状态共涉及多少名学生？", {"distinct_subject": "student"}, 5, 4, []),
    ("按发表状态分组统计论文", {"group_by": ["publication_status"]}, 5, 4,
     [group("publication_status", "accepted", 1, 1),
      group("publication_status", "published", 3, 2),
      group("publication_status", "submitted", 1, 1)]),
    ("按学位分组统计所有发表状态的论文篇数", {"group_by": ["degree"]}, 5, 4,
     [group("degree", "博士", 3, 2), group("degree", "硕士", 2, 2)]),
    ("标题包含‘发表过’的论文有多少篇？",
     {"filters": [{"field": "title", "operator": "contains", "value": "发表过"}]}, 1, 1, []),
    ("标题包含发表过的研究的论文有多少篇？",
     {"filters": [{"field": "title", "operator": "contains", "value": "发表过的研究"}]}, 1, 1, []),
    ("有多少篇论文已经录用但还没发表？",
     {"filters": [{"field": "publication_status", "operator": "eq", "value": "accepted"}]}, 1, 1, []),
    ("有哪些尚未发表过的论文？",
     {"filters": [{"field": "publication_status", "operator": "neq", "value": "published"}]}, 2, 2, []),
])
def test_publication_controls_keep_the_tool_scope(mixed_papers, agent, message, spec, records, students, breakdown):
    views = []

    def analyze(token):
        views.append(tool_result(agent.query(token, spec=spec)))
        return ""

    response = agent.ask(analyze, message=message)
    assert response.status_code == 200, response.text
    card, = response.json()["results"]
    view, = views
    check_query(agent, view, card, filters=spec.get("filters", []), records=records,
                students=students, breakdown=breakdown)


def test_rules_teacher_dialogue_groups_all_publication_statuses(mixed_papers, agent, monkeypatch):
    monkeypatch.setattr(_ConfiguredPlanner, "mode", property(lambda self: "rules"))

    grouped = agent.ask(lambda _: pytest.fail("rules mode must execute directly"),
                        message="按发表状态分组统计论文")
    published = agent.ask(lambda _: pytest.fail("rules mode must execute directly"),
                          key="published", message="只看已发表的论文", version=1)

    grouped_body = grouped.json()
    grouped_card = grouped_body["results"][0]
    assert grouped.status_code == published.status_code == 200
    assert grouped_card["applied_query"]["filters"] == []
    assert grouped_card["applied_query"]["group_by"] == ["publication_status"]
    grouped_metrics = {item["key"]: item["value"] for item in grouped_card["summary"]["metrics"]}
    assert grouped_metrics["paper_record_count"] == 5
    assert grouped_metrics["paper_student_count"] == 4
    assert [
        {key: item[key] for key in ("group_key", "record_count", "student_count")}
        for item in grouped_card["summary"]["breakdown"]
    ] == [
        group("publication_status", "accepted", 1, 1),
        group("publication_status", "published", 3, 2),
        group("publication_status", "submitted", 1, 1),
    ]

    published_card = published.json()["results"][0]
    assert published_card["applied_query"]["filters"] == [PUBLISHED]
    published_metrics = {item["key"]: item["value"] for item in published_card["summary"]["metrics"]}
    assert published_metrics["paper_record_count"] == 3
    assert published_metrics["paper_student_count"] == 2


def test_mixed_intent_keeps_independent_cards(mixed_papers, agent):
    views = []

    def analyze(token):
        views.append(tool_result(agent.query(token, spec={"group_by": ["publication_status"]})))
        views.append(tool_result(agent.query(token, spec={"operation": "list", "filters": [PUBLISHED]})))
        return ""

    response = agent.ask(analyze, message="先汇总所有发表状态，再看已发表的论文。")
    assert response.status_code == 200, response.text
    overview, listing = response.json()["results"]
    check_query(agent, views[0], overview, filters=[], records=5, students=4, breakdown=[
        group("publication_status", "accepted", 1, 1), group("publication_status", "published", 3, 2),
        group("publication_status", "submitted", 1, 1),
    ])
    check_query(agent, views[1], listing, filters=[PUBLISHED], records=3, students=2, breakdown=[])
    assert {item["title"] for item in views[1]["items"]} == {"合成甲", "合成乙", "合成丙"}
    assert_persisted(agent, turns=1, runs=2)


@pytest.mark.parametrize("separator", ["？", "。", "；", "\n"])
def test_separate_questions_keep_the_all_papers_card(mixed_papers, agent, separator):
    views = []

    def analyze(token):
        views.append(tool_result(agent.query(token, spec={"operation": "list", "filters": [PUBLISHED]})))
        views.append(tool_result(agent.query(token, spec={})))
        return ""

    response = agent.ask(analyze, message=f"学生发表了哪些论文{separator}所有论文总共有多少篇？")
    assert response.status_code == 200, response.text
    listing, total = response.json()["results"]
    check_query(agent, views[0], listing, filters=[PUBLISHED], records=3, students=2, breakdown=[])
    check_query(agent, views[1], total, filters=[], records=5, students=4, breakdown=[])


def test_negative_roster_question_does_not_force_positive_status(mixed_papers, agent):

    def analyze(token):
        tool_result(agent.query(token, spec={"distinct_subject": "student"}))
        return ""

    response = agent.ask(analyze, message="哪些学生没有发表过论文？")
    assert response.status_code == 200, response.text
    card, = response.json()["results"]
    assert card["applied_query"]["filters"] == []
