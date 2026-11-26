"""Validation and canonicalization for research project stage achievement forms (Issue #26)."""

from __future__ import annotations

from typing import Any

from .form_utils import (
    clean_optional_text,
    clean_required_text,
    compute_canonical_digest,
    find_missing_text_fields,
    reject_unknown_fields,
    validate_form_dict,
    validate_http_url,
    validate_iso_date,
)

RESEARCH_PROJECT_METADATA_VERSION = 1
MAX_LINKED_ARTIFACTS = 20
RESEARCH_PROJECT_REQUIRED_FIELDS: tuple[str, ...] = (
    "project_name",
    "student_role",
    "stage_deliverables",
    "completion_date",
)

STUDENT_ROLE_LABELS: dict[str, str] = {
    "lead": "项目/子课题负责人",
    "core_member": "核心成员",
    "participant": "参与成员",
    "other": "其他",
}

ARTIFACT_TYPE_LABELS: dict[str, str] = {
    "experiment_report": "实验报告",
    "dataset": "数据集",
    "code": "代码",
    "prototype": "原型",
}

_ALLOWED_FIELDS = frozenset(
    {
        "metadata_version",
        "title",
        *RESEARCH_PROJECT_REQUIRED_FIELDS,
        "role_description",
        "linked_artifacts",
        "period",
        "research_project_key",
    }
)
_ALLOWED_ARTIFACT_FIELDS = frozenset(
    {"artifact_type", "name", "url", "file_id", "description"}
)


def _normalize_role(role_raw: object, detail_raw: object) -> tuple[str, str]:
    if not isinstance(role_raw, str) or role_raw not in STUDENT_ROLE_LABELS:
        raise ValueError("请选择有效的学生本人角色")
    if role_raw == "other":
        detail = clean_required_text(detail_raw, "其他角色说明", 100)
    else:
        detail = clean_optional_text(detail_raw, "角色补充说明", 100)
    return role_raw, detail


def _normalize_artifact(
    item: object, allowed_file_ids: set[str] | None
) -> dict[str, str]:
    """Validate one optional linked artifact (experiment report, dataset, code, prototype)."""
    if not isinstance(item, dict):
        raise TypeError("关联材料条目格式无效")
    reject_unknown_fields(item, _ALLOWED_ARTIFACT_FIELDS, "关联材料")
    artifact_type = item.get("artifact_type")
    if not isinstance(artifact_type, str) or artifact_type not in ARTIFACT_TYPE_LABELS:
        raise ValueError("关联材料类型必须是实验报告、数据集、代码或原型")
    name = clean_required_text(item.get("name"), "关联材料名称", 200)
    url = validate_http_url(item.get("url"), "关联材料链接")
    file_id = clean_optional_text(item.get("file_id"), "关联附件 ID", 64)
    if file_id and allowed_file_ids is not None and file_id not in allowed_file_ids:
        raise ValueError("关联附件必须属于本次提交已上传的文件")
    description = clean_optional_text(item.get("description"), "关联材料说明", 500)
    return {
        "artifact_type": artifact_type,
        "name": name,
        "url": url,
        "file_id": file_id,
        "description": description,
    }


def _normalize_artifacts(
    raw: object, allowed_file_ids: set[str] | None
) -> list[dict[str, str]]:
    """Linked artifacts are explicitly optional per Issue #26."""
    if raw is None or raw == "":
        return []
    if not isinstance(raw, list):
        raise TypeError("关联材料列表格式无效")
    if len(raw) > MAX_LINKED_ARTIFACTS:
        raise ValueError(f"单次最多关联 {MAX_LINKED_ARTIFACTS} 项材料")
    return [_normalize_artifact(item, allowed_file_ids) for item in raw]


def canonicalize_research_project_form(
    form: object, allowed_file_ids: set[str] | None = None
) -> dict[str, Any]:
    """Validate and canonicalize a research project stage achievement form."""
    data = validate_form_dict(
        form, _ALLOWED_FIELDS, RESEARCH_PROJECT_METADATA_VERSION, "科研项目阶段成果表单"
    )
    project_name = clean_required_text(data.get("project_name"), "项目或课题名称", 200)
    student_role, role_description = _normalize_role(
        data.get("student_role"), data.get("role_description")
    )
    deliverables = clean_required_text(
        data.get("stage_deliverables"), "本阶段完成的具体事项", 4000
    )
    completion_date = validate_iso_date(data.get("completion_date"), "完成时间")
    artifacts = _normalize_artifacts(data.get("linked_artifacts"), allowed_file_ids)
    period = clean_optional_text(data.get("period"), "所属学年", 40)
    canonical_key = compute_canonical_digest(
        {
            "project_name": project_name,
            "student_role": student_role,
            "completion_date": completion_date,
            "stage_deliverables": deliverables,
        }
    )
    result: dict[str, Any] = {
        "metadata_version": RESEARCH_PROJECT_METADATA_VERSION,
        "title": project_name,
        "project_name": project_name,
        "student_role": student_role,
        "role_description": role_description,
        "stage_deliverables": deliverables,
        "completion_date": completion_date,
        "linked_artifacts": artifacts,
        "research_project_key": canonical_key,
    }
    if period:
        result["period"] = period
    return result


def missing_research_project_fields(form: dict[str, Any]) -> list[str]:
    """Return missing required field keys for frozen research project checks."""
    missing = find_missing_text_fields(form, RESEARCH_PROJECT_REQUIRED_FIELDS)
    if form.get("student_role") == "other":
        missing.extend(find_missing_text_fields(form, ("role_description",)))
    return missing
