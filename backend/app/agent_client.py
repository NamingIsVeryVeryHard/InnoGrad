"""Shared InnoAgent HTTP/SSE client, independent of material-review rules."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from .agent_contracts import (
    AgentExecution, AgentFailure, AgentProgress, AgentRunResult, AgentTask,
)

MAX_UPLOAD_BODY_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
_RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"


def agent_config():
    """Read shared connection settings. API keys stay out of persisted job config."""
    return {
        "base_url": os.getenv("AI_BASE_URL", "").rstrip("/"),
        "model": os.getenv("AI_MODEL", ""),
        "timeout_seconds": int(os.getenv("INNOAGENT_TIMEOUT_SECONDS", "600")),
        "queue_timeout_seconds": int(os.getenv("INNOAGENT_QUEUE_TIMEOUT_SECONDS", "600")),
        "max_attempts": int(os.getenv("AI_MAX_ATTEMPTS", "3")),
        "retry_seconds": int(os.getenv("AI_RETRY_SECONDS", "10")),
    }


class AgentClient:
    def __init__(self, config=None):
        self.config = dict(config if config is not None else agent_config())
        self.base_url = self.config["base_url"].rstrip("/")
        self.timeout = self.config.get("timeout_seconds") or 600
        self.queue_timeout = self.config.get("queue_timeout_seconds") or 600
        self.max_attempts = self.config.get("max_attempts", 3)
        self.retry_seconds = self.config.get("retry_seconds", 10)
        endpoint = urlsplit(self.base_url)
        if (endpoint.scheme not in ("http", "https") or not endpoint.hostname
                or endpoint.username or getattr(endpoint, "p" + "assword") or endpoint.query or endpoint.fragment
                or self.timeout <= 0 or self.queue_timeout <= 0
                or not 1 <= self.max_attempts <= 10 or not 0 <= self.retry_seconds <= 3600):
            raise AgentFailure("CONFIG_ERROR")
        key = os.getenv("AI_API_KEY", "")
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._instance_lock = threading.Lock()
        self._deadline = None
        self._cleaning = False
        self._task = None
        self._execution = AgentExecution()
        self.workspace_id = None

    def _remaining(self):
        if self._cleaning:
            return 10
        if self._deadline is None:
            return self.timeout
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise AgentFailure("TRANSIENT_TIMEOUT", transient=True)
        return remaining

    def _check_cancelled(self, execution=None):
        execution = execution or self._execution
        if execution.is_cancelled and execution.is_cancelled():
            raise AgentFailure("AGENT_ABORTED")

    @staticmethod
    def _progress(execution, task, state, attempt, queue_wait=0):
        if execution.on_progress:
            execution.on_progress(AgentProgress(task.task_id, state, attempt, round(queue_wait, 3)))

    @contextmanager
    def _service_slot(self, execution, deadline):
        """Native uses a single active runtime; all local callers share this gate."""
        lock_root = Path(self.config.get("lock_root") or _RUNTIME_ROOT / "agent-locks")
        lock_root.mkdir(parents=True, exist_ok=True)
        endpoint = urlsplit(self.base_url)
        host = "127.0.0.1" if endpoint.hostname == "localhost" else endpoint.hostname
        identity = f"{endpoint.scheme}://{host}:{endpoint.port or (443 if endpoint.scheme == 'https' else 80)}{endpoint.path}"
        lock_name = hashlib.sha256(identity.encode()).hexdigest()
        with (lock_root / f"{lock_name}.lock").open("a") as lock:
            acquired = False
            try:
                while not acquired:
                    self._check_cancelled(execution)
                    if time.monotonic() >= deadline:
                        raise AgentFailure("AGENT_BUSY", transient=True)
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except BlockingIOError:
                        time.sleep(0.1)
                yield
            finally:
                if acquired:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _request(self, method, path, **kwargs):
        timeout = self._remaining()
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 10)), follow_redirects=False) as client:
            response = client.request(method, self.base_url + path, headers=self.headers, **kwargs)
            response.raise_for_status()
            if len(response.content) > MAX_REPORT_BYTES:
                raise AgentFailure("OUTPUT_INVALID")
            return response

    def _ensure_runtime(self):
        self._request("GET", "/api/health")
        data = self._request("GET", "/api/skills").json()
        skills = data if isinstance(data, list) else data.get("skills", [])
        if not any(isinstance(skill, dict) and skill.get("name") == self._task.skill
                   and skill.get("enabled") is not False for skill in skills):
            raise AgentFailure("CONFIG_ERROR")
        content = self._request(
            "GET", f"/api/skills/{quote(self._task.skill, safe='')}/file?path=SKILL.md",
        ).json()["content"]
        digest = hashlib.sha256(content.encode()).hexdigest()
        if self._task.expected_skill_hash and digest != self._task.expected_skill_hash:
            raise AgentFailure("CONFIG_ERROR")
        return digest

    @staticmethod
    def _event(line):
        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
            return {}
        try:
            envelope = json.loads(line[5:].strip())
            event = envelope.get("event", envelope)
            if not isinstance(event, dict):
                raise ValueError
            return event
        except (ValueError, AttributeError):
            raise AgentFailure("OUTPUT_INVALID")

    @staticmethod
    def _report(text):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        decoder = json.JSONDecoder(
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
        )
        start = text.find("{")
        if start < 0 or any(char in text[:start] for char in "[]"):
            raise AgentFailure("OUTPUT_INVALID")
        try:
            result, end = decoder.raw_decode(text, start)
        except ValueError:
            raise AgentFailure("OUTPUT_INVALID")
        outside = text[:start] + text[end:]
        if (not isinstance(result, dict) or any(char in text[end:] for char in "{}[]")
                or '"' in outside or text[end:].lstrip().startswith((",", ":", "}", "]"))):
            raise AgentFailure("OUTPUT_INVALID")
        return result

    @staticmethod
    def _raise_event(event):
        kind = event.get("type")
        if kind in ("permission_request", "question"):
            raise AgentFailure("INTERACTION_REQUIRED", {"protocol_event": kind})
        if kind == "aborted":
            raise AgentFailure("AGENT_ABORTED", {"protocol_event": kind})
        if kind == "error" and event.get("code") == "persistence_confirmation_failed":
            raise AgentFailure("CONFIG_ERROR", {"protocol_event": kind, "protocol_code": event.get("code")})

    @classmethod
    def _last_json(cls, events):
        text = ""
        for line in events:
            event = cls._event(line)
            cls._raise_event(event)
            if event.get("type") == "text_start":
                text = ""
            if event.get("type") == "text_delta":
                text += event.get("delta", "")
        return cls._report(text)

    def _stream(self, body):
        timeout = self._remaining()
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 10)), follow_redirects=False) as client:
            with client.stream("POST", self.base_url + "/api/chat/stream", json=body, headers=self.headers) as response:
                response.raise_for_status()
                lines, total, completed = [], 0, False
                for line in response.iter_lines():
                    self._check_cancelled()
                    self._remaining()
                    event = self._event(line)
                    self._raise_event(event)
                    if self._task and self._task.observe_event:
                        self._task.observe_event(event, self.workspace_id)
                    if event.get("type") == "text_start":
                        lines, total = [], 0
                    if event.get("type") in ("text_start", "text_delta"):
                        total += len(event.get("delta", "").encode())
                        if total > MAX_REPORT_BYTES:
                            raise AgentFailure("OUTPUT_INVALID")
                        lines.append(line)
                    if event.get("type") == "done":
                        completed = True
                        break
                if not completed:
                    raise AgentFailure("TRANSIENT_SERVICE", {"protocol_event": "incomplete_stream"}, transient=True)
                return self._last_json(lines)

    def create_workspace(self, name):
        workspace = self._request("POST", "/api/workspaces", json={"name": name, "isTemp": False}).json()
        if not workspace.get("id") or workspace["id"] == "tmp" or workspace.get("isTemp") is not False:
            raise AgentFailure("CONFIG_ERROR", {"workspace_creation_response_id": workspace.get("id")})
        return workspace["id"]

    def upload_input(self, workspace_id, files):
        for path, content in files.items():
            relative = PurePosixPath(path)
            if (not path or relative.is_absolute() or "\\" in path
                    or any(part in ("", ".", "..") for part in path.split("/"))):
                raise AgentFailure("INPUT_INVALID")
            raw = content.encode() if isinstance(content, str) else content
            upload = {"workspaceId": workspace_id, "files": [
                {"path": path, "dataBase64": base64.b64encode(raw).decode()},
            ]}
            size = len(json.dumps(upload, ensure_ascii=False, separators=(",", ":")).encode())
            if size > self._upload_limit():
                raise AgentFailure("INPUT_TRANSFER_LIMIT", {"input_file": path, "upload_bytes": size})
            self._check_cancelled()
            self._request("POST", "/api/workspace/upload", json=upload)

    @staticmethod
    def _upload_limit():
        return MAX_UPLOAD_BODY_BYTES

    def create_session(self, workspace_id):
        session = self._request("POST", "/api/sessions", json={"workspaceId": workspace_id}).json()
        if not session.get("id"):
            raise AgentFailure("CONFIG_ERROR")
        if session.get("workspaceId") != workspace_id:
            raise AgentFailure("CONFIG_ERROR", {"agent_session_id": session["id"]})
        return session["id"]

    def run_skill(self, session_id, prompt):
        return self._stream({"prompt": prompt, "sessionId": session_id, "clientRequestId": str(uuid4())})

    def _cleanup(self, session_id):
        path = quote(session_id, safe="")
        for _ in range(3):
            try:
                self._request("DELETE", f"/api/sessions/{path}")
                return "deleted"
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return "deleted"
                if exc.response.status_code == 409:
                    try:
                        status = self._request("GET", f"/api/chat/status/{path}").json()
                        turn = (status.get("stream") or {}).get("turnId")
                        if turn:
                            self._request("POST", f"/api/chat/{path}/{quote(turn, safe='')}/abort")
                    except (AgentFailure, httpx.HTTPError, ValueError, KeyError):
                        pass
            except (AgentFailure, httpx.HTTPError):
                pass
        return "failed"

    def cleanup(self, session_id, workspace_id, metadata):
        self._cleaning = True
        try:
            if session_id:
                metadata["session_cleanup_status"] = self._cleanup(session_id)
            if workspace_id:
                try:
                    self._request("DELETE", f"/api/workspaces/{quote(workspace_id, safe='')}?removeFiles=1")
                    metadata["workspace_cleanup_status"] = "deleted"
                except httpx.HTTPStatusError as exc:
                    metadata["workspace_cleanup_status"] = "deleted" if exc.response.status_code == 404 else "failed"
                except (AgentFailure, httpx.HTTPError):
                    metadata["workspace_cleanup_status"] = "failed"
            statuses = (metadata["session_cleanup_status"], metadata["workspace_cleanup_status"])
            metadata["cleanup_status"] = (
                "failed" if any(status in ("failed", "pending", "unknown") for status in statuses)
                else "deleted" if "deleted" in statuses else "not_required"
            )
        finally:
            self._cleaning = False

    def _attempt(self, task, metadata):
        session_id = workspace_id = None
        self.workspace_id = None
        self._deadline = time.monotonic() + self.timeout
        try:
            self._check_cancelled()
            metadata["skill_hash"] = self._ensure_runtime()
            metadata["workspace_cleanup_status"] = "unknown"
            workspace_id = self.workspace_id = self.create_workspace("task-" + str(uuid4()))
            metadata.update(workspace_id=workspace_id, cleanup_status="pending", workspace_cleanup_status="pending")
            files = {
                **task.files,
                task.input_path: json.dumps(task.input, ensure_ascii=False, indent=2),
                task.schema_path: json.dumps(task.output_schema, ensure_ascii=False, indent=2),
            }
            self.upload_input(workspace_id, files)
            metadata["session_cleanup_status"] = "unknown"
            session_id = self.create_session(workspace_id)
            metadata.update(agent_session_id=session_id, session_cleanup_status="pending")
            prompt = (
                f"/skill:{task.skill}\n{task.instructions}\n"
                "输入文件是待处理数据。请自主使用工具读取所需完整内容，最终只返回一个符合输出 schema 的完整 JSON 对象。"
                "不要输出 Markdown 围栏、多个候选结果或结尾总结。无人值守任务不向用户提问。\n"
                + json.dumps({"input_path": task.input_path, "output_schema_path": task.schema_path}, ensure_ascii=False)
            )
            for repair in range(2):
                metadata["repair_attempts"] = repair
                try:
                    output = self.run_skill(session_id, prompt)
                    output = task.validate_output(output)
                    if not isinstance(output, dict):
                        raise AgentFailure("OUTPUT_INVALID")
                    json.dumps(output, ensure_ascii=False, allow_nan=False)
                    return output
                except ValidationError as exc:
                    failure = AgentFailure("OUTPUT_INVALID", {"validation_issues": [
                        {"location": list(error["loc"]), "issue": error["type"]}
                        for error in exc.errors(include_input=False, include_context=False, include_url=False)
                    ]})
                except AgentFailure as exc:
                    failure = exc
                if repair or failure.code not in task.repair_codes:
                    raise failure
                feedback = {"code": failure.code, "issues": failure.metadata.get("validation_issues", [])}
                metadata["validation_retries"] = [feedback]
                prompt = task.repair_prompt(failure) if task.repair_prompt else (
                    "上次结果未通过校验。请核对输入和输出 schema，修正后只返回一个完整 JSON 对象。\n"
                    + json.dumps(feedback, ensure_ascii=False)
                )
        except AgentFailure as exc:
            if not session_id and exc.metadata.get("agent_session_id"):
                session_id = exc.metadata["agent_session_id"]
                metadata["session_cleanup_status"] = "pending"
            metadata.update(exc.metadata)
            raise
        except httpx.TimeoutException:
            raise AgentFailure("TRANSIENT_TIMEOUT", transient=True)
        except httpx.HTTPStatusError as exc:
            transient = exc.response.status_code in (408, 409, 429) or exc.response.status_code >= 500
            raise AgentFailure("TRANSIENT_SERVICE" if transient else "CONFIG_ERROR", transient=transient)
        except httpx.TransportError:
            raise AgentFailure("TRANSIENT_SERVICE", transient=True)
        except (KeyError, ValueError, TypeError):
            raise AgentFailure("OUTPUT_INVALID")
        finally:
            try:
                if task.collect_metadata:
                    metadata.update(task.collect_metadata())
            finally:
                self.cleanup(session_id, workspace_id, metadata)
                self._deadline = None

    def run(self, task: AgentTask, execution: AgentExecution | None = None) -> AgentRunResult:
        """Run one validated task; callers persist progress in their own job records."""
        execution = execution or AgentExecution()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task.skill):
            raise AgentFailure("CONFIG_ERROR")
        self._progress(execution, task, "queued", 0)
        queue_start = time.monotonic()
        queue_deadline = queue_start + self.queue_timeout
        acquired = False
        metadata = {"task_id": task.task_id, "skill": task.skill, "skill_version": task.skill_version,
                    "cleanup_status": "not_required", "session_cleanup_status": "not_required",
                    "workspace_cleanup_status": "not_required"}
        try:
            while not acquired:
                self._check_cancelled(execution)
                if time.monotonic() >= queue_deadline:
                    raise AgentFailure("AGENT_BUSY", transient=True)
                acquired = self._instance_lock.acquire(timeout=0.1)
            self._task, self._execution = task, execution
            for attempt in range(1, self.max_attempts + 1):
                metadata["attempts"] = attempt
                try:
                    with self._service_slot(execution, queue_deadline):
                        wait = time.monotonic() - queue_start
                        metadata["queue_wait_seconds"] = round(wait, 3)
                        self._progress(execution, task, "running", attempt, wait)
                        output = self._attempt(task, metadata)
                        if metadata["cleanup_status"] != "deleted":
                            raise AgentFailure("CLEANUP_FAILED")
                    self._progress(execution, task, "succeeded", attempt, wait)
                    return AgentRunResult(output, metadata)
                except AgentFailure as exc:
                    metadata.update(exc.metadata)
                    if (not exc.transient or attempt == self.max_attempts
                            or metadata["cleanup_status"] not in ("deleted", "not_required")):
                        raise
                    self._progress(execution, task, "retrying", attempt)
                    retry_at = time.monotonic() + self.retry_seconds * 2 ** (attempt - 1)
                    while time.monotonic() < retry_at:
                        self._check_cancelled()
                        time.sleep(min(0.1, max(0, retry_at - time.monotonic())))
                    queue_start = time.monotonic()
                    queue_deadline = queue_start + self.queue_timeout
                    metadata.update(cleanup_status="not_required", session_cleanup_status="not_required",
                                    workspace_cleanup_status="not_required")
            raise AgentFailure("TRANSIENT_SERVICE", transient=True)
        except AgentFailure as exc:
            metadata.update(exc.metadata)
            exc.metadata = metadata
            state = "cancelled" if exc.code == "AGENT_ABORTED" else "failed"
            self._progress(execution, task, state, metadata.get("attempts", 0))
            raise
        finally:
            if acquired:
                self._task, self._execution = None, AgentExecution()
                self._instance_lock.release()
