"""Evidence-based records, not inferred ability scores or automatic eligibility decisions."""
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from .db import Archive, Audit, Decision, File, PortraitSnapshot, Submission, User, Version
from .policy import relation

RULE_VERSION = "archive-facts-1"
FIELDS = {"paper": ("title", "publication_status", "submission_date", "acceptance_date",
                    "publication_date", "contribution"), "annual": ("summary", "plan")}


def build_guidance(records):
    """Build the PR20 history/guidance shape from immutable portrait records.

    This deliberately reports evidence and plans only. It does not infer ability
    scores or mark a plan complete without a current annual record.
    """
    ordered = sorted(records, key=lambda r: (r.get("period") or "", r.get("archived_at") or ""))
    history, goals, reviews = [], [], []
    for record in ordered:
        source = {"archive_id": record["archive_id"], "version_id": record["version_id"]}
        summary = next((f["value"] for f in record.get("facts", []) if f["field"] == "summary"), None)
        if summary:
            history.append({"period": record.get("period"), "summary": summary, "source": source})
            previous = goals[-1] if goals else None
            plan = next((f["value"] for f in record.get("facts", []) if f["field"] == "plan"), None)
            if plan:
                goal = {"text": plan, "period": record.get("period"), "status": "current", "source": source}
                if previous and previous["text"] == plan:
                    reviews.append({"goal": plan, "status": "plan_repeated", "prior_period": previous["period"], "source": source})
                goals.append(goal)
    current = history[-1] if history else None
    guidance = []
    if current:
        guidance.append({"action": "继续记录研究计划的执行结果", "why": "当前画像只有材料证据，不能从计划推断完成情况", "completion_evidence": "下一份年度报告中的结果、数据或产出", "source": current["source"]})
    return {"schema_version": "pr20-portrait-guidance-1", "history": history,
            "current_focus": current, "goals": goals, "plan_reviews": reviews,
            "guidance": guidance, "ability_assessment": "待评价",
            "notice": "建议来自已归档证据与计划记录；未生成能力分数或资格结论。"}


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
    from .growth import warnings_for
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

    @app.get("/api/v1/students/{student_id}/portrait/guidance")
    def portrait_guidance(student_id: str, user=Depends(authenticated), session=Depends(db)):
        student = session.get(User, student_id)
        allowed = user.id == student_id or (user.role in ("teacher", "manager") and relation(session, user.id, student_id))
        if not student or student.role != "student" or not allowed:
            raise HTTPException(404, "学生不存在或无权访问")
        rows = session.execute(select(Submission, Archive, PortraitSnapshot)
            .join(Archive, Submission.effective_archive_id == Archive.id)
            .join(PortraitSnapshot, PortraitSnapshot.archive_id == Archive.id)
            .where(Submission.student_id == student_id)).all()
        records = [{"archive_id": archive.id, "archived_at": archive.created_at, **snap.payload}
                   for _, archive, snap in rows]
        guidance = build_guidance(records)
        guidance["warnings"] = [w for w in warnings_for(session, user) if w["student"] == student_id]
        return JSONResponse({"student_id": student_id, **guidance}, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/students/{student_id}/portrait/compare")
    def portrait_compare(student_id: str, from_period: str, to_period: str,
                         user=Depends(authenticated), session=Depends(db)):
        student = session.get(User, student_id)
        allowed = user.id == student_id or (user.role in ("teacher", "manager") and relation(session, user.id, student_id))
        if not student or student.role != "student" or not allowed:
            raise HTTPException(404, "学生不存在或无权访问")
        rows = session.execute(select(Submission, Archive, PortraitSnapshot)
            .join(Archive, Submission.effective_archive_id == Archive.id)
            .join(PortraitSnapshot, PortraitSnapshot.archive_id == Archive.id)
            .where(Submission.student_id == student_id)).all()
        records = [{"archive_id": archive.id, "archived_at": archive.created_at, **snap.payload}
                   for _, archive, snap in rows]
        guidance = build_guidance(records)
        by_period = {item["period"]: item for item in guidance["history"]}
        before, after = by_period.get(from_period), by_period.get(to_period)
        if not before or not after:
            raise HTTPException(404, "指定学年没有已归档画像")
        return JSONResponse({"student_id": student_id, "from": before, "to": after,
                             "warnings": [w for w in warnings_for(session, user) if w["student"] == student_id],
                             "changed": before.get("summary") != after.get("summary"),
                             "notice": "比较基于两个学年的已归档原文和来源，不代表能力变化或排名。"},
                            headers={"Cache-Control": "no-store"})
