"""Validation and canonicalization for competition awards and academic exchange forms."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from urllib.parse import urlparse


COMPETITION_METADATA_VERSION = 1
EXCHANGE_METADATA_VERSION = 1

PARTICIPATION_MODES = ("attend", "talk", "poster", "practice_task")
PARTICIPATION_MODE_LABELS = {
    "attend": "参会",
    "talk": "作报告",
    "poster": "展示海报",
    "practice_task": "承担具体实践任务",
}


def _clean_text(value, field, *, required=True, max_length=500):
    if value is None or (isinstance(value, str) and not value.strip()):
        if not required:
            return ""
        raise ValueError(f"{field}不能为空")
    if not isinstance(value, str):
        raise ValueError(f"{field}格式无效")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise ValueError(f"{field}过长")
    return cleaned


def _normalize_date(value, field, *, required=True):
    if value is None or (isinstance(value, str) and not value.strip()):
        if not required:
            return ""
        raise ValueError(f"请填写有效的{field}（YYYY-MM-DD）")
    if not isinstance(value, str):
        raise ValueError(f"请填写有效的{field}（YYYY-MM-DD）")
    text = value.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"请填写有效的{field}（YYYY-MM-DD）") from exc


def _normalize_url(value, field):
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    cleaned = _clean_text(value, field, max_length=2000)
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field}必须是完整的 http(s) 地址")
    return cleaned


def _normalize_members(value):
    """Accept newline/comma-separated names, string lists, or structured member dicts."""
    if isinstance(value, str):
        names = [
            part.strip() for part in re.split(r"[\r\n,，、]+", value) if part.strip()
        ]
        members = [
            {"name": name, "order": index} for index, name in enumerate(names, 1)
        ]
    elif isinstance(value, list):
        members = []
        for index, item in enumerate(value, 1):
            if isinstance(item, str):
                name = _clean_text(item, "成员姓名", max_length=200)
                order = index
            elif isinstance(item, dict):
                name = _clean_text(item.get("name"), "成员姓名", max_length=200)
                order = item.get("order", index)
                if isinstance(order, bool) or not isinstance(order, int):
                    raise ValueError("团队成员顺序必须是整数")
                entry = {"name": name, "order": order}
                if "is_self" in item:
                    entry["is_self"] = bool(item["is_self"])
                members.append(entry)
                continue
            else:
                raise ValueError("团队成员格式无效")
            members.append({"name": name, "order": order})
    else:
        raise ValueError("请填写团队成员")
    if not members or len(members) > 100:
        raise ValueError("请填写 1 至 100 名团队成员")
    orders = [member["order"] for member in members]
    if sorted(orders) != list(range(1, len(members) + 1)):
        raise ValueError("团队成员顺序必须从 1 开始且不能重复")
    return sorted(members, key=lambda member: member["order"])


def _digest(canonical):
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def canonicalize_competition_form(form):
    """Validate and normalize competition award metadata."""
    if not isinstance(form, dict):
        raise ValueError("竞赛表单格式无效")
    if form.get("competition_metadata_version") not in (
        None,
        COMPETITION_METADATA_VERSION,
        str(COMPETITION_METADATA_VERSION),
    ):
        raise ValueError("竞赛表单版本无效")
    result = dict(form)
    raw_name = (
        form.get("competition_name")
        if form.get("competition_name") not in (None, "")
        else form.get("title")
    )
    competition_name = _clean_text(raw_name, "竞赛名称", max_length=300)
    organizer = _clean_text(form.get("organizer"), "主办方", max_length=300)
    award_level = _clean_text(form.get("award_level"), "奖项", max_length=200)
    award_date = _normalize_date(form.get("award_date"), "获奖日期")
    team_members = _normalize_members(form.get("team_members"))
    my_role = _clean_text(form.get("my_role"), "本人角色", max_length=300)
    publicity_url = _normalize_url(form.get("publicity_url", ""), "公示链接")
    description = _clean_text(
        form.get("description", ""), "补充说明", required=False, max_length=2000
    )

    result.update(
        {
            "competition_metadata_version": COMPETITION_METADATA_VERSION,
            "title": competition_name,
            "competition_name": competition_name,
            "organizer": organizer,
            "award_level": award_level,
            "award_date": award_date,
            "team_members": team_members,
            "team_size": len(team_members),
            "is_team": len(team_members) > 1,
            "my_role": my_role,
            "publicity_url": publicity_url,
            "description": description,
            "competition_key": _digest(
                {
                    "competition_name": competition_name,
                    "organizer": organizer,
                    "award_level": award_level,
                    "award_date": award_date,
                    "publicity_url": publicity_url,
                }
            ),
        }
    )
    return result


def canonicalize_exchange_form(form):
    """Validate and normalize academic exchange metadata."""
    if not isinstance(form, dict):
        raise ValueError("学术交流表单格式无效")
    if form.get("exchange_metadata_version") not in (
        None,
        EXCHANGE_METADATA_VERSION,
        str(EXCHANGE_METADATA_VERSION),
    ):
        raise ValueError("学术交流表单版本无效")
    result = dict(form)
    raw_name = (
        form.get("activity_name")
        if form.get("activity_name") not in (None, "")
        else form.get("title")
    )
    activity_name = _clean_text(raw_name, "会议或实践项目名称", max_length=300)
    activity_date = _normalize_date(form.get("activity_date"), "活动日期")
    end_date = _normalize_date(form.get("end_date", ""), "结束日期", required=False)
    if end_date and end_date < activity_date:
        raise ValueError("结束日期不能早于活动日期")

    participation_mode = form.get("participation_mode")
    if participation_mode not in PARTICIPATION_MODES:
        raise ValueError(
            "请选择有效的参与方式（参会、作报告、展示海报或承担具体实践任务）"
        )

    location_or_organizer = _clean_text(
        form.get("location_or_organizer", ""),
        "主办单位或地点",
        required=False,
        max_length=300,
    )
    presentation_label = (
        "报告题目" if participation_mode == "talk" else "海报题目"
    )
    presentation_title = (
        _clean_text(
            form.get("presentation_title", ""),
            presentation_label,
            required=True,
            max_length=300,
        )
        if participation_mode in ("talk", "poster")
        else ""
    )
    practice_task_description = (
        _clean_text(
            form.get("practice_task_description", ""),
            "承担的具体实践任务",
            required=True,
            max_length=2000,
        )
        if participation_mode == "practice_task"
        else ""
    )
    participation_summary = _clean_text(
        form.get("participation_summary", ""),
        "参与说明",
        required=False,
        max_length=2000,
    )
    reference_url = _normalize_url(form.get("reference_url", ""), "活动链接")

    result.update(
        {
            "exchange_metadata_version": EXCHANGE_METADATA_VERSION,
            "title": activity_name,
            "activity_name": activity_name,
            "activity_date": activity_date,
            "end_date": end_date,
            "participation_mode": participation_mode,
            "participation_mode_label": PARTICIPATION_MODE_LABELS[participation_mode],
            "location_or_organizer": location_or_organizer,
            "presentation_title": presentation_title,
            "practice_task_description": practice_task_description,
            "participation_summary": participation_summary,
            "reference_url": reference_url,
            "exchange_key": _digest(
                {
                    "activity_name": activity_name,
                    "activity_date": activity_date,
                    "participation_mode": participation_mode,
                    "presentation_title": presentation_title,
                    "practice_task_description": practice_task_description,
                }
            ),
        }
    )
    return result
