from app.material_pipeline import score_rules, to_bundle


def test_material_pipeline_score_and_bundle_contract():
    pages = [{
        "id": "doc-1:p1", "document_id": "doc-1", "number": 1,
        "text": "学号 S001；本学年完成了研究训练。", "method": "native",
        "quality": "accepted", "confidence": None,
    }]
    facts = {
        "studentId": "S001",
        "identityEvidence": [{"pageId": "doc-1:p1", "quote": "学号 S001"}],
        "observations": [{
            "id": "training-1", "metric": "training", "eventId": "training-1",
            "value": True, "date": "2026-01-20",
            "evidence": [{"pageId": "doc-1:p1", "quote": "本学年完成了研究训练"}],
        }],
    }
    context = {
        "student_id": "S001", "academic_year": 2025, "cutoff": "2026-09-01",
        "template": "balanced", "practice_id": "", "period": "2025—2026学年",
        "stage": "annual", "task_id": "task-1", "plans": [],
    }
    evaluation = score_rules(facts, context, pages)
    assert evaluation["ruleVersion"] == "annual-six-v1-trial"
    assert evaluation["dimensions"]["D2"]["score"] is None
    bundle = to_bundle(context, [{"document_id": "doc-1", "source_name": "报告.pdf", "sha256": "a" * 64, "kind": "annual"}], pages)
    assert bundle["schema_version"] == "1.0"
    assert bundle["student_id"] == "S001"
    assert bundle["documents"][0]["segments"][0]["segment_id"] == "doc-1:p1"
    assert bundle["input_context"]["sources"][0]["review_status"] == "pending"

