"""Attachment roles for student submissions."""

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

SubmissionAttachmentRole = Literal[
    "paper_fulltext",
    "submission_proof",
    "author_order_proof",
    "acceptance_proof",
    "publication_proof",
    "article_page",
    "contribution_proof",
    "award_certificate",
    "publicity_proof",
    "team_role_proof",
    "attendance_proof",
    "presentation_proof",
    "poster_proof",
    "practice_task_proof",
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

COMPETITION_ATTACHMENT_ROLE_LABELS = {
    "award_certificate": "获奖证书",
    "publicity_proof": "公示页面或获奖名单证明",
    "team_role_proof": "团队成员与本人角色证明",
    "other_proof": "其他证明材料",
}

EXCHANGE_ATTACHMENT_ROLE_LABELS = {
    "attendance_proof": "参会证明 / 邀请函",
    "presentation_proof": "作报告证明 / 议程 / PPT",
    "poster_proof": "海报展示证明 / 海报原件",
    "practice_task_proof": "实践任务证明 / 结项或考核材料",
    "other_proof": "其他证明材料",
}

ATTACHMENT_ROLE_LABELS_BY_KIND = {
    "paper": PAPER_ATTACHMENT_ROLE_LABELS,
    "annual": PAPER_ATTACHMENT_ROLE_LABELS,
    "competition": COMPETITION_ATTACHMENT_ROLE_LABELS,
    "exchange": EXCHANGE_ATTACHMENT_ROLE_LABELS,
}

ALL_ATTACHMENT_ROLE_LABELS = {
    **PAPER_ATTACHMENT_ROLE_LABELS,
    **COMPETITION_ATTACHMENT_ROLE_LABELS,
    **EXCHANGE_ATTACHMENT_ROLE_LABELS,
}


def normalize_file_roles(file_ids, roles, *, kind="paper", default="other_proof"):
    """Keep only roles for selected files and preserve legacy submissions."""
    ids = list(dict.fromkeys(file_ids or []))
    provided = roles or {}
    if set(provided) - set(ids):
        raise ValueError("材料类型只能设置给本次提交的附件")
    allowed = ATTACHMENT_ROLE_LABELS_BY_KIND.get(kind, PAPER_ATTACHMENT_ROLE_LABELS)
    normalized = {}
    for file_id in ids:
        role = provided.get(file_id, default)
        if role not in allowed:
            raise ValueError("附件材料类型无效")
        normalized[file_id] = role
    return normalized
