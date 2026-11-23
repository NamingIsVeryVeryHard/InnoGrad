"""From the repository root, run with PYTHONPATH=backend backend/.venv/bin/python
fixtures/teacher-agent/generate.py > fixtures/teacher-agent/schemas_and_mocks.json.
"""

import json
import importlib
import random
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import event, select

from app.db import Base, PortraitSnapshot, User, connect
from app.seed import seed
from app.seed_scenarios import ident, seed_scenarios
from app.teacher_agent.contract import PaperQuerySpec, QueryPatch, TurnResponse, TurnTimelineItem, apply_patch, export_schemas
from app.teacher_agent.papers import materialize
from app.teacher_agent.privacy import render_agent_response


AS_OF = datetime(2026, 11, 19, 2, tzinfo=timezone.utc)
FIXED_SEED = 320237


def _fixture_ids(session, flush_context, instances):
    for row in session.new:
        if isinstance(row, User) and row.id is None:
            row.id = ident("fixture/user/" + row.username)
        elif isinstance(row, PortraitSnapshot) and row.id is None:
            row.id = ident("fixture/snapshot/" + row.archive_id)


def build_artifact():
    token_rng = random.Random(FIXED_SEED)

    def fixed_token_urlsafe(nbytes=32):
        return token_rng.randbytes(nbytes).hex()

    def fixed_token_hex(nbytes=32):
        return token_rng.randbytes(nbytes).hex()

    engine, sessions = connect("sqlite://")
    event.listen(sessions, "before_flush", _fixture_ids)
    try:
        Base.metadata.create_all(engine)
        seed_module = importlib.import_module("app.seed")
        scenario_module = importlib.import_module("app.seed_scenarios")
        main_module = importlib.import_module("app.main")
        with (
            TemporaryDirectory() as temp,
            patch("app.db.datetime") as clock,
            patch("zipfile.time") as zip_clock,
            patch.object(seed_module.secrets, "token_urlsafe", fixed_token_urlsafe),
            patch.object(scenario_module.secrets, "token_urlsafe", fixed_token_urlsafe),
            patch.object(main_module.secrets, "token_hex", fixed_token_hex),
        ):
            clock.now.return_value = AS_OF
            zip_clock.localtime.return_value = AS_OF.timetuple()
            seed(sessions)
            root = Path(temp)
            seed_scenarios(sessions, root / "files", root / "cohort", AS_OF.date())
            with sessions() as session:
                teacher = session.scalars(select(User).where(User.username == "teacher")).one()
                aggregate = PaperQuerySpec(
                    time_range={"from": "2026-01-01", "to": "2026-12-31"},
                    group_by=["publication_status"], page_size=2,
                )
                followup = apply_patch(aggregate, QueryPatch(
                    operation="list", group_by=[], page_size=50,
                    set_filters=[{"field": "publication_status", "value": "published"},
                                 {"field": "degree", "value": "博士"}],
                ))
                portrait = PaperQuerySpec(
                    operation="portrait", filters=[{"field": "student_id", "value": ident("s01")}],
                    include=["metrics", "items", "portrait", "sources"],
                )
                mocks = {}
                queries = {
                    "paper_summary_2026": aggregate,
                    "paper_followup_filtered": followup,
                    "student_portrait_trace": portrait,
                }
                for number, (name, query) in enumerate(queries.items(), 1):
                    result = materialize(session, teacher, query, run_id=f"run-demo-{number:02}",
                                         data_as_of=AS_OF.isoformat())
                    mocks[name] = {
                        **result.model_dump(mode="json", by_alias=True),
                        "conversation_id": "conv-demo-01", "turn_id": f"turn-demo-{number:02}",
                    }
                conversation_id, turn_id = "conv-demo-02", "turn-demo-04"
                results = [
                    materialize(session, teacher, query, run_id=run_id, data_as_of=AS_OF.isoformat())
                    .model_copy(update={"conversation_id": conversation_id, "turn_id": turn_id})
                    for query, run_id in [(aggregate, "run-demo-04"), (followup, "run-demo-05")]
                ]
                overview, published = results
                analysis = (
                    f"本年度有效档案中共有 {overview.pagination.total} 条论文申报记录 "
                    f"[{overview.query_run_id}]。其中博士生已发表的申报记录有 "
                    f"{published.pagination.total} 条 [{published.query_run_id}]。"
                )
                turn = TurnResponse(
                    conversation_id=conversation_id, conversation_lock_version=1,
                    turn=TurnTimelineItem(
                        id=turn_id, turn_index=1, input_mode="natural_language",
                        user_message="汇总 2026 年论文的发表状态，再列出博士生已发表的论文。",
                        resolved_query=followup, status="succeeded", created_at=AS_OF.isoformat(),
                        run_id=published.query_run_id, run_ids=[card.query_run_id for card in results],
                    ),
                    analysis=analysis, results=results, result=published,
                )
                analysis, notice = render_agent_response("本年度共发表了 99999 篇论文。", results)
                unverified = turn.model_copy(update={"analysis": analysis, "analysis_notice": notice})
                return {**export_schemas(), "mocks": mocks, "turn_mocks": {
                    "paper_multirun_turn": turn.model_dump(mode="json", by_alias=True),
                    "paper_multirun_unverified_analysis": unverified.model_dump(mode="json", by_alias=True),
                }}
    finally:
        engine.dispose()


if __name__ == "__main__":
    print(json.dumps(build_artifact(), ensure_ascii=False, indent=2))
