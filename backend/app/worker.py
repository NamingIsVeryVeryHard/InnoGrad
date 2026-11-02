"""Outbox/exports use short DB transactions; AI execution runs outside transactions."""
import argparse
import time
from sqlalchemy import select, update
from datetime import datetime, timedelta, timezone
from .db import Outbox, Submission, Decision, Archive, Correction, Version, uid, now, connect


def drain(factory, limit=100):
    count = 0
    for _ in range(limit):
        with factory.begin() as session:
            session.execute(update(Outbox).where(Outbox.status == "processing", Outbox.attempts < 3)
                            .values(status="pending", error_code="ARCHIVE_RECOVERED"))
            event = session.scalar(select(Outbox).where(
                Outbox.status == "pending",
                (Outbox.next_attempt_at.is_(None) | (Outbox.next_attempt_at <= now()))
            ).order_by(Outbox.created_at).limit(1))
            if not event:
                break
            claimed = session.execute(update(Outbox).where(Outbox.id == event.id, Outbox.status == "pending")
                                      .values(status="processing", attempts=Outbox.attempts + 1))
            if claimed.rowcount != 1:
                continue
            nested = session.begin_nested()
            try:
                if event.kind == "review.approved":
                    sub = session.get(Submission, event.aggregate_id)
                    decision = session.get(Decision, event.payload["decision_id"])
                    if not decision or decision.outcome != "approved" or decision.version_id != event.payload["version_id"]:
                        raise ValueError("Invalid archive event")
                    archive = session.scalar(select(Archive).where(Archive.version_id == decision.version_id))
                    if not archive:
                        archive = Archive(id=uid(), version_id=decision.version_id, decision_id=decision.id)
                        session.add(archive)
                        session.flush()
                    changed = session.execute(update(Submission).where(Submission.id == sub.id,
                        Submission.current_version_id == decision.version_id, Submission.status == "approved"
                    ).values(status="archived", effective_archive_id=archive.id, lock_version=Submission.lock_version + 1))
                    version = session.get(Version, decision.version_id)
                    cid = version.snapshot.get('correction_id')
                    if cid and changed.rowcount == 1:
                        session.execute(update(Correction).where(Correction.id==cid, Correction.status=='opened').values(status='completed'))
                    from .portraits import ensure_snapshot
                    ensure_snapshot(session, archive, sub)
                elif event.kind != "submission.version_created":
                    raise ValueError("Unknown event kind")
            except Exception:
                nested.rollback()
                if event.attempts >= 3:
                    event.status, event.error_code = "failed", "ARCHIVE_FAILED"
                else:
                    event.status, event.next_attempt_at = "pending", (datetime.now(timezone.utc) + timedelta(seconds=2 ** event.attempts)).isoformat()
                    event.error_code = "ARCHIVE_RETRY"
                continue
            nested.commit()
            # Submitted events acknowledge manual routing; no fictitious AI success.
            event.status = "done"
            count += 1
    return count


def main():
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    _, factory = connect()
    from .jobs import process_exports, run_ai
    import logging
    while True:
        processed = 0
        for name, handler in [('outbox', drain), ('exports', process_exports), ('ai', run_ai)]:
            try:
                processed += int(handler(factory))
            except Exception:
                logging.getLogger(__name__).error("%s processing failed; durable job retained", name)
                if args.once: raise
        from .db import WorkerHeartbeat, now
        with factory.begin() as session:
            session.merge(WorkerHeartbeat(id='main', last_seen=now()))
        if args.once:
            print(f"Processed {processed} jobs/events")
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
