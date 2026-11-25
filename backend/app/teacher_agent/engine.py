import hashlib
import json
import secrets
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..db import Audit, Idempotency, QueryConversation, QueryRun, User, now, uid
from ..workspace import scope_ids
from .budget import TurnBudget
from .contract import (
    ClarificationPrompt, ClarifyAction, ConversationDetail, ConversationSummary, PaperQuerySpec,
    PatchSpecAction, PublicationStatusFilter, QueryPatch, ReplaceSpecAction, ResultEnvelope, TurnResponse,
    TurnTimelineItem, UnsupportedAction, apply_patch, validate_query_spec,
)
from .errors import (
    AgentResultViewChangedError, ConcurrencyConflictError, ForbiddenRoleError, IdempotencyConflictError,
    PlannerInvalidOutputError, PlannerUnavailableError, ResourceNotFoundError, RetryableToolInputError,
    TeacherAgentError,
)
from .grants import ActiveTurnGrant, InMemoryTurnGrantStore, TurnGrantStore
from .papers import materialize
from .planner import PlanRequest, build_planner, requests_only_published, requests_scholarship
from .privacy import (
    SELECTED_STUDENT, agent_clarification_subjects, agent_tool_view, free_text_filter, planner_view, prepare_agent_question,
    prepare_question, render_agent_response, resolve_agent_spec, resolve_subjects,
    roster, safe_agent_clarification, safe_language, student_ids, subject_filter, with_subject,
)
from .visual import extract_visual_artifact


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
    if selected and not set(selected) <= ids:
        raise ResourceNotFoundError("查询范围已变更，请重新设置筛选")
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


@dataclass(frozen=True)
class StoredTurn:
    id: str
    turn_index: int
    input_mode: str
    user_message: str
    resolved_query_spec: dict | None
    planner_trace: dict
    status: str
    run_ids: list[str]
    created_at: str


def _timeline(turn, spec=None, *, revoked=False, clarification=None):
    run_ids = [] if revoked else turn.run_ids
    return TurnTimelineItem(id=turn.id, turn_index=turn.turn_index, input_mode=turn.input_mode,
                            user_message="当时的查询范围已变更" if revoked else turn.user_message,
                            resolved_query=spec, status=turn.status, run_id=run_ids[-1] if run_ids else None,
                            access_revoked=revoked, clarification=clarification, created_at=turn.created_at,
                            run_ids=run_ids)


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
    if result.status != "ok":
        return result.model_copy(update={"turn_id": turn_id, "conversation_id": conversation_id, "applied_query": None})
    session.add(QueryRun(id=ident, conversation_id=conversation_id, turn_id=turn_id,
                         parent_run_id=parent_run_id, teacher_id=user.id, domain=spec.domain,
                         operation=spec.operation, basis=spec.basis, applied_query=spec.model_dump(mode="json", by_alias=True),
                         scope_digest=scope[1], scope_size=len(scope[0]), data_as_of=stamp,
                         result_version=result.schema_version, created_at=stamp,
                         metric_receipt={card.key: card.value for card in result.summary.metrics} if result.summary else {},
                         source_refs=[{"version_id": source.version_id} for source in result.sources]))
    session.add(Audit(actor_id=user.id, action="teacher_agent.query", object_id=ident))
    return result.model_copy(update={"turn_id": turn_id, "conversation_id": conversation_id, "query_run_id": ident})


_TOOL_ARGUMENTS = "请提供且仅提供 spec 或 patch。"
_TOOL_RETRIES_EXHAUSTED = "论文查询参数纠错次数已用完"
_SELECT_STUDENT = "请选择一位学生查看画像。"
_RESULT_VIEW_CHANGED = "查询期间论文数据已变化，请重新提问"
_SAFE_VALIDATION_REASONS = {
    "filtering pending_review/returned requires basis='submitted_latest'",
    "time_range.field='archived_at' requires basis='current_effective_archives'",
    "operation='portrait' requires a student_id, student_name, or student_number filter",
    "operation='portrait' does not support group_by",
    "group_by must not contain duplicates",
    "include must not contain duplicates",
}


def _tool_validation_message(argument, error):
    messages = []
    for issue in error.errors(include_input=False, include_url=False)[:4]:
        kind = issue["type"]
        location = issue["loc"]
        context = issue.get("ctx", {})
        if kind == "extra_forbidden":
            location, message = location[:-1], "请移除未定义的字段"
        elif kind == "union_tag_invalid":
            message = f"请选择合法类型 {context['expected_tags']}"
        elif kind == "literal_error":
            message = f"请使用合法值 {context['expected']}"
        elif kind == "value_error":
            reason = str(context["error"])
            message = reason if reason in _SAFE_VALIDATION_REASONS else "请检查字段和筛选条件是否兼容"
        else:
            message = "请检查字段是否齐全且类型正确"
        path = ".".join((argument, *(str(part) for part in location)))
        messages.append(f"{path}：{message}")
    return "；".join(dict.fromkeys(messages))


def _parse_tool_query(body: dict[str, object], previous, *, only_published: bool) -> tuple[PaperQuerySpec, str | None]:
    if set(body) not in ({"spec"}, {"patch"}):
        raise RetryableToolInputError(_TOOL_ARGUMENTS)
    argument, data = next(iter(body.items()))
    try:
        if argument == "spec":
            spec = PaperQuerySpec.model_validate(data)
            filters = spec.filters
        else:
            patch = QueryPatch.model_validate(data)
            spec = apply_patch(previous or PaperQuerySpec(), patch)
            filters = patch.set_filters
        if only_published and spec.operation != "portrait" and not any(
            isinstance(item, PublicationStatusFilter) for item in spec.filters
        ):
            spec = PaperQuerySpec.model_validate({
                **spec.model_dump(), "filters": [*spec.filters, PublicationStatusFilter(value="published")],
            })
    except ValidationError as error:
        raise RetryableToolInputError(_tool_validation_message(argument, error)) from None
    except ValueError:
        raise RetryableToolInputError("patch 中的筛选条件与当前查询不兼容。") from None
    explicit_id = next((item.value for item in filters if item.field == "student_id"
                        and item.operator == "eq" and item.value != SELECTED_STUDENT), None)
    return spec, explicit_id


class TeacherQueryEngine:
    def __init__(self, session_factory, planner=None, *, grants: TurnGrantStore | None = None):
        self.sessions = session_factory
        self.planner = planner if planner is not None else build_planner()
        self.grants = grants if grants is not None else InMemoryTurnGrantStore()

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
            rows = [StoredTurn(**raw) for raw in conversation.turns_json]
            runs_by_id = self._conversation_runs(session, conversation)
            turns, latest, results = [], None, []
            for index, turn in enumerate(rows):
                try:
                    turn, runs = self._turn_with_runs(turn, runs_by_id)
                    specs = [_stored_view(item.applied_query, scope, item.scope_digest) for item in runs]
                    spec = specs[-1] if specs else None
                    clarification = _notice(turn.status).clarification if not runs else None
                    if index == len(rows) - 1:
                        results = [_run_result(session, user, item, scope) for item in runs]
                        latest = results[-1] if results else _notice(turn.status).model_copy(
                            update={"conversation_id": conversation.id, "turn_id": turn.id},
                        )
                    turns.append(_timeline(turn, spec, clarification=clarification))
                except ResourceNotFoundError:
                    turns.append(_timeline(turn, revoked=True))
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
    def _conversation_runs(session, conversation, ids=None):
        query = select(QueryRun).where(
            QueryRun.conversation_id == conversation.id, QueryRun.teacher_id == conversation.teacher_id,
        )
        if ids is not None:
            query = query.where(QueryRun.id.in_(ids))
        return {run.id: run for run in session.scalars(query)}

    @staticmethod
    def _turn_with_runs(turn, runs_by_id):
        runs = [runs_by_id.get(ident) for ident in turn.run_ids]
        if any(run is None or run.turn_id != turn.id for run in runs):
            raise ResourceNotFoundError("记录不存在或无权访问")
        if turn.status == "unsupported_domain" and runs:
            return replace(turn, run_ids=[]), []
        return turn, runs

    @staticmethod
    def _replay_turn(session, user, conversation_id, receipt):
        conversation = _owned(session, user, QueryConversation, conversation_id)
        raw = next((item for item in conversation.turns_json if item["id"] == receipt["turn_id"]), None)
        if raw is None:
            raise ResourceNotFoundError("记录不存在或无权访问")
        turn = StoredTurn(**raw)
        turn, runs = TeacherQueryEngine._turn_with_runs(
            turn, TeacherQueryEngine._conversation_runs(session, conversation, turn.run_ids),
        )
        scope = _scope(session, user)
        results = [_run_result(session, user, item, scope) for item in runs]
        result = (results[-1] if results else
                  _notice(turn.status).model_copy(update={"conversation_id": conversation.id, "turn_id": turn.id}))
        timeline = _timeline(turn, result.applied_query, clarification=result.clarification)
        return TurnResponse(conversation_id=conversation.id, conversation_lock_version=conversation.lock_version,
                            turn=timeline, result=result, results=results)

    @staticmethod
    def _append_turn(session, conversation, version, scope, turn, *, active_query=None):
        values = dict(lock_version=version + 1, turn_count=turn.turn_index, updated_at=turn.created_at,
                      turns_json=[*conversation.turns_json, asdict(turn)])
        if active_query is not None:
            values.update(active_query_spec=active_query, active_domain="paper", scope_digest_snapshot=scope[1],
                          scope_size_snapshot=len(scope[0]))
        changed = session.execute(update(QueryConversation).where(
            QueryConversation.id == conversation.id, QueryConversation.teacher_id == conversation.teacher_id,
            QueryConversation.status == "active", QueryConversation.lock_version == version,
        ).values(**values))
        if changed.rowcount != 1:
            raise ConcurrencyConflictError("对话已变化，请刷新后重试")
        session.add(Audit(actor_id=conversation.teacher_id, action="teacher_agent.turn", object_id=turn.id))

    def submit_turn(self, actor, conversation_id, request, *, idempotency_key):
        record = _request_record(actor, f"teacher_agent.turn/{conversation_id}", idempotency_key,
                                 request.model_dump(mode="json", by_alias=True))
        entry = request.input
        parent_run_id = entry.parent_run_id if entry.mode == "drilldown_patch" else None
        selected, question, ambiguous, domain = [], None, [], "paper"
        requested_domain = None
        agent_mode = False
        with self.sessions() as session:
            user = _user(session, actor)
            conversation = _owned(session, user, QueryConversation, conversation_id)
            receipt = _receipt(session, record)
            if receipt:
                return self._replay_turn(session, user, conversation_id, receipt.response)
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
                if requests_scholarship(entry.message):
                    requested_domain = "scholarship"
                else:
                    agent_mode = self.planner.mode == "innoagent" and domain == "paper"
                    prepare = prepare_agent_question if agent_mode else prepare_question
                    students = roster(session, scope[0])
                    question, selected = prepare(entry.message, students)
                    if agent_mode:
                        ambiguous = agent_clarification_subjects(entry.message, students)
        if question and agent_mode:
            return self._agent_turn(actor, conversation_id, record, version, scope[1], previous, selected, ambiguous, question)
        trace = {"mode": "direct", "action": "direct"}
        if entry.mode == "structured_spec":
            action, label = ReplaceSpecAction(spec=entry.spec), "结构化查询"
        elif entry.mode == "drilldown_patch":
            action, label = PatchSpecAction(patch=entry.patch), "筛选查询"
        elif requested_domain or (domain != "paper" and self.planner.mode == "innoagent"):
            action = UnsupportedAction(requested_domain=requested_domain or domain, message="当前仅开放论文查询")
            label = "未开放领域"
        elif question:
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            plan = self.planner.plan(PlanRequest(question, planner_view(previous), today))
            action, trace, label = plan.output, asdict(plan.trace), question
        else:
            action, label = ClarifyAction(message="请明确查询范围"), "查询范围待确认"

        def write(session, user):
            conversation = _owned(session, user, QueryConversation, conversation_id)
            if conversation.status != "active" or conversation.lock_version != version:
                raise ConcurrencyConflictError("对话已变化，请刷新后重试")
            current_scope = _scope(session, user)
            current = None if isinstance(action, UnsupportedAction) else previous
            if parent_run_id:
                parent = _owned(session, user, QueryRun, parent_run_id)
                current = _stored_view(parent.applied_query, current_scope, parent.scope_digest)
            elif current and current_scope[1] != scope[1]:
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
            turn_id = uid()
            if spec is not None:
                result = _record_run(session, user, spec, current_scope, conversation_id=conversation.id,
                                     turn_id=turn_id, parent_run_id=parent_run_id)
            else:
                status = "unsupported_domain" if isinstance(action, UnsupportedAction) else "clarification_needed"
                result = _notice(status).model_copy(update={"conversation_id": conversation.id, "turn_id": turn_id})
            run_ids = [result.query_run_id] if result.query_run_id else []
            resolved = spec if run_ids else None
            raw = resolved.model_dump(mode="json", by_alias=True) if resolved else None
            turn = StoredTurn(turn_id, conversation.turn_count + 1, entry.mode, label, raw, trace,
                              "succeeded" if result.status == "ok" else result.status, run_ids, now())
            self._append_turn(session, conversation, version, current_scope, turn,
                              active_query=raw if resolved and resolved.domain == "paper" else None)
            timeline = _timeline(turn, resolved, clarification=result.clarification)
            response = TurnResponse(conversation_id=conversation.id, conversation_lock_version=version + 1,
                                    turn=timeline, result=result, results=[result] if run_ids else [])
            return response, {"turn_id": turn.id}

        return self._write_once(actor, record, write,
                                lambda session, user, receipt: self._replay_turn(session, user, conversation_id, receipt))

    @contextmanager
    def _grant(self, actor, conversation_id, version, digest, selected, ambiguous, budget, *, only_published):
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()

        def issue_token():
            with self.sessions() as session:
                self._active_scope(session, actor.user_id, conversation_id, version, digest)
            self.grants.issue(key, ActiveTurnGrant(
                actor.user_id, conversation_id, uid(), version, digest, selected, budget,
                clarification_subjects=ambiguous or None, only_published=only_published,
            ))
            with self.sessions() as session:
                self._active_scope(session, actor.user_id, conversation_id, version, digest)
            return token

        try:
            yield issue_token, key
        finally:
            self.grants.revoke(key)

    @staticmethod
    def _active_scope(session, teacher_id, conversation_id, version, digest):
        user = session.get(User, teacher_id)
        ActorContext.from_user(user)
        conversation = _owned(session, user, QueryConversation, conversation_id)
        scope = _scope(session, user)
        if scope[1] != digest or conversation.lock_version != version or conversation.status != "active":
            raise ConcurrencyConflictError("查询期间对话或指导范围已变化，请重新提问")
        return user, conversation, scope

    def _grant_scope(self, session, grant):
        return self._active_scope(session, grant.teacher_id, grant.conversation_id, grant.version, grant.scope_digest)

    def query_for_agent(self, token: str, raw: dict[str, object], call_id: str | None):
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.grants.claim(key) as grant, self.sessions() as session:
            user, conversation, scope = self._grant_scope(session, grant)
            if grant.tool_failures > grant.budget.max_tool_retries:
                raise PlannerInvalidOutputError(_TOOL_RETRIES_EXHAUSTED)
            if not call_id or call_id in grant.call_ids:
                raise PlannerInvalidOutputError("论文查询调用标识缺失或重复")
            if grant.query_count >= grant.budget.max_queries:
                raise ResourceNotFoundError("本轮查询次数已用完")
            grant.call_ids = [*grant.call_ids, call_id]
            try:
                previous = (validate_query_spec(grant.calls[-1]["spec"]) if grant.calls else
                            _stored_view(conversation.active_query_spec, scope, conversation.scope_digest_snapshot))
            except ResourceNotFoundError:
                previous = None
            try:
                spec, explicit_id = _parse_tool_query(raw, previous, only_published=grant.only_published)
                return self._preview_agent_query(session, user, scope, grant, spec, previous, explicit_id)
            except RetryableToolInputError as error:
                grant.tool_failures += 1
                failure = error
                if grant.tool_failures > grant.budget.max_tool_retries:
                    failure = PlannerInvalidOutputError(_TOOL_RETRIES_EXHAUSTED)
        raise failure

    @staticmethod
    def _preview_agent_query(session, user, scope, grant, spec, previous, explicit_id):
        selected = grant.selected or student_ids(previous)
        if SELECTED_STUDENT in student_ids(spec) and not selected:
            raise RetryableToolInputError("student_id 中的 selected-student 必须对应已指定的学生。")
        resolved = resolve_agent_spec(spec, selected, roster(session, scope[0]))
        subjects = student_ids(resolved)
        pending = grant.clarification_subjects
        if pending is None and len(subjects) > 1 and any(
            item.field in ("student_name", "student_number") for item in spec.filters
        ):
            pending = grant.clarification_subjects = subjects
        if pending is not None and (explicit_id not in pending or subjects != [explicit_id]):
            clarification = TeacherQueryEngine._student_clarification(session, user, pending)
            return {"clarification": clarification.model_dump(mode="json")}
        run_id = uid()
        result = materialize(session, user, resolved, run_id=run_id, data_as_of=now())
        if result.clarification:
            grant.clarification_subjects = [candidate.student_id for candidate in result.clarification.student_candidates]
            return {"clarification": result.clarification.model_dump(mode="json")}
        view = agent_tool_view(result)
        grant.calls = [*grant.calls, {"spec": resolved.model_dump(mode="json", by_alias=True), "id": run_id,
                                      "view_digest": _view_digest(view)}]
        return view

    @staticmethod
    def _student_clarification(session, user, subjects):
        if subjects and len(subjects) <= 50:
            spec = PaperQuerySpec(operation="portrait", filters=[subject_filter(subjects)])
            result = materialize(session, user, spec, run_id=uid(), data_as_of=now())
            if result.clarification:
                return result.clarification
        return ClarificationPrompt(message=_SELECT_STUDENT)

    @staticmethod
    def _agent_clarification(session, user, grant, text):
        if grant.clarification_subjects is not None:
            return TeacherQueryEngine._student_clarification(session, user, grant.clarification_subjects)
        message = safe_agent_clarification(text)
        return ClarificationPrompt(message=message) if message else _notice("clarification_needed").clarification

    def _agent_turn(self, actor, conversation_id, record, version, digest, previous, selected, ambiguous, question):
        budget = TurnBudget.from_env()
        request = PlanRequest(question, previous, datetime.now(ZoneInfo("Asia/Shanghai")).date(), budget=budget)
        for attempt in range(budget.max_turn_retries + 1):
            try:
                return self._agent_turn_attempt(actor, conversation_id, record, version, digest, selected, ambiguous, request)
            except (PlannerUnavailableError, PlannerInvalidOutputError, AgentResultViewChangedError,
                    SQLAlchemyError) as error:
                with self.sessions() as session:
                    receipt = _receipt(session, record)
                    if receipt:
                        return self._replay_turn(session, _user(session, actor), conversation_id, receipt.response)
                    if isinstance(error, SQLAlchemyError):
                        raise
                    self._active_scope(session, actor.user_id, conversation_id, version, digest)
                if isinstance(error, PlannerInvalidOutputError) or attempt == budget.max_turn_retries:
                    raise

    def _agent_turn_attempt(self, actor, conversation_id, record, version, digest, selected, ambiguous, request):
        with self._grant(actor, conversation_id, version, digest, selected, ambiguous, request.budget,
                         only_published=requests_only_published(request.user_message)) as (issue_token, key):
            try:
                text = self.planner.analyze(request, issue_token)
            except TimeoutError:
                raise PlannerUnavailableError("规划服务超时", retry_after_seconds=1) from None

            def finish(session, user):
                user, conversation, scope = self._grant_scope(session, grant)
                if grant.tool_failures > grant.budget.max_tool_retries:
                    raise PlannerInvalidOutputError(_TOOL_RETRIES_EXHAUSTED)
                calls = grant.calls
                raw = calls[-1]["spec"] if calls else None
                results = []
                for call in calls:
                    try:
                        result = _record_run(session, user, validate_query_spec(call["spec"]), scope,
                                             conversation_id=conversation_id, turn_id=grant.turn_id, run_id=call["id"])
                    except ResourceNotFoundError:
                        raise AgentResultViewChangedError(_RESULT_VIEW_CHANGED) from None
                    if result.status != "ok" or _view_digest(agent_tool_view(result)) != call["view_digest"]:
                        raise AgentResultViewChangedError(_RESULT_VIEW_CHANGED)
                    results.append(result)
                extracted = extract_visual_artifact(text, results)
                if results and (extracted.prose or not extracted.visual):
                    analysis, notice = render_agent_response(extracted.prose, results)
                else:
                    analysis, notice = None, None
                safe_question, _ = prepare_question(request.user_message, roster(session, scope[0]))
                turn = StoredTurn(
                    grant.turn_id, conversation.turn_count + 1, "natural_language",
                    safe_question or "论文分析", raw,
                    {"mode": "innoagent", "query_count": grant.query_count},
                    "succeeded" if results else "clarification_needed",
                    [item.query_run_id for item in results], now(),
                )
                clarification = None
                if not results or grant.clarification_subjects is not None:
                    clarification = self._agent_clarification(session, user, grant, extracted.prose)
                self._append_turn(session, conversation, version, scope, turn, active_query=raw)
                final = (results[-1] if results else ResultEnvelope(
                    status="clarification_needed", clarification=clarification,
                    conversation_id=conversation_id, turn_id=turn.id,
                ))
                timeline = _timeline(turn, final.applied_query, clarification=clarification)
                return TurnResponse(conversation_id=conversation_id, conversation_lock_version=version + 1,
                                    turn=timeline, result=final, results=results,
                                    analysis=analysis, analysis_notice=notice,
                                    visual=extracted.visual), {"turn_id": turn.id}

            with self.grants.finalize(key) as grant:
                return self._write_once(actor, record, finish,
                                        lambda session, user, receipt: self._replay_turn(
                                            session, user, conversation_id, receipt,
                                        ))

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
