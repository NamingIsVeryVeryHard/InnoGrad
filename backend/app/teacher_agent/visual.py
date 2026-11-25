"""Extract model HTML for the initial response's isolated visual sandbox."""

import re
from dataclasses import dataclass

from .contract import ResultEnvelope, VisualArtifact

MAX_VISUAL_HTML_BYTES = 16_384
MAX_VISUAL_TITLE_CHARS = 80

_VISUAL_BLOCK = re.compile(
    r"^[ \t]*```visual-(?P<kind>spec|html)\b(?P<extra>[^\n]*)"
    r"(?:\n(?P<body>.*?)(?:(?P<closed>^[ \t]*```[ \t]*\r?$)|\Z)|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_TITLE_ATTR = re.compile(r"""title\s*=\s*(?:"([^"\n]{1,120})"|'([^'\n]{1,120})')""")
_DATA_BINDING = re.compile(r"\bwindow\s*\.\s*__INNOGRAD_DATA__\b")

_FORBIDDEN_PATTERNS = (
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
    match = _TITLE_ATTR.search(meta)
    if not match:
        return ""
    return (match[1] or match[2]).strip()[:MAX_VISUAL_TITLE_CHARS]


def extract_visual_artifact(raw_text: str, results: list[ResultEnvelope]) -> ExtractedTurnOutput:
    matches = list(_VISUAL_BLOCK.finditer(raw_text))
    if not matches:
        return ExtractedTurnOutput(raw_text.strip(), None)

    prose = _VISUAL_BLOCK.sub("\n", raw_text).strip()
    if len(matches) > 1:
        return ExtractedTurnOutput(prose, None, "multiple_visual_blocks")

    match = matches[0]
    if match["kind"].lower() != "html" or not match["closed"]:
        return ExtractedTurnOutput(prose, None, "invalid_visual_fence")

    run_ids = [result.query_run_id for result in results if result.status == "ok" and result.query_run_id]
    if not run_ids:
        return ExtractedTurnOutput(prose, None, "no_verified_results")

    html = match["body"].strip()
    if not html:
        return ExtractedTurnOutput(prose, None, "empty_html")
    if len(html.encode("utf-8")) > MAX_VISUAL_HTML_BYTES:
        return ExtractedTurnOutput(prose, None, "html_too_large")
    if not _DATA_BINDING.search(html):
        return ExtractedTurnOutput(prose, None, "missing_data_binding")
    for name, pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(html):
            return ExtractedTurnOutput(prose, None, f"forbidden_pattern:{name}")

    return ExtractedTurnOutput(prose, VisualArtifact(
        title=_parse_title(match["extra"]),
        html=html,
        source_run_ids=run_ids,
    ))
