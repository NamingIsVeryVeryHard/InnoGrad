"""Authenticated API entry point for the additive material pipeline."""
from __future__ import annotations

from datetime import date
import re
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from .db import File, Submission, Task, Version
from .material_pipeline import PipelineError, run_pipeline


class PipelineRequest:
    """Marker used only for documentation; the route parses a strict model below."""


def register(app, db, authenticated, get_sub, root):
    from pydantic import BaseModel, ConfigDict

    class MaterialPlan(BaseModel):
        model_config = ConfigDict(extra="forbid")
        id: str = Field(min_length=1, max_length=120)
        kind: Literal["goal", "delivery"]
        due: date
        weight: float = Field(gt=0, le=1000)
        creditKey: str = Field(min_length=1, max_length=200)

    class MaterialPipelineBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        file_ids: list[str] | None = Field(default=None, max_length=30)
        stage: Literal["annual", "proposal"] | None = None
        period: str | None = Field(default=None, max_length=80)
        cutoff: date | None = None
        template: Literal["balanced", "evidence-strict", "early-stage", "graduation-stage"] = "balanced"
        plans: list[MaterialPlan] = Field(default_factory=list, max_length=100)
        practice_id: str = Field(default="", max_length=300)
        force_ocr: bool = False
        consent: bool = False

    @app.post("/api/v1/submissions/{ident}/material-pipeline")
    def material_pipeline(ident: str, body: MaterialPipelineBody, user=Depends(authenticated), session=Depends(db)):
        if not body.consent:
            raise HTTPException(422, "请确认将材料文本发送到配置的模型服务")
        sub = get_sub(session, user, ident)
        task = session.get(Task, sub.task_id) if sub.task_id else None
        selected_ids = list(dict.fromkeys(body.file_ids or sub.draft.get("file_ids", [])))
        if not selected_ids or len(selected_ids) > 5:
            raise HTTPException(422, "请提供 1—5 份材料附件")
        rows = session.scalars(select(File).where(File.id.in_(selected_ids), File.submission_id == sub.id)).all()
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(selected_ids):
            raise HTTPException(404, "材料附件不存在或不属于本次提交")
        if user.id != sub.student_id:
            visible = set()
            for version in session.scalars(select(Version).where(Version.submission_id == sub.id)).all():
                visible.update(version.snapshot.get("file_ids", []))
            if not set(selected_ids).issubset(visible):
                raise HTTPException(404, "材料附件尚未进入可见提交版本")
        if any(row.media_type != "application/pdf" for row in rows):
            raise HTTPException(422, "材料处理链目前只接受 PDF")
        period = body.period or (task.period if task else None)
        if not period and sub.current_version_id:
            version = session.get(Version, sub.current_version_id)
            period = version.snapshot.get("period") if version else None
        if not period:
            raise HTTPException(422, "请提供材料期间 period")
        match = re.search(r"(20\d{2})", period)
        if not match:
            raise HTTPException(422, "period 必须包含四位学年起始年份")
        academic_year = int(match.group(1))
        cutoff = body.cutoff or date(academic_year + 1, 9, 1)
        if cutoff < date(academic_year, 9, 1) or cutoff > date(academic_year + 1, 9, 1):
            raise HTTPException(422, "统计截止日必须位于评价学年内或结束边界")
        context = {"student_id": sub.student_id, "academic_year": academic_year, "cutoff": cutoff.isoformat(),
                   "template": body.template, "practice_id": body.practice_id, "period": period,
                   "stage": body.stage or ("annual" if sub.kind == "annual" else "proposal"),
                   "task_id": sub.task_id,
                   "plans": [plan.model_dump(mode="json", by_alias=True) for plan in body.plans]}
        documents, data = [], []
        for row in rows:
            path = Path(root) / row.storage_key
            if not path.exists() or path.stat().st_size != row.size:
                raise HTTPException(422, "材料文件暂不可用")
            raw = path.read_bytes()
            documents.append({"document_id": row.id, "source_name": row.name, "sha256": row.sha256,
                              "kind": "annual" if context["stage"] == "annual" else "proposal"})
            data.append(raw)
        try:
            return run_pipeline(context, documents, data, force_ocr=body.force_ocr)
        except PipelineError as exc:
            raise HTTPException(422, str(exc)) from exc

