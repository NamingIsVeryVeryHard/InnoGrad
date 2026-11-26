"""Unified dispatch for achievement and cultivation submission form validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, cast

from . import paper_form
from .form_utils import find_missing_text_fields
from .research_project_form import (
    RESEARCH_PROJECT_REQUIRED_FIELDS,
    canonicalize_research_project_form,
    missing_research_project_fields,
)
from .software_copyright_form import (
    SOFTWARE_COPYRIGHT_REQUIRED_FIELDS,
    canonicalize_software_copyright_form,
    missing_software_copyright_fields,
)

SubmissionKind = Literal[
    "paper", "annual", "software_copyright", "research_project"
]
ACHIEVEMENT_KINDS: frozenset[str] = frozenset(
    {"paper", "software_copyright", "research_project"}
)

_PAPER_STATUS_DATE_KEY: dict[str, str] = {
    "submitted": "submission_date",
    "accepted": "acceptance_date",
    "published": "publication_date",
}
_DISPLAY_TITLE_CONFIG: dict[str, tuple[str, str]] = {
    "software_copyright": ("software_name", "软件著作权"),
    "research_project": ("project_name", "科研项目阶段成果"),
    "annual": ("title", "年度培养报告"),
    "paper": ("title", "论文成果"),
}


def _canonicalize_paper(form: dict[str, Any]) -> dict[str, Any]:
    fn = cast(
        Callable[[dict[str, Any]], dict[str, Any]],
        paper_form.canonicalize_paper_form,
    )
    return fn(form)


def _validate_paper_submit(form: dict[str, Any], file_ids: list[str]) -> dict[str, Any]:
    required = ("title", "contribution", "publication_status")
    if find_missing_text_fields(form, required):
        raise ValueError("缺少必填信息：" + "、".join(required))
    canonical = _canonicalize_paper(form)
    state = canonical["publication_status"]
    if state not in _PAPER_STATUS_DATE_KEY:
        raise ValueError("论文状态无效")
    date_key = _PAPER_STATUS_DATE_KEY[state]
    try:
        datetime.strptime(str(canonical.get(date_key, "")), "%Y-%m-%d")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"请填写有效的 {date_key}") from exc
    if not file_ids:
        raise ValueError("至少提供一份证明或报告附件")
    return canonical


def _validate_annual_submit(
    form: dict[str, Any],
    file_ids: list[str],
    task_requirements: dict[str, Any] | None,
) -> dict[str, Any]:
    extra = (task_requirements or {}).get("required_fields", [])
    required = list(dict.fromkeys(["summary", *extra]))
    if find_missing_text_fields(form, required):
        raise ValueError("缺少必填信息：" + "、".join(required))
    if not file_ids:
        raise ValueError("至少提供一份证明或报告附件")
    return form


def _validate_software_copyright_submit(
    form: dict[str, Any], file_ids: list[str]
) -> dict[str, Any]:
    canonical = canonicalize_software_copyright_form(form)
    if canonical["registration_status"] == "registered" and not file_ids:
        raise ValueError("已登记的软件著作权至少提供一份登记证书或证明附件")
    return canonical


def _validate_research_project_submit(
    form: dict[str, Any], file_ids: list[str]
) -> dict[str, Any]:
    return canonicalize_research_project_form(form, allowed_file_ids=set(file_ids))


def validate_submission_form(
    kind: str,
    form: dict[str, Any],
    file_ids: list[str],
    task_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and canonicalize a submission form right before freezing a version."""
    if kind == "paper":
        return _validate_paper_submit(form, file_ids)
    if kind == "annual":
        return _validate_annual_submit(form, file_ids, task_requirements)
    if kind == "software_copyright":
        return _validate_software_copyright_submit(form, file_ids)
    if kind == "research_project":
        return _validate_research_project_submit(form, file_ids)
    raise ValueError("不支持的材料类型")


def default_requirements_for_kind(kind: str) -> dict[str, Any]:
    """Return frozen default requirements metadata for non-task achievements."""
    if kind == "software_copyright":
        return {
            "version": "software-copyright-1",
            "kind": "software_copyright",
            "required_fields": list(SOFTWARE_COPYRIGHT_REQUIRED_FIELDS),
            "review_policy": "manual_all",
        }
    if kind == "research_project":
        return {
            "version": "research-project-1",
            "kind": "research_project",
            "required_fields": list(RESEARCH_PROJECT_REQUIRED_FIELDS),
            "attachment_required": False,
            "review_policy": "manual_all",
        }
    return {"version": "paper-1", "review_policy": "manual_all"}


def missing_required_fields(
    form: dict[str, Any], requirements: dict[str, Any]
) -> list[str]:
    """Check frozen form completeness across all submission kinds for Agent review."""
    kind = requirements.get("kind")
    if kind == "software_copyright" or "software_name" in form:
        return missing_software_copyright_fields(form)
    if kind == "research_project" or "project_name" in form:
        return missing_research_project_fields(form)
    required = requirements.get("required_fields") or (
        ["title", "contribution", "publication_status"]
        if "title" in form
        else ["summary"]
    )
    return find_missing_text_fields(form, required)


def submission_display_title(kind: str, form: dict[str, Any]) -> str:
    """Return a consistent display title across submission kinds."""
    primary_key, fallback = _DISPLAY_TITLE_CONFIG.get(kind, ("title", "论文成果"))
    title = form.get(primary_key) or form.get("title") or fallback
    return str(title)
