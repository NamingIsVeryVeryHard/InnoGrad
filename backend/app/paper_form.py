"""Validation and canonicalization for student paper metadata."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse


DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
AUTHOR_IDENTITIES = {
    "first_author",
    "co_first_author",
    "corresponding_author",
    "other_author",
}


def _clean_text(value, field, *, max_length=500):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}不能为空")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{field}过长")
    return value


def _normalize_authors(value):
    """Accept the UI's newline-separated names and the stored structured form."""
    if isinstance(value, str):
        names = [part.strip() for part in re.split(r"[\r\n,，、]+", value) if part.strip()]
        authors = [
            {"name": name, "order": index, "is_self": False}
            for index, name in enumerate(names, 1)
        ]
    elif isinstance(value, list):
        authors = []
        for index, author in enumerate(value, 1):
            if not isinstance(author, dict):
                raise ValueError("作者列表格式无效")
            name = _clean_text(author.get("name"), "作者姓名", max_length=200)
            order = author.get("order", index)
            if isinstance(order, bool) or not isinstance(order, int):
                raise ValueError("作者顺序必须是整数")
            authors.append(
                {"name": name, "order": order, "is_self": bool(author.get("is_self", False))}
            )
    else:
        raise ValueError("请填写完整作者列表")
    if not authors or len(authors) > 100:
        raise ValueError("请填写 1 至 100 名作者")
    orders = [author["order"] for author in authors]
    if sorted(orders) != list(range(1, len(authors) + 1)):
        raise ValueError("作者顺序必须从 1 开始且不能重复")
    return sorted(authors, key=lambda author: author["order"])


def _normalize_doi(value):
    if value is None or value == "":
        return ""
    value = _clean_text(value, "DOI", max_length=300)
    if value.lower().startswith("https://doi.org/"):
        value = value[len("https://doi.org/") :]
    if value.lower().startswith("http://doi.org/"):
        value = value[len("http://doi.org/") :]
    if not DOI_RE.fullmatch(value):
        raise ValueError("DOI格式无效，应为 10.xxxx/xxxxx")
    return value


def _normalize_url(value):
    if value is None or value == "":
        return ""
    value = _clean_text(value, "文章链接", max_length=2000)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("文章链接必须是完整的 http(s) 地址")
    return value


def canonicalize_paper_form(form):
    """Validate new paper metadata while retaining compatibility with old snapshots."""
    if not isinstance(form, dict):
        raise ValueError("论文表单格式无效")
    result = dict(form)
    metadata_keys = {"paper_metadata_version", "authors", "author_order", "author_identity", "article_url"}
    if not metadata_keys.intersection(result):
        return result
    if result.get("paper_metadata_version") not in (None, 2, "2"):
        raise ValueError("论文表单版本无效")

    authors = _normalize_authors(result.get("authors"))
    author_order = result.get("author_order")
    if isinstance(author_order, str) and author_order.strip().isdigit():
        author_order = int(author_order.strip())
    if isinstance(author_order, bool) or not isinstance(author_order, int):
        raise ValueError("请填写本人作者顺序")
    self_authors = [author for author in authors if author["order"] == author_order]
    if len(self_authors) != 1:
        raise ValueError("本人作者顺序不在作者列表中")
    for author in authors:
        author["is_self"] = author["order"] == author_order

    identity = result.get("author_identity")
    if identity not in AUTHOR_IDENTITIES:
        raise ValueError("请选择本人身份")
    doi = _normalize_doi(result.get("doi", ""))
    article_url = _normalize_url(result.get("article_url", ""))
    if not doi and not article_url:
        raise ValueError("DOI或文章链接至少填写一项")

    result.update(
        {
            "paper_metadata_version": 2,
            "authors": authors,
            "author_order": author_order,
            "author_identity": identity,
            "doi": doi,
            "article_url": article_url,
        }
    )
    canonical = {
        "title": str(result.get("title", "")).strip(),
        "authors": [{"name": a["name"], "order": a["order"]} for a in authors],
        "doi": doi.lower(),
        "article_url": article_url,
    }
    result["external_article_key"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result["external_article"] = canonical
    return result
