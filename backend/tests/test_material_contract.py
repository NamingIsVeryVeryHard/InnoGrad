from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.agent import Check
from app.material_rules import freeze_requirements, validate_rule_checks
from app.db import AIJob, File, Version
from test_workflow import env, paper, post


def test_submission_freezes_rules_files_identity_and_rerun_hash(env):
    app, clients, ids = env
    ident, fid, draft = paper(env)
    draft.update(expected_lock_version=1, file_roles={fid: "paper_fulltext"})
    assert clients["student1"].patch(f"/api/v1/submissions/{ident}/draft", json=draft).status_code == 200
    submitted = post(clients["student1"], f"/api/v1/submissions/{ident}/submit",
                     {"expected_lock_version": 2}).json()
    with app.state.sessions.begin() as session:
        version = session.get(Version, submitted["version_id"])
        snapshot = deepcopy(version.snapshot)
        original = session.get(AIJob, submitted["ai_job_id"])
        digest = original.input_hash
        session.get(File, fid).role = "other"
    rerun = post(clients["teacher"], f"/api/v1/submissions/{ident}/ai-jobs",
                 {"version_id": submitted["version_id"]})
    assert rerun.status_code == 202
    with app.state.sessions() as session:
        again = session.get(AIJob, rerun.json()["id"])
        assert again.input_hash == digest
        assert again.input_pack["files"][0]["role"] == "paper_fulltext"
    assert snapshot["student"]["name"]
    assert len(snapshot["requirements"]["review_rules"]) == 6
    assert snapshot["files"][0]["sha256"]


def test_rule_manifest_is_frozen_and_not_applicable_cannot_skip_paper():
    requirements = freeze_requirements("paper")
    snapshot = {"requirements": requirements, "kind": "paper", "form": {"publication_status": "accepted"}}
    before = deepcopy(requirements)
    assert freeze_requirements("paper", requirements) == before
    checks = [Check(rule_id=rule["id"], conclusion="not_applicable", severity="info", explanation="skip")
              for rule in requirements["review_rules"]]
    with pytest.raises(ValueError, match="RULE_INCOMPLETE"):
        validate_rule_checks(checks, snapshot, [])


def test_missing_rule_and_wrong_role_rejected():
    requirements = freeze_requirements("annual")
    snapshot = {"requirements": requirements, "kind": "annual", "form": {}, "references": []}
    checks = [Check(rule_id=rule["id"], conclusion="compliant", severity="info", explanation="ok",
                    evidence=[{"file_id": "f", "paragraph_id": "p-1", "quote": "work"}])
              for rule in requirements["review_rules"]]
    with pytest.raises(ValueError, match="RULE_INCOMPLETE"):
        validate_rule_checks(checks[:-1], snapshot, [])
    with pytest.raises(ValueError, match="EVIDENCE_INVALID"):
        validate_rule_checks(checks, snapshot, [{"id": "f", "role": "other"}])
    validate_rule_checks(checks, snapshot, [{"id": "f", "role": "annual_report"}])
