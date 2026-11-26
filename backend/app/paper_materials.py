"""Attachment roles across paper, software copyright, research project, and annual submissions."""

from __future__ import annotations

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

SoftwareCopyrightAttachmentRole = Literal[
    "copyright_certificate",
    "registration_application",
    "source_code_doc",
    "development_proof",
    "other_proof",
]

ResearchProjectAttachmentRole = Literal[
    "experiment_report",
    "dataset_doc",
    "code_artifact",
    "prototype_doc",
    "project_proof",
    "other_proof",
]

AttachmentRole = Literal[
    "paper_fulltext",
    "submission_proof",
    "author_order_proof",
    "acceptance_proof",
    "publication_proof",
    "article_page",
    "contribution_proof",
    "copyright_certificate",
    "registration_application",
    "source_code_doc",
    "development_proof",
    "experiment_report",
    "dataset_doc",
    "code_artifact",
    "prototype_doc",
    "project_proof",
    "other_proof",
]

PAPER_ATTACHMENT_ROLE_LABELS: dict[str, str] = {
    "paper_fulltext": "论文全文",
    "submission_proof": "投稿证明",
    "author_order_proof": "作者顺位证明",
    "acceptance_proof": "录用证明",
    "publication_proof": "发表证明",
    "article_page": "文章页面或 DOI 证明",
    "contribution_proof": "本人贡献证明",
    "other_proof": "其他证明材料",
}

SOFTWARE_COPYRIGHT_ATTACHMENT_ROLE_LABELS: dict[str, str] = {
    "copyright_certificate": "软件著作权登记证书",
    "registration_application": "登记申请或受理证明",
    "source_code_doc": "源代码或设计说明书",
    "development_proof": "个人开发工作证明",
    "other_proof": "其他证明材料",
}

RESEARCH_PROJECT_ATTACHMENT_ROLE_LABELS: dict[str, str] = {
    "experiment_report": "实验报告",
    "dataset_doc": "数据集说明或清单",
    "code_artifact": "代码文档或仓库说明",
    "prototype_doc": "原型设计或演示材料",
    "project_proof": "项目参与或结题证明",
    "other_proof": "其他证明材料",
}

ATTACHMENT_ROLE_LABELS: dict[str, str] = {
    **PAPER_ATTACHMENT_ROLE_LABELS,
    **SOFTWARE_COPYRIGHT_ATTACHMENT_ROLE_LABELS,
    **RESEARCH_PROJECT_ATTACHMENT_ROLE_LABELS,
}

_KIND_ROLE_MAP: dict[str, dict[str, str]] = {
    "paper": PAPER_ATTACHMENT_ROLE_LABELS,
    "annual": PAPER_ATTACHMENT_ROLE_LABELS,
    "software_copyright": SOFTWARE_COPYRIGHT_ATTACHMENT_ROLE_LABELS,
    "research_project": RESEARCH_PROJECT_ATTACHMENT_ROLE_LABELS,
}


def allowed_roles_for_kind(kind: str) -> dict[str, str]:
    """Return the allowed attachment role dictionary for a submission kind."""
    return _KIND_ROLE_MAP.get(kind, PAPER_ATTACHMENT_ROLE_LABELS)


def normalize_file_roles(
    file_ids: list[str] | None,
    roles: dict[str, str] | None,
    *,
    kind: str = "paper",
    default: str = "other_proof",
) -> dict[str, str]:
    """Validate and keep roles only for files attached to the current submission."""
    ids = list(dict.fromkeys(file_ids or []))
    provided = roles or {}
    if set(provided) - set(ids):
        raise ValueError("材料类型只能设置给本次提交的附件")
    allowed = allowed_roles_for_kind(kind)
    normalized: dict[str, str] = {}
    for file_id in ids:
        role = provided.get(file_id, default)
        if role not in allowed:
            raise ValueError("附件材料类型无效")
        normalized[file_id] = role
    return normalized
