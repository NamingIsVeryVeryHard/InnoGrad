"""InnoAgent 0.7 HTTP/SSE protocol; one isolated workspace per review."""
import hashlib
import json
import os
import time
from urllib.parse import quote
from uuid import uuid4

import httpx
from ..material_rules import SKILL_ROOT, SKILL_VERSION
from ..review_errors import ReviewFailure


class InnoAgentAdapter:
    def __init__(self, config):
        self.base_url = config["base_url"].rstrip("/")
        self.skill = config.get("skill") or "material-review"
        self.timeout = config.get("timeout_seconds") or 240
        key = os.getenv("AI_API_KEY", "")
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    def _request(self, method, path, **kwargs):
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10), follow_redirects=False) as client:
            response = client.request(method, self.base_url + path, headers=self.headers, **kwargs)
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise ReviewFailure("OUTPUT_INVALID")
            return response

    def _ensure_runtime(self):
        self._request("GET", "/api/health")
        data = self._request("GET", "/api/skills").json()
        skills = data if isinstance(data, list) else data.get("skills", [])
        if not any(isinstance(s, dict) and s.get("name") == self.skill and s.get("enabled") is not False for s in skills):
            raise ReviewFailure("CONFIG_ERROR")
        content = self._request("GET", f"/api/skills/{quote(self.skill, safe='')}/content").json()["content"]
        expected = (SKILL_ROOT / "SKILL.md").read_text()
        if content != expected:
            raise ReviewFailure("CONFIG_ERROR")
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _last_json(events):
        """Use only assistant text deltas, never thinking or tool output."""
        text, direct = "", None
        for line in events:
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                continue
            try:
                envelope = json.loads(raw)
            except ValueError:
                raise ReviewFailure("OUTPUT_INVALID")
            event = envelope.get("event", envelope)
            if event.get("type") in ("error", "aborted", "permission_request", "question"):
                raise ReviewFailure("TRANSIENT_SERVICE", transient=event.get("type") == "error")
            if event.get("type") == "text_start":
                text = ""
            if event.get("type") == "text_delta":
                text += event.get("delta", "")
            if "checks" in event:
                direct = event
        if direct is not None and not text:
            return direct
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            result = json.loads(stripped)
        except ValueError:
            raise ReviewFailure("OUTPUT_INVALID")
        if not isinstance(result, dict):
            raise ReviewFailure("OUTPUT_INVALID")
        return result

    def _stream(self, body):
        deadline = time.monotonic() + self.timeout
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10), follow_redirects=False) as client:
            with client.stream("POST", self.base_url + "/api/chat/stream", json=body, headers=self.headers) as response:
                response.raise_for_status()
                lines, total = [], 0
                for line in response.iter_lines():
                    if time.monotonic() > deadline:
                        raise httpx.ReadTimeout("review deadline")
                    total += len(line)
                    if total > 2 * 1024 * 1024:
                        raise ReviewFailure("OUTPUT_INVALID")
                    lines.append(line)
                return self._last_json(lines)

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
                    except Exception:
                        pass
            except Exception:
                pass
        return "failed"

    def review(self, payload, output_schema):
        metadata = {"skill": self.skill, "skill_version": SKILL_VERSION}
        session_id = None
        try:
            metadata["skill_hash"] = self._ensure_runtime()
            session = self._request("POST", "/api/sessions", json={
                "newWorkspace": {"name": "review-" + payload["version_id"], "isTemp": True}
            }).json()
            session_id = session["id"]
            metadata["agent_session_id"] = session_id
            metadata["workspace_id"] = session.get("workspaceId")
            prompt = f"/skill:{self.skill}\n" + json.dumps(
                {"review_package": payload, "output_schema": output_schema}, ensure_ascii=False)
            result = self._stream({"prompt": prompt, "sessionId": session_id, "clientRequestId": str(uuid4())})
            messages = self._request("GET", f"/api/sessions/{quote(session_id, safe='')}").json().get("messages", [])
            identities = [m for m in messages if m.get("role") == "assistant" and m.get("model")]
            if identities:
                metadata["response_model"] = identities[-1]["model"]
                metadata["response_provider"] = identities[-1].get("provider")
            return result, metadata
        except ReviewFailure as exc:
            exc.metadata = metadata
            raise
        except httpx.TimeoutException:
            raise ReviewFailure("TRANSIENT_TIMEOUT", metadata, transient=True)
        except httpx.HTTPStatusError as exc:
            transient = exc.response.status_code in (408, 409, 429) or exc.response.status_code >= 500
            raise ReviewFailure("TRANSIENT_SERVICE" if transient else "CONFIG_ERROR", metadata, transient)
        except httpx.TransportError:
            raise ReviewFailure("TRANSIENT_SERVICE", metadata, transient=True)
        except (KeyError, ValueError, TypeError):
            raise ReviewFailure("OUTPUT_INVALID", metadata)
        finally:
            if session_id:
                metadata["cleanup_status"] = self._cleanup(session_id)
