"""Evidence-based records, not inferred ability scores or automatic eligibility decisions."""
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from .db import Archive, Audit, Decision, File, PortraitSnapshot, Submission, User, Version
from .policy import relation

RULE_VERSION = "archive-facts-1"
FIELDS = {"paper": ("title", "publication_status", "submission_date", "acceptance_date",
                    "publication_date", "contribution"), "annual": ("summary",)}


def ensure_snapshot(session, archive, sub):
    existing = session.scalar(select(PortraitSnapshot).where(PortraitSnapshot.archive_id == archive.id))
    if existing:
        return existing
    version = session.get(Version, archive.version_id)
    decision = session.get(Decision, archive.decision_id)
    if not version or version.submission_id != sub.id or not decision or decision.outcome != "approved":
        raise ValueError("Portrait requires an approved archive")
    facts = []
    for field in FIELDS[sub.kind]:
        value = version.snapshot["form"].get(field)
        if value:
            facts.append({"field": field, "value": value, "source": {
                "version_id": version.id, "pointer": "/form/" + field},
                "verification": "simulated_approved_submission" if version.snapshot.get("simulation") else "agent_approved_submission" if decision.actor_type == "agent" else "human_approved_submission"})
    files = []
    for fid in version.snapshot["file_ids"]:
        item = session.get(File, fid)
        files.append({"file_id": fid, "name": item.name, "sha256": item.sha256})
    row = PortraitSnapshot(archive_id=archive.id, rule_version=RULE_VERSION, payload={
        "simulation":bool(version.snapshot.get("simulation")), "submission_id": sub.id, "version_id": version.id, "version_number": version.number,
        "kind": sub.kind, "period": version.snapshot.get("period"),
        "requirements": version.snapshot["requirements"], "decision_id": decision.id,
        "review_actor_type":decision.actor_type, "ai_job_id":decision.ai_job_id,
        "reviewed_at": decision.created_at, "facts": facts, "files": files,
        "inferences": [], "ability_assessment": "待评价",
        "limitation": "记录来自审核通过的提交表单，审核主体与报告已留痕；不代表逐字段独立核真，不计算能力分或资格结论。"})
    session.add(row)
    session.flush()
    session.add(Audit(actor_id=decision.reviewer_id, action="portrait.snapshot_created", object_id=row.id))
    return row


def register(app, db, authenticated):
    @app.get("/api/v1/students/{student_id}/portrait")
    def portrait(student_id: str, user=Depends(authenticated), session=Depends(db)):
        student = session.get(User, student_id)
        allowed = user.id == student_id or (
            user.role in ("teacher", "manager") and relation(session, user.id, student_id))
        if not student or student.role != "student" or not allowed:
            raise HTTPException(404, "学生不存在或无权访问")
        rows = session.execute(select(Submission, Archive, PortraitSnapshot)
            .join(Archive, Submission.effective_archive_id == Archive.id)
            .outerjoin(PortraitSnapshot, PortraitSnapshot.archive_id == Archive.id)
            .where(Submission.student_id == student_id).order_by(Archive.created_at, Archive.id)).all()
        records = [{"archive_id": archive.id, "archived_at": archive.created_at,
                    "snapshot_id": snap.id, "rule_version": snap.rule_version,
                    **snap.payload} for sub, archive, snap in rows if snap]
        return JSONResponse({"student_id": student_id, "student_name": student.name,
                "basis": "current_effective_archives", "records": records,
                "pending_snapshot_count": sum(snap is None for _, _, snap in rows),
                "counts": {"paper_records": sum(r["kind"] == "paper" for r in records),
                           "annual_records": sum(r["kind"] == "annual" for r in records)},
                "ability_assessment": "待评价", "inferences": [],
                "notice": "只统计当前有效申报记录，尚未实现成果主档去重；不代表论文总数、能力得分或学校资格认定。"},
                headers={"Cache-Control": "no-store"})
