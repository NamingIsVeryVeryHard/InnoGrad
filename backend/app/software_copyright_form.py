"""Validation and canonicalization for software copyright achievement submissions (Issue #25)."""

from __future__ import annotations

import re
from typing import Any

from .form_utils import (
    clean_optional_text,
    clean_required_text,
    compute_canonical_digest,
    find_missing_text_fields,
    validate_form_dict,
    validate_iso_date,
)

SOFTWARE_COPYRIGHT_METADATA_VERSION = 1
MAX_COPYRIGHT_HOLDERS = 50
SOFTWARE_COPYRIGHT_REQUIRED_FIELDS: tuple[str, ...] = (
    "software_name",
    "version",
    "copyright_holders",
    "development_work",
    "registration_status",
)
REGISTRATION_STATUS_LABELS: dict[str, str] = {
    "unregistered": "未登记",
    "applying": "申请登记中",
    "registered": "已登记",
}

_TEXT_REQUIRED_KEYS: tuple[str, ...] = (
    "software_name",
    "version",
    "development_work",
    "registration_status",
)
_REGISTERED_EXTRA_KEYS: tuple[str, ...] = ("registration_number", "registration_date")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,49}$")
_REGISTRATION_NUMBER_RE = re.compile(
    r"^[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\-/._]{3,63}$"
)
_HOLDER_SPLIT_RE = re.compile(r"[\r\n,，、;；]+")
_ALLOWED_FIELDS = frozenset(
    {
        "metadata_version",
        "title",
        *SOFTWARE_COPYRIGHT_REQUIRED_FIELDS,
        *_REGISTERED_EXTRA_KEYS,
        "period",
        "software_copyright_key",
    }
)


def _normalize_copyright_holders(value: object) -> list[str]:
    """Accept newline/comma-separated names or a JSON string list and deduplicate."""
    if value is None:
        raise ValueError("请填写著作权人")
    raw_items: list[object]
    if isinstance(value, str):
        raw_items = [part.strip() for part in _HOLDER_SPLIT_RE.split(value) if part.strip()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise TypeError("著作权人格式无效")
    holders: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        holder = clean_required_text(item, "著作权人", max_length=100)
        if holder not in seen:
            seen.add(holder)
            holders.append(holder)
    if not holders or len(holders) > MAX_COPYRIGHT_HOLDERS:
        raise ValueError(f"著作权人数量须在 1 至 {MAX_COPYRIGHT_HOLDERS} 之间")
    return holders


def _validate_version(value: object) -> str:
    cleaned = clean_required_text(value, "版本号", max_length=50)
    if not _VERSION_RE.fullmatch(cleaned):
        raise ValueError("版本号格式无效，仅允许字母、数字及 . _ + -（如 V1.0）")
    return cleaned


def _normalize_registration_details(
    status: str, number_raw: object, date_raw: object
) -> tuple[str, str]:
    """Enforce conditional requirement: number and date are required iff registered."""
    if status == "registered":
        reg_number = clean_required_text(number_raw, "登记号", max_length=64)
        if not _REGISTRATION_NUMBER_RE.fullmatch(reg_number):
            raise ValueError("登记号格式无效，请填写 4 至 64 位有效登记号")
        reg_date = validate_iso_date(date_raw, "登记日期")
        return reg_number, reg_date
    extra_number = clean_optional_text(number_raw, "登记号", max_length=64)
    extra_date = clean_optional_text(date_raw, "登记日期", max_length=10)
    if extra_number or extra_date:
        raise ValueError("仅登记状态为已登记时才填写登记号和登记日期")
    return "", ""


def canonicalize_software_copyright_form(form: object) -> dict[str, Any]:
    """Validate and canonicalize a software copyright submission form."""
    data = validate_form_dict(
        form, _ALLOWED_FIELDS, SOFTWARE_COPYRIGHT_METADATA_VERSION, "软件著作权表单"
    )
    software_name = clean_required_text(data.get("software_name"), "软件全称", 200)
    version = _validate_version(data.get("version"))
    holders = _normalize_copyright_holders(data.get("copyright_holders"))
    development_work = clean_required_text(
        data.get("development_work"), "学生承担的开发工作", 4000
    )
    status = data.get("registration_status")
    if not isinstance(status, str) or status not in REGISTRATION_STATUS_LABELS:
        raise ValueError("请选择有效的登记状态（未登记、申请登记中或已登记）")
    reg_number, reg_date = _normalize_registration_details(
        status, data.get("registration_number"), data.get("registration_date")
    )
    period = clean_optional_text(data.get("period"), "所属学年", 40)
    canonical_key = compute_canonical_digest(
        {
            "software_name": software_name,
            "version": version.lower(),
            "copyright_holders": holders,
            "registration_number": reg_number.lower(),
        }
    )
    result: dict[str, Any] = {
        "metadata_version": SOFTWARE_COPYRIGHT_METADATA_VERSION,
        "title": software_name,
        "software_name": software_name,
        "version": version,
        "copyright_holders": holders,
        "development_work": development_work,
        "registration_status": status,
        "registration_number": reg_number,
        "registration_date": reg_date,
        "software_copyright_key": canonical_key,
    }
    if period:
        result["period"] = period
    return result


def missing_software_copyright_fields(form: dict[str, Any]) -> list[str]:
    """Return missing required field keys for frozen software copyright checks."""
    missing = find_missing_text_fields(form, _TEXT_REQUIRED_KEYS)
    holders = form.get("copyright_holders")
    if not isinstance(holders, list) or not holders:
        missing.append("copyright_holders")
    if form.get("registration_status") == "registered":
        missing.extend(find_missing_text_fields(form, _REGISTERED_EXTRA_KEYS))
    return missing
