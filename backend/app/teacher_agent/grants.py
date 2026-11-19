import os
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Protocol

from .budget import TurnBudget
from .errors import ConcurrencyConflictError, PlannerConfigError, ResourceNotFoundError


@dataclass
class ActiveTurnGrant:
    teacher_id: str
    conversation_id: str
    turn_id: str
    version: int
    scope_digest: str
    selected: list[str]
    budget: TurnBudget
    calls: list[dict] = field(default_factory=list)
    call_ids: list[str] = field(default_factory=list)
    tool_failures: int = 0
    clarification_subjects: list[str] | None = None

    @property
    def query_count(self) -> int:
        return len(self.calls)


class TurnGrantStore(Protocol):
    def issue(self, key: str, grant: ActiveTurnGrant) -> None: ...

    def claim(self, key: str) -> AbstractContextManager[ActiveTurnGrant]: ...

    def finalize(self, key: str) -> AbstractContextManager[ActiveTurnGrant]: ...

    def revoke(self, key: str) -> None: ...


@dataclass
class _GrantEntry:
    grant: ActiveTurnGrant
    expires_at: float
    lock: Lock = field(default_factory=Lock)
    accepting: bool = True


_SINGLE_WORKER = "教师查询的内存授权仅支持单个 API worker"
_GRANT_ENDED = "本轮查询授权已结束"


def _check_single_worker():
    options = sys.argv[1:]
    configured = [os.getenv("WEB_CONCURRENCY", "1")]
    configured.extend(options[index + 1] for index, value in enumerate(options[:-1]) if value == "--workers")
    configured.extend(value.split("=", 1)[1] for value in options if value.startswith("--workers="))
    try:
        if any(int(value) != 1 for value in configured):
            raise ValueError
    except ValueError:
        raise PlannerConfigError(_SINGLE_WORKER) from None


class InMemoryTurnGrantStore:
    def __init__(self, *, clock: Callable[[], float] = monotonic, ttl_seconds: float = 60):
        _check_single_worker()
        self._pid = os.getpid()
        self._clock = clock
        self._ttl = ttl_seconds
        self._index = Lock()
        self._by_key: dict[str, _GrantEntry] = {}
        self._by_conversation: dict[str, str] = {}

    def _check_process(self):
        if os.getpid() != self._pid:
            raise PlannerConfigError(_SINGLE_WORKER)

    def issue(self, key, grant):
        self._check_process()
        while True:
            with self._index:
                if key in self._by_key:
                    raise ConcurrencyConflictError("当前对话正在处理另一轮查询")
                previous_key = self._by_conversation.get(grant.conversation_id)
                if previous_key is None:
                    self._register(key, grant)
                    return
                entry = self._by_key[previous_key]
                if self._clock() < entry.expires_at:
                    raise ConcurrencyConflictError("当前对话正在处理另一轮查询")
            with entry.lock, self._index:
                if self._by_key.get(previous_key) is entry:
                    if key in self._by_key:
                        raise ConcurrencyConflictError("当前对话正在处理另一轮查询")
                    entry.accepting = False
                    del self._by_key[previous_key]
                    self._register(key, grant)
                    return

    def _register(self, key, grant):
        self._by_key[key] = _GrantEntry(deepcopy(grant), self._clock() + self._ttl)
        self._by_conversation[grant.conversation_id] = key

    def _lookup(self, key):
        self._check_process()
        with self._index:
            return self._by_key.get(key)

    @contextmanager
    def claim(self, key):
        entry = self._lookup(key)
        if entry is None:
            raise ResourceNotFoundError(_GRANT_ENDED)
        with entry.lock:
            if not entry.accepting or self._clock() >= entry.expires_at:
                raise ResourceNotFoundError(_GRANT_ENDED)
            grant = deepcopy(entry.grant)
            yield grant
            entry.grant = deepcopy(grant)

    @contextmanager
    def finalize(self, key):
        entry = self._lookup(key)
        if entry is None:
            raise ResourceNotFoundError(_GRANT_ENDED)
        with entry.lock:
            if not entry.accepting:
                raise ResourceNotFoundError(_GRANT_ENDED)
            entry.accepting = False
            yield deepcopy(entry.grant)

    def revoke(self, key):
        entry = self._lookup(key)
        if entry is None:
            return
        with entry.lock, self._index:
            if self._by_key.get(key) is entry:
                entry.accepting = False
                del self._by_key[key]
                del self._by_conversation[entry.grant.conversation_id]
