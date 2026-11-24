"""Extract and statically validate initial-response sandboxed visual HTML blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contract import ResultEnvelope, VisualArtifact

MAX_VISUAL_HTML_BYTES = 16_384
MAX_VISUAL_TITLE_CHARS = 80

_VISUAL_BLOCK = re.compile(
    r"(?:^|\n)[ \t]*```visual-html(?P<meta>[^\n]*)\n(?P<body>.*?)\n[ \t]*```[ \t]*(?=\n|$)",
    re.DOTALL,
)
_TITLE_ATTR = re.compile(r"""title\s*=\s*(?:"([^"\n]{1,120})"|'([^'\n]{1,120})')""")

_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("external_url", re.compile(r"(?:https?|wss?|ftp)://", re.IGNORECASE)),
    ("protocol_relative_attr", re.compile(r"""(?:src|href|action)\s*=\s*["']\s*//""", re.IGNORECASE)),
    ("css_import", re.compile(r"@import\b", re.IGNORECASE)),
    ("script_src", re.compile(r"<script\b[^>]*\bsrc\s*=", re.IGNORECASE)),
    ("meta_tag", re.compile(r"<meta\b", re.IGNORECASE)),
    ("base_tag", re.compile(r"<base\b", re.IGNORECASE)),
    ("nested_embed", re.compile(r"<(?:iframe|object|embed|form)\b", re.IGNORECASE)),
    ("storage_or_cookie", re.compile(r"\b(?:document\.cookie|localStorage|sessionStorage|indexedDB)\b")),
    ("network_api", re.compile(r"\b(?:fetch\s*\(|(?:XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b)")),
    ("frame_escape", re.compile(r"\b(?:window\.(?:top|parent|opener|open)|top\.location|parent\.postMessage)\b")),
)


@dataclass(frozen=True, slots=True)
class ExtractedTurnOutput:
    prose: str
    visual: VisualArtifact | None
    dropped_reason: str | None = None


def _parse_title(meta: str) -> str:
    match = _TITLE_ATTR.search(meta or "")
    if not match:
        return ""
    title = (match.group(1) or match.group(2) or "").strip()
    return title[:MAX_VISUAL_TITLE_CHARS]


def extract_visual_artifact(raw_text: str, results: list[ResultEnvelope]) -> ExtractedTurnOutput:
    """Split optional `visual-html` fenced block from model text and validate it at the boundary."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return ExtractedTurnOutput(prose="", visual=None)

    matches = list(_VISUAL_BLOCK.finditer(raw_text))
    if not matches:
        return ExtractedTurnOutput(prose=raw_text.strip(), visual=None)

    prose = _VISUAL_BLOCK.sub("\n", raw_text).strip()
    if len(matches) > 1:
        return ExtractedTurnOutput(prose=prose, visual=None, dropped_reason="multiple_visual_blocks")

    ok_run_ids = [result.query_run_id for result in results if result.status == "ok" and result.query_run_id]
    if not ok_run_ids:
        return ExtractedTurnOutput(prose=prose, visual=None, dropped_reason="no_verified_results")

    match = matches[0]
    html = match.group("body").strip()
    if not html:
        return ExtractedTurnOutput(prose=prose, visual=None, dropped_reason="empty_html")

    if len(html) > MAX_VISUAL_HTML_BYTES or len(html.encode("utf-8")) > MAX_VISUAL_HTML_BYTES:
        return ExtractedTurnOutput(prose=prose, visual=None, dropped_reason="html_too_large")

    if "__INNOGRAD_DATA__" not in html:
        return ExtractedTurnOutput(prose=prose, visual=None, dropped_reason="missing_data_binding")

    for name, pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(html):
            return ExtractedTurnOutput(prose=prose, visual=None, dropped_reason=f"forbidden_pattern:{name}")

    artifact = VisualArtifact(
        title=_parse_title(match.group("meta")),
        html=html,
        source_run_ids=ok_run_ids,
    )
    return ExtractedTurnOutput(prose=prose, visual=artifact)
