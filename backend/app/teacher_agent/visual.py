import re


_LEGACY_VISUAL_BLOCK = re.compile(
    r"^[ \t]*```visual-html\b[^\n]*(?:\n.*?(?:^[ \t]*```[ \t]*\r?$|\Z)|\Z)",
    re.MULTILINE | re.DOTALL,
)


def strip_visual_blocks(text: str) -> str:
    return _LEGACY_VISUAL_BLOCK.sub("", text).strip()
