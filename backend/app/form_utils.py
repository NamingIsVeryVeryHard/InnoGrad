"""Shared boundary validation utilities for achievement submission forms.

All external inputs are validated at the API boundary (MLPS-3 D-12 / 8.1.4.4 d)
before entering version snapshots or downstream review/portrait pipelines.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MIN_YEAR = 1970
_MAX_YEAR = 2100


def _ensure_no_control_chars(value: str, label: str) -> None:
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{label}包含非法控制字符")


def clean_required_text(value: object, label: str, max_length: int) -> str:
    """Validate and strip a mandatory non-empty text field."""
    if value is None:
        raise ValueError(f"{label}不能为空")
    if not isinstance(value, str):
        raise TypeError(f"{label}格式无效")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label}不能为空")
    _ensure_no_control_chars(cleaned, label)
    if len(cleaned) > max_length:
        raise ValueError(f"{label}长度不能超过 {max_length} 个字符")
    return cleaned


def clean_optional_text(value: object, label: str, max_length: int) -> str:
    """Validate and strip an optional text field, returning empty string when absent."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{label}格式无效")
    cleaned = value.strip()
    _ensure_no_control_chars(cleaned, label)
    if len(cleaned) > max_length:
        raise ValueError(f"{label}长度不能超过 {max_length} 个字符")
    return cleaned


def validate_iso_date(value: object, label: str) -> str:
    """Validate a strict YYYY-MM-DD calendar date within an accepted year range."""
    cleaned = clean_required_text(value, label, max_length=10)
    if len(cleaned) != 10 or cleaned[4] != "-" or cleaned[7] != "-":
        raise ValueError(f"{label}格式无效，应为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label}不是有效日期，应为 YYYY-MM-DD") from exc
    if not (_MIN_YEAR <= parsed.year <= _MAX_YEAR):
        raise ValueError(f"{label}年份超出合理范围（{_MIN_YEAR}—{_MAX_YEAR}）")
    return parsed.isoformat()


def validate_http_url(value: object, label: str, max_length: int = 2000) -> str:
    """Validate an optional http/https URL without embedded credentials."""
    cleaned = clean_optional_text(value, label, max_length=max_length)
    if not cleaned:
        return ""
    parsed = urlsplit(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{label}必须是完整的 http:// 或 https:// 地址")
    if parsed.username or parsed.password:
        raise ValueError(f"{label}不能包含账号或口令凭据")
    return cleaned


def reject_unknown_fields(
    form: dict[str, Any], allowed: frozenset[str], kind_label: str
) -> None:
    """Reject unexpected keys to enforce strict input schema boundaries."""
    unknown = sorted(set(form) - allowed)
    if unknown:
        raise ValueError(f"{kind_label}包含未定义字段：{'、'.join(unknown)}")


def validate_form_dict(
    form: object,
    allowed_fields: frozenset[str],
    expected_version: int,
    form_label: str,
) -> dict[str, Any]:
    """Validate that a submitted form is a dict with allowed keys and version."""
    if not isinstance(form, dict):
        raise TypeError(f"{form_label}格式无效")
    reject_unknown_fields(form, allowed_fields, form_label)
    meta_ver = form.get("metadata_version")
    if meta_ver not in (None, expected_version, str(expected_version)):
        raise ValueError(f"{form_label}版本无效")
    return form


def compute_canonical_digest(payload: dict[str, Any]) -> str:
    """Compute a deterministic 64-char SHA-256 hex digest for canonical payloads."""
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def find_missing_text_fields(
    form: dict[str, Any], keys: tuple[str, ...] | list[str]
) -> list[str]:
    """Return field names whose string values are absent or blank."""
    return [
        key
        for key in keys
        if not isinstance(form.get(key), str) or not str(form[key]).strip()
    ]
