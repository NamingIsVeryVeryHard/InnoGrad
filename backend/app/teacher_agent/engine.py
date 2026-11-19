import hashlib
import json
import secrets
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from ..db import Audit, Idempotency, QueryConversation, QueryRun, QueryTurn, QueryTurnGrant, User, now, uid
from ..workspace import scope_ids
from .contract import (
    ClarificationPrompt, ClarifyAction, ConversationDetail, ConversationSummary, PaperQuerySpec,
    PatchSpecAction, ReplaceSpecAction, ResultEnvelope, TurnResponse, TurnTimelineItem,
    UnsupportedAction, apply_patch, validate_query_spec,
)
from .errors import (
    ConcurrencyConflictError, ForbiddenRoleError, IdempotencyConflictError, PlannerInvalidOutputError,
    ResourceNotFoundError, TeacherAgentError,
)
from .papers import materialize
from .planner import PlanRequest, build_planner
from .privacy import (
    SELECTED_STUDENT, agent_tool_view, free_text_filter, planner_view, prepare_agent_question,
    prepare_question, render_agent_response, resolve_agent_spec, resolve_subjects,
    roster, safe_language, student_ids, with_subject,
)


@dataclass(frozen=True)
class ActorContext:
    user_id: str
    role: str
    name: str = ""

    @classmethod
    def from_user(cls, user):
        if not user or not user.enabled or user.role not in ("teacher", "manager"):
            raise ForbiddenRoleError("仅导师或管理教师可使用对话查询")
        return cls(user.id, user.role, user.name)


def _user(session, actor):
    user = session.get(User, actor.user_id)
    ActorContext.from_user(user)
    return user


def _scope(session, user):
    ids = set(scope_ids(session, user))
    digest = hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
    return ids, digest


def _view_digest(view):
    return hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stored_view(raw, scope, original_digest):
    if raw is None:
        return None
    spec = validate_query_spec(raw)
    ids, digest = scope
    if digest == original_digest:
        return spec
    if any(free_text_filter(item) for item in spec.filters):
        raise ResourceNotFoundError("查询范围已变更，请重新设置筛选")
    selected = student_ids(spec)
    if selected:
        return with_subject(spec, sorted(ids.intersection(selected)))
    return spec


def _owned(session, user, model, ident):
    obj = session.scalar(select(model).where(model.id == ident, model.teacher_id == user.id))
    if obj is None:
        raise ResourceNotFoundError("记录不存在或无权访问")
    return obj


def _summary(conversation):
    return ConversationSummary.model_validate(conversation, from_attributes=True)


def _request_record(actor, operation, key, body):
    if not key or len(key) > 100:
        raise TeacherAgentError("必须提供长度不超过 100 的 Idempotency-Key")
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return dict(user_id=actor.user_id, operation=operation, key=key,
                request_hash=hashlib.sha256(payload.encode()).hexdigest())


def _receipt(session, record):
    receipt = session.scalar(select(Idempotency).where(
        Idempotency.user_id == record["user_id"], Idempotency.operation == record["operation"],
        Idempotency.key == record["key"]))
    if receipt and receipt.request_hash != record["request_hash"]:
        raise IdempotencyConflictError("幂等键已用于其他内容")
    return receipt


def _notice(status):
    text = ("当前仅开放论文查询，奖学金查询将在后续开放。" if status == "unsupported_domain"
            else "请明确要查看的论文范围，或从名单中选择学生。")
    return ResultEnvelope(status=status, clarification=ClarificationPrompt(message=text))


def _timeline(turn, spec, run, *, revoked=False, clarification=None, runs=()):
    return TurnTimelineItem(id=turn.id, turn_index=turn.turn_index, input_mode=turn.input_mode,
                            user_message="当时的查询范围已变更" if revoked else turn.user_message,
                            resolved_query=spec, status=turn.status, run_id=run.id if run else None,
                            access_revoked=revoked, clarification=clarification, created_at=turn.created_at,
                            run_ids=[item.id for item in runs] if runs else ([run.id] if run and not revoked else []))


def _run_result(session, user, run, scope):
    spec = _stored_view(run.applied_query, scope, run.scope_digest)
    result = (materialize(session, user, spec, run_id=run.id, data_as_of=now(),
                          scope_recomputed=scope[1] != run.scope_digest)
              if spec.domain == "paper" else _notice("unsupported_domain"))
    return result.model_copy(update={"conversation_id": run.conversation_id, "turn_id": run.turn_id,
                                     "query_run_id": run.id})


def _record_run(session, user, spec, scope, *, conversation_id=None, turn_id=None, parent_run_id=None, run_id=None):
    if parent_run_id:
        _owned(session, user, QueryRun, parent_run_id)
    ident, stamp = run_id or uid(), now()
    result = (materialize(session, user, spec, run_id=ident, data_as_of=stamp)
              if spec.domain == "paper" else _notice("unsupported_domain"))
    session.add(QueryRun(id=ident, conversation_id=conversation_id, turn_id=turn_id,
                         parent_run_id=parent_run_id, teacher_id=user.id, domain=spec.domain,
                         operation=spec.operation, basis=spec.basis, applied_query=spec.model_dump(mode="json", by_alias=True),
                         scope_digest=scope[1], scope_size=len(scope[0]), data_as_of=stamp,
                         result_version=result.schema_version, created_at=stamp,
                         metric_receipt={card.key: card.value for card in result.summary.metrics} if result.summary else {},
                         source_refs=[{"version_id": source.version_id} for source in result.sources]))
    session.add(Audit(actor_id=user.id, action="teacher_agent.query", object_id=ident))
    return result.model_copy(update={"turn_id": turn_id, "conversation_id": conversation_id, "query_run_id": ident})


class TeacherQueryEngine:
    def __init__(self, session_factory, planner=None):
        self.sessions = session_factory
        self.planner = planner if planner is not None else build_planner()

    def _write_once(self, actor, record, write, replay):
        try:
            with self.sessions.begin() as session:
                previous = _receipt(session, record)
                user = _user(session, actor)
                if previous:
                    return replay(session, user, previous.response)
                receipt = Idempotency(**record, response={})
                session.add(receipt)
                session.flush()
                result, receipt.response = write(session, user)
                return result
        except IntegrityError:
            with self.sessions() as session:
                previous = _receipt(session, record)
                if previous:
                    return replay(session, _user(session, actor), previous.response)
            raise

    def create_conversation(self, actor, *, domain="paper", title=None, idempotency_key):
        record = _request_record(actor, "teacher_agent.create", idempotency_key, {"domain": domain, "title": title})

        def write(session, user):
            visible, digest = _scope(session, user)
            safe_title = safe_language(title) if title else None
            conversation = QueryConversation(id=uid(), teacher_id=user.id, title=safe_title or
                                             ("论文查询" if domain == "paper" else "奖学金查询"),
                                             active_domain=domain, scope_digest_snapshot=digest,
                                             scope_size_snapshot=len(visible), turn_count=0, lock_version=0,
                                             status="active", created_at=now(), updated_at=now())
            session.add(conversation)
            session.add(Audit(actor_id=user.id, action="teacher_agent.create", object_id=conversation.id))
            return _summary(conversation), {"conversation_id": conversation.id}

        def replay(session, user, receipt):
            return _summary(_owned(session, user, QueryConversation, receipt["conversation_id"]))

        return self._write_once(actor, record, write, replay)

    def list_conversations(self, actor, *, limit=50, offset=0):
        with self.sessions() as session:
            user = _user(session, actor)
            rows = session.scalars(select(QueryConversation).where(
                QueryConversation.teacher_id == user.id, QueryConversation.status == "active")
                .order_by(QueryConversation.updated_at.desc(), QueryConversation.id).limit(limit).offset(offset))
            return [_summary(row) for row in rows]

    def get_conversation(self, actor, conversation_id):
        with self.sessions() as session:
            user = _user(session, actor)
            conversation = _owned(session, user, QueryConversation, conversation_id)
            scope = _scope(session, user)
            rows = session.scalars(select(QueryTurn).where(QueryTurn.conversation_id == conversation.id)
                                   .order_by(QueryTurn.turn_index)).all()
            turns, latest, results = [], None, []
            for index, turn in enumerate(rows):
                runs = self._runs(session, turn)
                run = runs[-1] if runs else None
                try:
                    specs = [_stored_view(item.applied_query, scope, item.scope_digest) for item in runs]
                    spec = specs[-1] if specs else None
                    latest, results = None, []
                    if index == len(rows) - 1 or turn.status == "clarification_needed":
                        results = [_run_result(session, user, item, scope) for item in runs]
                        latest = results[-1] if results else _notice(turn.status)
                    timeline = _timeline(turn, spec, run, runs=runs, clarification=latest.clarification if latest else None)
                    turns.append(timeline)
                except ResourceNotFoundError:
                    turns.append(_timeline(turn, None, run, revoked=True))
                    latest, results = None, []
            try:
                active = _stored_view(conversation.active_query_spec, scope, conversation.scope_digest_snapshot)
            except ResourceNotFoundError:
                active = None
            return ConversationDetail(conversation=_summary(conversation), active_query=active, turns=turns,
                                      latest_result=latest, latest_results=results)

    def execute_spec(self, actor, spec, *, parent_run_id=None):
        with self.sessions.begin() as session:
            user = _user(session, actor)
            scope = _scope(session, user)
            spec = resolve_subjects(spec, roster(session, scope[0]))
            return _record_run(session, user, spec, scope, parent_run_id=parent_run_id)

    def replay_run(self, actor, run_id):
        with self.sessions() as session:
            user = _user(session, actor)
            run = _owned(session, user, QueryRun, run_id)
            return _run_result(session, user, run, _scope(session, user))

    @staticmethod
    def _runs(session, turn):
        return session.scalars(select(QueryRun).where(QueryRun.turn_id == turn.id)
                               .order_by(QueryRun.created_at, QueryRun.id)).all()

    @staticmethod
    def _replay_turn(session, user, receipt):
        turn = session.get(QueryTurn, receipt["turn_id"])
        conversation = _owned(session, user, QueryConversation, turn.conversation_id)
        runs = TeacherQueryEngine._runs(session, turn)
        run = runs[-1] if runs else None
        scope = _scope(session, user)
        results = [_run_result(session, user, item, scope) for item in runs]
        result = (results[-1] if results else
                  _notice(turn.status).model_copy(update={"conversation_id": conversation.id, "turn_id": turn.id}))
        spec = _stored_view(run.applied_query, scope, run.scope_digest) if run else None
        timeline = _timeline(turn, spec, run, runs=runs, clarification=result.clarification)
        return TurnResponse(conversation_id=conversation.id, conversation_lock_version=conversation.lock_version,
                            turn=timeline, result=result, results=results)

    def submit_turn(self, actor, conversation_id, request, *, idempotency_key):
        record = _request_record(actor, f"teacher_agent.turn/{conversation_id}", idempotency_key,
                                 request.model_dump(mode="json", by_alias=True))
        entry = request.input
        parent_run_id = entry.parent_run_id if entry.mode == "drilldown_patch" else None
        selected, question, domain = [], None, "paper"
        with self.sessions() as session:
            user = _user(session, actor)
            conversation = _owned(session, user, QueryConversation, conversation_id)
            receipt = _receipt(session, record)
            if receipt:
                return self._replay_turn(session, user, receipt.response)
            version, domain = conversation.lock_version, conversation.active_domain
            if conversation.status != "active" or request.expected_lock_version not in (None, version):
                raise ConcurrencyConflictError("对话已变化，请刷新后重试")
            scope = _scope(session, user)
            try:
                if parent_run_id:
                    parent = _owned(session, user, QueryRun, parent_run_id)
                    if parent.conversation_id != conversation_id:
                        raise ResourceNotFoundError("该查询不属于当前对话")
                    previous = _stored_view(parent.applied_query, scope, parent.scope_digest)
                else:
                    previous = _stored_view(conversation.active_query_spec, scope, conversation.scope_digest_snapshot)
            except ResourceNotFoundError:
                previous = None
                if entry.mode == "drilldown_patch":
                    raise
            if entry.mode == "natural_language":
                agent_mode = self.planner.mode == "innoagent" and domain == "paper"
                prepare = prepare_agent_question if agent_mode else prepare_question
                question, selected = prepare(entry.message, roster(session, scope[0]))
        if entry.mode == "natural_language" and agent_mode and question:
            return self._agent_turn(actor, conversation_id, record, version, scope[1], previous, selected, question)
        trace = {"mode": "direct", "action": "direct"}
        if entry.mode == "structured_spec":
            action, label = ReplaceSpecAction(spec=entry.spec), "结构化查询"
        elif entry.mode == "drilldown_patch":
            action, label = PatchSpecAction(patch=entry.patch), "筛选查询"
        elif domain != "paper" and self.planner.mode == "innoagent":
            action, label = UnsupportedAction(requested_domain=domain, message="当前仅开放论文查询"), "未开放领域"
        elif question:
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            plan = self.planner.plan(PlanRequest(question, planner_view(previous), today))
            action, trace, label = plan.output, asdict(plan.trace), question
        else:
            action, label = ClarifyAction(message="请明确查询范围"), "查询范围待确认"

        def write(session, user):
            conversation = _owned(session, user, QueryConversation, conversation_id)
            current_scope = _scope(session, user)
            current = previous
            if current and current_scope[1] != scope[1]:
                current = _stored_view(current.model_dump(mode="json", by_alias=True), current_scope, scope[1])
            spec = None
            if isinstance(action, ReplaceSpecAction):
                spec = action.spec
            elif isinstance(action, PatchSpecAction):
                if current is None and domain != "paper":
                    raise TeacherAgentError("请先选择要筛选的论文查询")
                try:
                    spec = apply_patch(current or PaperQuerySpec(), action.patch)
                except (ValidationError, ValueError) as error:
                    raise TeacherAgentError("筛选条件与当前查询不兼容") from error
            if spec is not None:
                if entry.mode == "natural_language":
                    if SELECTED_STUDENT in student_ids(spec):
                        ids = selected or student_ids(current)
                        if not ids:
                            raise PlannerInvalidOutputError("规划器使用了未指定的学生")
                        spec = with_subject(spec, ids)
                    elif selected:
                        spec = with_subject(spec, selected)
                spec = resolve_subjects(spec, roster(session, current_scope[0]))
            stamp = now()
            values = dict(lock_version=version + 1, turn_count=QueryConversation.turn_count + 1, updated_at=stamp)
            raw = spec.model_dump(mode="json", by_alias=True) if spec else None
            if spec and spec.domain == "paper":
                values.update(active_query_spec=raw, active_domain=spec.domain,
                              scope_digest_snapshot=current_scope[1], scope_size_snapshot=len(current_scope[0]))
            changed = session.execute(update(QueryConversation).where(
                QueryConversation.id == conversation.id, QueryConversation.status == "active",
                QueryConversation.lock_version == version).values(**values))
            if changed.rowcount != 1:
                raise ConcurrencyConflictError("对话已变化，请刷新后重试")
            turn = QueryTurn(id=uid(), conversation_id=conversation.id, turn_index=conversation.turn_count,
                             input_mode=entry.mode, user_message=label, resolved_query_spec=raw,
                             planner_trace=trace, status="succeeded", created_at=stamp)
            session.add(turn)
            session.flush()
            if spec is not None:
                result = _record_run(session, user, spec, current_scope, conversation_id=conversation.id,
                                     turn_id=turn.id, parent_run_id=parent_run_id)
            else:
                status = "unsupported_domain" if isinstance(action, UnsupportedAction) else "clarification_needed"
                result = _notice(status).model_copy(update={"conversation_id": conversation.id, "turn_id": turn.id})
            turn.status = "succeeded" if result.status == "ok" else result.status
            session.add(Audit(actor_id=user.id, action="teacher_agent.turn", object_id=turn.id))
            run = session.get(QueryRun, result.query_run_id) if result.query_run_id else None
            timeline = _timeline(turn, spec, run, clarification=result.clarification)
            response = TurnResponse(conversation_id=conversation.id, conversation_lock_version=version + 1,
                                    turn=timeline, result=result, results=[result] if run else [])
            return response, {"turn_id": turn.id, "query_run_id": result.query_run_id}

        return self._write_once(actor, record, write, self._replay_turn)

    @contextmanager
    def _grant(self, actor, conversation_id, version, digest, selected):
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()

        def issue_token():
            current_time = int(time.time())
            try:
                with self.sessions.begin() as session:
                    grant = QueryTurnGrant(token_hash=key, teacher_id=actor.user_id,
                                           conversation_id=conversation_id, turn_id=uid(), version=version,
                                           expires_at=current_time + 60, scope_digest=digest, selected=selected,
                                           calls=[], used=0)
                    self._grant_scope(session, grant)
                    session.execute(delete(QueryTurnGrant).where(QueryTurnGrant.expires_at <= current_time,
                                                                QueryTurnGrant.conversation_id == conversation_id))
                    session.add(grant)
            except IntegrityError as error:
                raise ConcurrencyConflictError("当前对话正在处理另一轮查询") from error
            return token

        try:
            yield issue_token, key
        finally:
            with self.sessions.begin() as session:
                session.execute(delete(QueryTurnGrant).where(QueryTurnGrant.token_hash == key))

    @staticmethod
    def _grant_scope(session, grant, *, finalizing=False):
        if grant is None or (not finalizing and grant.expires_at <= time.time()):
            raise ResourceNotFoundError("本轮查询授权已结束")
        user = session.get(User, grant.teacher_id)
        ActorContext.from_user(user)
        conversation = _owned(session, user, QueryConversation, grant.conversation_id)
        scope = _scope(session, user)
        if (scope[1] != grant.scope_digest or conversation.lock_version != grant.version
                or conversation.status != "active"):
            raise ConcurrencyConflictError("查询期间对话或指导范围已变化，请重新提问")
        return user, conversation, scope

    def query_for_agent(self, token, query):
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.sessions.begin() as session:
            claimed = session.execute(update(QueryTurnGrant).where(
                QueryTurnGrant.token_hash == key, QueryTurnGrant.expires_at > time.time(),
                QueryTurnGrant.used < 5).values(used=QueryTurnGrant.used + 1))
            if claimed.rowcount != 1:
                raise ResourceNotFoundError("本轮查询授权已结束或查询次数已用完")
            grant = session.get(QueryTurnGrant, key)
            user, conversation, scope = self._grant_scope(session, grant)
            try:
                previous = (validate_query_spec(grant.calls[-1]["spec"]) if grant.calls else
                            _stored_view(conversation.active_query_spec, scope, conversation.scope_digest_snapshot))
            except ResourceNotFoundError:
                previous = None
            try:
                spec = query.spec if hasattr(query, "spec") else apply_patch(previous or PaperQuerySpec(), query.patch)
            except ValueError as error:
                raise TeacherAgentError("筛选条件与当前查询不兼容") from error
            selected = grant.selected
            if not selected and SELECTED_STUDENT in student_ids(spec):
                selected = student_ids(previous)
            spec = resolve_agent_spec(spec, selected, roster(session, scope[0]))
            run_id = uid()
            result = materialize(session, user, spec, run_id=run_id, data_as_of=now())
            if result.status != "ok":
                raise TeacherAgentError("请指定当前可见的一位学生")
            view = agent_tool_view(result)
            grant.calls = [*grant.calls, {"spec": spec.model_dump(mode="json", by_alias=True), "id": run_id,
                                        "view_digest": _view_digest(view)}]
            return view

    def _agent_turn(self, actor, conversation_id, record, version, digest, previous, selected, question):
        request = PlanRequest(question, previous, datetime.now(ZoneInfo("Asia/Shanghai")).date())
        with self._grant(actor, conversation_id, version, digest, selected) as (issue_token, key):
            text = self.planner.analyze(request, issue_token)

            def finish(session, user):
                grant = session.get(QueryTurnGrant, key)
                user, conversation, scope = self._grant_scope(session, grant, finalizing=True)
                stamp = now()
                raw = grant.calls[-1]["spec"] if grant.calls else None
                values = dict(lock_version=version + 1, updated_at=stamp, turn_count=QueryConversation.turn_count + 1)
                if raw:
                    values.update(active_query_spec=raw, active_domain="paper", scope_digest_snapshot=scope[1],
                                  scope_size_snapshot=len(scope[0]))
                changed = session.execute(update(QueryConversation).where(QueryConversation.id == conversation_id,
                    QueryConversation.status == "active", QueryConversation.lock_version == version).values(**values))
                if changed.rowcount != 1:
                    raise ConcurrencyConflictError("对话已变化，请刷新后重试")
                turn = QueryTurn(id=grant.turn_id, conversation_id=conversation_id, turn_index=conversation.turn_count,
                                 input_mode="natural_language", user_message=safe_language(question) or "论文分析", resolved_query_spec=raw,
                                 status="succeeded" if raw else "clarification_needed", created_at=stamp,
                                 planner_trace={"mode": "innoagent", "query_count": len(grant.calls)})
                session.add(turn)
                session.flush()
                results = []
                for call in grant.calls:
                    result = _record_run(session, user, validate_query_spec(call["spec"]), scope,
                                         conversation_id=conversation_id, turn_id=turn.id,
                                         run_id=call["id"])
                    if _view_digest(agent_tool_view(result)) != call["view_digest"]:
                        raise ConcurrencyConflictError("查询期间论文数据已变化，请重新提问")
                    results.append(result)
                analysis, notice = render_agent_response(text, results) if results else (None, None)
                session.add(Audit(actor_id=user.id, action="teacher_agent.turn", object_id=turn.id))
                receipt = {"turn_id": turn.id, "query_run_id": results[-1].query_run_id if results else None}
                final = results[-1] if results else _notice(turn.status).model_copy(
                    update={"conversation_id": conversation_id, "turn_id": turn.id})
                run = session.get(QueryRun, final.query_run_id) if results else None
                timeline = _timeline(turn, final.applied_query, run, clarification=final.clarification,
                                     runs=self._runs(session, turn))
                return TurnResponse(conversation_id=conversation_id, conversation_lock_version=version + 1,
                                    turn=timeline, result=final, results=results,
                                    analysis=analysis, analysis_notice=notice), receipt

            return self._write_once(actor, record, finish, self._replay_turn)

    def archive_conversation(self, actor, conversation_id):
        with self.sessions.begin() as session:
            user = _user(session, actor)
            conversation = _owned(session, user, QueryConversation, conversation_id)
            if conversation.status == "active":
                changed = session.execute(update(QueryConversation).where(QueryConversation.id == conversation.id,
                    QueryConversation.status == "active").values(status="archived", updated_at=now(),
                                                                lock_version=QueryConversation.lock_version + 1))
                if changed.rowcount:
                    session.add(Audit(actor_id=user.id, action="teacher_agent.archive", object_id=conversation.id))
