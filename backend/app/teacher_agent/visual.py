import re

from pydantic import ValidationError

from .contract import ResultEnvelope, VisualSpec
from .privacy import safe_language


_VISUAL_BLOCK = re.compile(
    r"^[ \t]*```visual-(?P<kind>spec|html)\b(?P<extra>[^\n]*)"
    r"(?:\n(?P<body>.*?)(?:(?P<closed>^[ \t]*```[ \t]*\r?$)|\Z)|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def split_visual_response(text: str) -> tuple[str, str | None]:
    matches = list(_VISUAL_BLOCK.finditer(text))
    body = None
    if len(matches) == 1:
        match = matches[0]
        if match["kind"] == "spec" and not match["extra"].strip() and match["closed"]:
            body = match["body"]
    return _VISUAL_BLOCK.sub("", text).strip(), body


def verified_visual_spec(body: str | None, results: list[ResultEnvelope]) -> VisualSpec | None:
    if not body or not results:
        return None
    try:
        spec = VisualSpec.model_validate_json(body)
    except ValidationError:
        return None
    run_ids = {result.query_run_id for result in results if result.status == "ok"}
    for block in spec.blocks:
        if block.run_id not in run_ids:
            return None
        if block.title and (not re.fullmatch(r"[\u3400-\u9fff ]+", block.title) or not safe_language(block.title)):
            return None
    return spec
