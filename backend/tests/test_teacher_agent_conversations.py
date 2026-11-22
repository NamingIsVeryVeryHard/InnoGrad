import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import Idempotency, QueryConversation, QueryRun, Supervision, User
from test_workflow import env, post, submitted


ROOT = "/api/v1/teacher-agent"
CONVERSATIONS = ROOT + "/conversations"


def question(message, version):
    return {"expected_lock_version": version, "input": {"mode": "natural_language", "message": message}}


def test_visible_then_revoked_history_and_retries(env):
    app, clients, ids = env
    submission_id, _, _, submitted_response = submitted(env)
    decision = post(
        clients["teacher"],
        f"/api/v1/submissions/{submission_id}/decision",
        {
            "expected_lock_version": 2,
            "version_id": submitted_response["version_id"],
            "outcome": "approved",
            "opinion": "材料完整",
        },
    )
    assert decision.status_code == 200, decision.text
    from app.worker import drain
    assert drain(app.state.sessions) >= 1
    teacher = clients["teacher"]
    title = "演示学生一（student1）的材料"
    created = post(teacher, CONVERSATIONS, {"title": title}, "create")
    assert created.status_code == 201, created.text
    assert created.json()["title"] == "论文查询"
    url = f"{CONVERSATIONS}/{created.json()['id']}"
    overview_request = {"expected_lock_version": 0, "input": {"mode": "structured_spec", "spec": {"domain": "paper"}}}
    overview = post(teacher, url + "/turns", overview_request, "overview")
    assert overview.status_code == 200, overview.text
    assert overview.json()["result"]["pagination"]["total"] == 1
    portrait_request = question("查看演示学生一的画像", 1)
    portrait = post(teacher, url + "/turns", portrait_request, "portrait")
    assert portrait.status_code == 200, portrait.text
    assert portrait.json()["result"]["portrait"]["student_id"] == ids["student1"]
    run_url = f"{ROOT}/runs/{portrait.json()['result']['query_run_id']}"
    assert clients["manager"].get(url).status_code == 404
    assert clients["manager"].get(run_url).status_code == 404
    with app.state.sessions.begin() as session:
        conversation = session.get(QueryConversation, created.json()["id"])
        assert [turn["turn_index"] for turn in conversation.turns_json] == [1, 2]
        records = [
            conversation.active_query_spec, conversation.turns_json,
            *[row.applied_query for row in session.scalars(select(QueryRun))],
            *[row.response for row in session.scalars(select(Idempotency).where(
                Idempotency.operation.like("teacher_agent.%")))],
        ]
        stored = json.dumps(records, ensure_ascii=False)
        assert "演示学生一" not in stored and "student1" not in stored
        link = session.scalar(select(Supervision).where(Supervision.teacher_id == ids["teacher"],
                                                        Supervision.student_id == ids["student1"]))
        link.valid_to = "2000-01-01"
    history = teacher.get(url)
    assert history.status_code == 200, history.text
    for value in ("演示学生一", "student1", ids["student1"], portrait.json()["result"]["query_run_id"]):
        assert value not in history.text
    assert history.json()["latest_result"] is None
    assert history.json()["active_query"] is None
    assert history.json()["turns"][1]["access_revoked"]
    assert history.json()["turns"][1]["run_id"] is None and history.json()["turns"][1]["run_ids"] == []
    assert teacher.get(run_url).status_code == 404
    assert post(teacher, url + "/turns", portrait_request, "portrait").status_code == 404
    drill = {"expected_lock_version": 2, "input": {"mode": "drilldown_patch",
             "parent_run_id": portrait.json()["result"]["query_run_id"], "patch": {"operation": "list"}}}
    assert post(teacher, url + "/turns", drill).status_code == 404
    after = post(teacher, url + "/turns", overview_request, "overview")
    assert after.status_code == 200, after.text
    assert after.json()["result"]["summary"]["scope_recomputed"]
    assert after.json()["result"]["pagination"]["total"] == 0
    assert after.json()["result"]["turn_id"] == overview.json()["result"]["turn_id"]
    assert after.json()["turn"]["created_at"] == overview.json()["turn"]["created_at"]
    assert after.json()["result"]["summary"]["data_as_of"] != overview.json()["result"]["summary"]["data_as_of"]
    assert teacher.get(CONVERSATIONS).json()[0]["turn_count"] == 2


def test_same_key_race_and_conflicting_turns(env):
    app, clients, _ = env
    teacher = clients["teacher"]
    cid = post(teacher, CONVERSATIONS, {}).json()["id"]
    url = f"{CONVERSATIONS}/{cid}/turns"
    body = question("今年论文发表情况怎么样？", 0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: post(teacher, url, body, "same-key"), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["turn"]["id"] == responses[1].json()["turn"]["id"]
    assert responses[0].json()["result"]["applied_query"]["group_by"] == ["publication_status"]
    mismatch = post(teacher, url, question("只看博士", 1), "same-key")
    assert mismatch.status_code == 409
    body = question("只看博士", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda key: post(teacher, url, body, key), ["second", "third"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    followup = next(response for response in responses if response.status_code == 200).json()
    followup_query = followup["result"]["applied_query"]
    assert followup_query["time_range"] == {
        "from": "2026-01-01",
        "to": "2026-12-31",
        "field": "status_date",
    }
    assert followup_query["group_by"] == ["publication_status"]
    assert followup_query["filters"] == [{
        "field": "degree",
        "operator": "eq",
        "value": "博士",
    }]
    with app.state.sessions() as session:
        stored = session.get(QueryConversation, cid)
        assert stored.turn_count == stored.lock_version == len(stored.turns_json) == 2
        assert [item["turn_index"] for item in stored.turns_json] == [1, 2]
        assert session.scalar(select(func.count()).select_from(QueryRun)) == 2


def test_legacy_receipt_replays_only_within_its_conversation(env):
    app, clients, _ = env
    teacher = clients["teacher"]
    first, second = [post(teacher, CONVERSATIONS, {}).json()["id"] for _ in range(2)]
    paths = [f"{CONVERSATIONS}/{ident}/turns" for ident in (first, second)]
    body = {"expected_lock_version": 0, "input": {"mode": "structured_spec", "spec": {"domain": "paper"}}}
    one, two = [post(teacher, path, body, "turn").json() for path in paths]
    with app.state.sessions.begin() as session:
        receipt = session.scalar(select(Idempotency).where(Idempotency.operation == f"teacher_agent.turn/{first}"))
        receipt.response = {"turn_id": one["turn"]["id"], "query_run_id": one["turn"]["run_id"]}
    assert post(teacher, paths[0], body, "turn").json()["turn"]["id"] == one["turn"]["id"]
    with app.state.sessions.begin() as session:
        receipt = session.scalar(select(Idempotency).where(Idempotency.operation == f"teacher_agent.turn/{first}"))
        receipt.response = {"turn_id": two["turn"]["id"], "query_run_id": two["turn"]["run_id"]}
    assert post(teacher, paths[0], body, "turn").status_code == 404
    assert post(teacher, paths[1], body, "turn").json()["turn"]["id"] == two["turn"]["id"]


def test_history_hides_stale_embedded_run_references(env):
    app, clients, _ = env
    teacher = clients["teacher"]
    conversation_id = post(teacher, CONVERSATIONS, {}).json()["id"]
    path = f"{CONVERSATIONS}/{conversation_id}"
    body = {"expected_lock_version": 0, "input": {"mode": "structured_spec", "spec": {"domain": "paper"}}}
    turn = post(teacher, path + "/turns", body, "turn").json()["turn"]
    with app.state.sessions.begin() as session:
        session.delete(session.get(QueryRun, turn["run_id"]))
    history = teacher.get(path).json()
    historical_turn = history["turns"][0]
    assert historical_turn["id"] == turn["id"]
    assert historical_turn["run_id"] is None and historical_turn["run_ids"] == []
    assert history["latest_result"] is None and history["latest_results"] == []
    assert post(teacher, path + "/turns", body, "turn").status_code == 404


def test_structured_ambiguity_keeps_no_run_or_candidate_data_in_history(env):
    app, clients, ids = env
    with app.state.sessions.begin() as session:
        for username in ("student1", "student2"):
            session.get(User, ids[username]).name = "同名合成学生"
    teacher = clients["teacher"]
    conversation_id = post(teacher, CONVERSATIONS, {}).json()["id"]
    path = f"{CONVERSATIONS}/{conversation_id}"
    body = {"expected_lock_version": 0, "input": {"mode": "structured_spec", "spec": {
        "domain": "paper", "operation": "portrait",
        "filters": [{"field": "student_name", "value": "同名合成学生"}],
    }}}
    initial = post(teacher, path + "/turns", body, "ask").json()
    assert initial["results"] == initial["turn"]["run_ids"] == []
    assert {item["student_id"] for item in initial["result"]["clarification"]["student_candidates"]} == {
        ids["student1"], ids["student2"],
    }
    history = teacher.get(path).json()
    replay = post(teacher, path + "/turns", body, "ask").json()
    assert history["turns"][0]["id"] == replay["turn"]["id"] == initial["turn"]["id"]
    for view in (history["latest_result"], replay["result"]):
        assert view["status"] == "clarification_needed" and view["clarification"]["student_candidates"] == []
    with app.state.sessions() as session:
        stored = session.get(QueryConversation, conversation_id)
        assert stored.turns_json[0]["resolved_query_spec"] is None
        serialized = json.dumps(stored.turns_json, ensure_ascii=False)
        assert all(value not in serialized for value in ("同名合成学生", ids["student1"], ids["student2"]))
        assert session.scalar(select(func.count()).select_from(QueryRun)) == 0


def test_sessions_roles_no_store_and_archive(env):
    app, clients, _ = env
    for client, status in [(TestClient(app), 401), (clients["student1"], 403),
                           (clients["operator"], 403), (clients["manager"], 200)]:
        result = client.get(ROOT + "/schemas")
        assert result.status_code == status
        assert result.headers["Cache-Control"] == "no-store"
    teacher = clients["teacher"]
    cid = post(teacher, CONVERSATIONS, {}).json()["id"]
    url = f"{CONVERSATIONS}/{cid}"
    assert teacher.delete(url).status_code == 204
    assert teacher.get(CONVERSATIONS).json() == []
    assert post(teacher, url + "/turns", question("查看论文", 0)).status_code == 409
    teacher.headers.pop("X-CSRF-Token")
    denied = post(teacher, CONVERSATIONS, {})
    assert denied.status_code == 403
    assert denied.headers["Cache-Control"] == "no-store"
