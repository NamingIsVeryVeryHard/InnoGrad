"""Shared contracts for business modules calling InnoAgent."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

AgentState = Literal["queued", "running", "retrying", "succeeded", "failed", "cancelled"]


class AgentFailure(ValueError):
    """A safe error code and execution metadata, without provider response text."""

    def __init__(self, code, metadata=None, transient=False):
        super().__init__(code)
        self.code = code
        self.metadata = metadata if metadata is not None else {}
        self.transient = transient


@dataclass(frozen=True)
class AgentProgress:
    task_id: str
    state: AgentState
    attempt: int
    queue_wait_seconds: float = 0


@dataclass(frozen=True)
class AgentExecution:
    """Optional hooks into the caller's durable task queue."""

    on_progress: Callable[[AgentProgress], None] | None = None
    is_cancelled: Callable[[], bool] | None = None


@dataclass(frozen=True, kw_only=True)
class AgentTask:
    skill: str
    input: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    validate_output: Callable[[dict], dict]
    instructions: str
    files: Mapping[str, str | bytes] = field(default_factory=dict)
    input_path: str = "input/request.json"
    schema_path: str = "input/output-schema.json"
    task_id: str = field(default_factory=lambda: str(uuid4()))
    skill_version: str | None = None
    expected_skill_hash: str | None = None
    observe_event: Callable[[dict, str], None] | None = None
    collect_metadata: Callable[[], dict] | None = None
    repair_prompt: Callable[[AgentFailure], str] | None = None
    repair_codes: tuple[str, ...] = ("OUTPUT_INVALID",)


@dataclass(frozen=True)
class AgentRunResult:
    output: dict
    metadata: dict
