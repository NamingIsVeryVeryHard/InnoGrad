from uuid import uuid4

from app.paper_form import canonicalize_paper_form
from test_workflow import env, post


def test_paper_submission_freezes_external_article_metadata(env):
    _, clients, ids = env
    created = post(
        clients["student1"],
        "/api/v1/submissions",
        {"kind": "paper", "reviewer_id": ids["teacher"]},
    )
    assert created.status_code == 201, created.text
    ident = created.json()["id"]
    uploaded = clients["student1"].post(
        f"/api/v1/submissions/{ident}/files",
        files={"file": ("proof.pdf", b"%PDF-1.7 synthetic", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    draft = clients["student1"].patch(
        f"/api/v1/submissions/{ident}/draft",
        json={
            "expected_lock_version": 0,
            "form": {
                "paper_metadata_version": 2,
                "title": "External article",
                "authors": [
                    {"name": "Author A", "order": 1},
                    {"name": "Author B", "order": 2},
                ],
                "author_order": 2,
                "author_identity": "other_author",
                "publication_status": "submitted",
                "submission_date": "2026-11-20",
                "doi": "10.1234/example",
                "article_url": "https://example.org/paper",
                "contribution": "实验与分析",
            },
            "file_ids": [uploaded.json()["id"]],
            "file_roles": {uploaded.json()["id"]: "author_order_proof"},
        },
    )
    assert draft.status_code == 200, draft.text
    submitted = post(
        clients["student1"],
        f"/api/v1/submissions/{ident}/submit",
        {"expected_lock_version": draft.json()["lock_version"]},
    )
    assert submitted.status_code == 202, submitted.text
    snapshot = clients["student1"].get(f"/api/v1/submissions/{ident}").json()["versions"][0]["snapshot"]
    assert snapshot["form"]["authors"][1]["is_self"] is True
    assert snapshot["form"]["doi"] == "10.1234/example"
    assert len(snapshot["form"]["external_article_key"]) == 64
    assert snapshot["file_roles"][uploaded.json()["id"]] == "author_order_proof"
    assert clients["student1"].get(f"/api/v1/submissions/{ident}").json()["files"][0]["role"] == "author_order_proof"


def test_canonicalize_external_article_metadata():
    form = canonicalize_paper_form(
        {
            "paper_metadata_version": 2,
            "title": "  Structured Paper  ",
            "authors": [
                {"name": "Author A", "order": 1},
                {"name": "Author B", "order": 2},
            ],
            "author_order": "2",
            "author_identity": "corresponding_author",
            "doi": "https://doi.org/10.1234/example",
            "article_url": "https://example.org/paper",
        }
    )
    assert form["doi"] == "10.1234/example"
    assert form["authors"][1]["is_self"] is True
    assert form["external_article"]["authors"][0]["order"] == 1
    assert len(form["external_article_key"]) == 64


def test_canonicalize_rejects_missing_external_reference():
    form = {
        "paper_metadata_version": 2,
        "title": "Paper",
        "authors": [{"name": "Author", "order": 1}],
        "author_order": 1,
        "author_identity": "first_author",
    }
    try:
        canonicalize_paper_form(form)
    except ValueError as exc:
        assert "DOI或文章链接" in str(exc)
    else:
        raise AssertionError("missing DOI and article URL should be rejected")


def test_legacy_paper_form_remains_readable():
    form = canonicalize_paper_form(
        {
            "title": "Legacy paper",
            "contribution": "Experiments",
            "publication_status": "published",
            "publication_date": "2026-01-01",
        }
    )
    assert "authors" not in form
