"""Authenticated HTTP interface for teacher query conversations."""
from collections.abc import Mapping
from functools import cached_property
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .contract import (
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
    PaperQuerySpec,
    QueryPatch,
    QuerySpec,
    ResultEnvelope,
    TurnRequest,
    TurnResponse,
    export_schemas,
)
from .engine import ActorContext, TeacherQueryEngine
from .errors import PlannerConfigError, ResourceNotFoundError, TeacherAgentError
from .planner import PlanRequest, PlanResult, QueryPlanner, build_planner, teacher_agent_config


PREFIX = "/api/v1/teacher-agent"
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]
TurnBearer = Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))]


class _ConfiguredPlanner:
    @cached_property
    def planner(self) -> QueryPlanner:
        return build_planner()

    def plan(self, request: PlanRequest) -> PlanResult:
        return self.planner.plan(request)

    @property
    def mode(self):
        return self.planner.mode

    def analyze(self, request, issue_token):
        return self.planner.analyze(request, issue_token)


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: PaperQuerySpec


class ToolPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patch: QueryPatch


class _NoStore:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or not (
            scope["path"] == PREFIX or scope["path"].startswith(PREFIX + "/")
        ):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_no_store)


def register(app: FastAPI, ctx: Mapping[str, Any], *, planner: QueryPlanner | None = None) -> None:
    engine = TeacherQueryEngine(app.state.sessions, planner=planner if planner is not None else _ConfiguredPlanner())
    router = APIRouter(prefix=PREFIX, tags=["teacher-agent"])
    app.add_middleware(_NoStore)

    @app.exception_handler(TeacherAgentError)
    async def domain_error(request: Request, error: TeacherAgentError):
        headers = {}
        if error.status_code == 503:
            delay = error.retry_after_seconds
            headers["Retry-After"] = str(5 if delay is None else delay)
        return JSONResponse(
            {"detail": str(error), "code": error.code},
            status_code=error.status_code,
            headers=headers,
        )

    def actor(user=Depends(ctx["authenticated"]), session=Depends(ctx["db"])) -> ActorContext:
        try:
            return ActorContext.from_user(user)
        finally:
            session.rollback()

    @router.get("/schemas")
    def schemas(current: ActorContext = Depends(actor)) -> dict:
        try:
            config, _ = teacher_agent_config()
            shared = config.shares_review_endpoint
        except PlannerConfigError:
            shared = None
        return {**export_schemas(), "shares_review_endpoint": shared}

    @router.post("/query")
    def query(
        body: Annotated[QuerySpec, Body(discriminator="domain")],
        current: ActorContext = Depends(actor),
    ) -> ResultEnvelope:
        return engine.execute_spec(current, body)

    @router.post("/tools/query-papers")
    def query_papers(body: ToolSpec | ToolPatch, authorization: TurnBearer):
        if not authorization:
            raise ResourceNotFoundError("本轮查询授权无效")
        return engine.query_for_agent(authorization.credentials, body)

    @router.post("/conversations", status_code=201)
    def create_conversation(
        body: CreateConversationRequest,
        idempotency_key: IdempotencyKey,
        current: ActorContext = Depends(actor),
    ) -> ConversationSummary:
        return engine.create_conversation(
            current, domain=body.domain, title=body.title, idempotency_key=idempotency_key,
        )

    @router.get("/conversations")
    def list_conversations(
        current: ActorContext = Depends(actor),
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[ConversationSummary]:
        return engine.list_conversations(current, limit=limit, offset=offset)

    @router.get("/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, current: ActorContext = Depends(actor)) -> ConversationDetail:
        return engine.get_conversation(current, conversation_id)

    @router.post("/conversations/{conversation_id}/turns")
    def submit_turn(
        conversation_id: str,
        body: TurnRequest,
        idempotency_key: IdempotencyKey,
        current: ActorContext = Depends(actor),
    ) -> TurnResponse:
        return engine.submit_turn(current, conversation_id, body, idempotency_key=idempotency_key)

    @router.delete("/conversations/{conversation_id}", status_code=204)
    def archive_conversation(conversation_id: str, current: ActorContext = Depends(actor)) -> Response:
        engine.archive_conversation(current, conversation_id)
        return Response(status_code=204)

    @router.get("/runs/{run_id}")
    def replay_run(run_id: str, current: ActorContext = Depends(actor)) -> ResultEnvelope:
        return engine.replay_run(current, run_id)

    app.include_router(router)
