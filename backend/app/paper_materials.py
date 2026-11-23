"""Attachment roles for paper submissions."""

from typing import Literal


PaperAttachmentRole = Literal[
    "paper_fulltext",
    "submission_proof",
    "author_order_proof",
    "acceptance_proof",
    "publication_proof",
    "article_page",
    "contribution_proof",
    "other_proof",
]

PAPER_ATTACHMENT_ROLE_LABELS = {
    "paper_fulltext": "论文全文",
    "submission_proof": "投稿证明",
    "author_order_proof": "作者顺位证明",
    "acceptance_proof": "录用证明",
    "publication_proof": "发表证明",
    "article_page": "文章页面或 DOI 证明",
    "contribution_proof": "本人贡献证明",
    "other_proof": "其他证明材料",
}


def normalize_file_roles(file_ids, roles, *, default="other_proof"):
    """Keep only roles for selected files and preserve legacy submissions."""
    ids = list(dict.fromkeys(file_ids or []))
    provided = roles or {}
    if set(provided) - set(ids):
        raise ValueError("材料类型只能设置给本次提交的附件")
    normalized = {}
    for file_id in ids:
        role = provided.get(file_id, default)
        if role not in PAPER_ATTACHMENT_ROLE_LABELS:
            raise ValueError("附件材料类型无效")
        normalized[file_id] = role
    return normalized
