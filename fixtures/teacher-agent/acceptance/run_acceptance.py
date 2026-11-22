"""Run the paper acceptance against a committed backend and React build."""

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import partial
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory, mkdtemp
from threading import Thread
import time
from urllib.parse import urlsplit
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from sqlalchemy import inspect, select

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TEST_CLOCK = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
MCP_PATH = "/api/v1/teacher-agent/mcp"


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return TEST_CLOCK.astimezone(tz) if tz else TEST_CLOCK.replace(tzinfo=None)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unpack_and_build(home, commit):
    archive = home / "source.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "archive", commit, "backend", "frontend"],
                       cwd=REPO, stdout=stream, check=True)
    with tarfile.open(archive) as source:
        source.extractall(home, filter="data")
    frontend = home / "frontend"
    modules = REPO / "frontend/node_modules"
    (frontend / "node_modules").symlink_to(modules, target_is_directory=True)
    subprocess.run(
        ["node", str(modules / "vite/bin/vite.js"), "build", "--configLoader", "runner"],
        cwd=frontend, check=True,
    )


@contextmanager
def innoagent(home, source, runtime, provider_config, api_url, trace_path):
    supplied = json.loads(provider_config.read_text(encoding="utf-8"))
    provider_name = supplied["defaultProvider"]
    provider = supplied["providers"][provider_name]
    endpoint = urlsplit(provider["baseUrl"])
    if endpoint.scheme not in {"http", "https"} or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Configure a loopback model provider for acceptance.")
    settings = {
        "defaultProvider": provider_name, "defaultModel": supplied["defaultModel"],
        "providers": {provider_name: provider}, "mcp": {"enabled": True},
        "memory": {f"l{level}Enabled": False for level in (1, 2, 3)},
        "plugins": {name: {"enabled": False}
                    for name in ("webAccess", "todo", "computerUse", "codemode", "permissionSystem")},
    }
    app = runtime / "apps/inno-agent"
    adapter = app / "node_modules/pi-mcp-adapter/index.ts"
    server = app / "dist/server.js"
    if not (adapter.is_file() and server.is_file() and (runtime / "node_modules").is_dir()):
        raise RuntimeError("Build InnoAgent and install its MCP adapter before acceptance.")

    config = home / "config"
    skill = source / "backend/skills/teacher-query-planner"
    shutil.copytree(skill, home / "skills/teacher-query-planner")
    shutil.copytree(skill / "extensions", config / "extensions")
    shutil.copyfile(HERE / "provider-trace.ts", config / "extensions/provider-trace.ts")
    (home / "node_modules").symlink_to(runtime / "node_modules", target_is_directory=True)
    (config / "config.json").touch(mode=0o600)
    save(config / "config.json", settings)
    save(config / "settings.json", {"defaultTools": []})
    save(config / "mcp-adapter.json", {
        "settings": {"allowInstall": False, "namespaceProxyTools": False, "outputGuard": False},
        "mcpServers": {},
    })
    grants = home / "grants"
    grants.mkdir(mode=0o700)
    port_file = home / "port"
    hook = home / "listen.cjs"
    hook.write_text(
        "const { Server } = require('node:net');\n"
        "const { writeFileSync } = require('node:fs');\n"
        "const listen = Server.prototype.listen;\n"
        "Server.prototype.listen = function(port, ...args) {\n"
        "  if (port !== 1) return listen.call(this, port, ...args);\n"
        "  this.once('listening', () => writeFileSync(process.env.ACCEPTANCE_PORT_FILE,\n"
        "    String(this.address().port), {mode: 0o600}));\n"
        "  return listen.call(this, 0, '127.0.0.1', ...args);\n"
        "};\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(home),
        "PI_OFFLINE": "1", "TEACHER_QUERY_PLANNER_ONLY": "1",
        "TEACHER_AGENT_GRANT_DIR": str(grants), "TEACHER_AGENT_MCP_URL": api_url + MCP_PATH,
        "ACCEPTANCE_TRACE_PATH": str(trace_path),
        "TEACHER_AGENT_MCP_ADAPTER": str(adapter), "ACCEPTANCE_PORT_FILE": str(port_file),
    }
    command = ["node", "--require", str(hook), str(server), "--home", str(home),
               "--config-dir", str(config), "--data-dir", str(home / "data"),
               "--skills-dir", str(home / "skills"), "--workspace", str(home / "workspace"), "--port", "1"]
    process = subprocess.Popen(command, cwd=home, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while not port_file.is_file() or not port_file.stat().st_size:
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("InnoAgent failed to open its isolated loopback listener.")
            time.sleep(0.1)
        url = f"http://127.0.0.1:{int(port_file.read_text())}"
        with httpx.Client(base_url=url, trust_env=False, timeout=15) as client:
            response = client.get("/api/settings")
            response.raise_for_status()
            assert all(response.json()["memory"].get(f"l{level}Enabled") is False for level in (1, 2, 3))
        yield url, grants
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@contextmanager
def api_runtime(home, db_path, listener, agent_url, grants, callbacks, *, invalid_receipt=False):
    for key in tuple(os.environ):
        if key.startswith(("TEACHER_AGENT_", "AI_")):
            del os.environ[key]
    os.environ.update(
        PYTHON_DOTENV_DISABLED="1", DATABASE_URL=f"sqlite:///{db_path}", FILE_ROOT=str(home / "files"),
        AI_MODE="rules", REVIEW_WORKFLOW="manual", COOKIE_SECURE="0",
        TEACHER_AGENT_MODE="innoagent", TEACHER_AGENT_BASE_URL=agent_url,
        TEACHER_AGENT_GRANT_DIR=str(grants), TEACHER_AGENT_TIMEOUT_SECONDS="120",
    )
    sys.path.insert(0, str(home / "backend"))
    from app import db, main
    from app.teacher_agent import engine, planner
    from receipt_trace import BoundaryCapture, PiTransport, observe_outcome

    app = main.app
    @app.middleware("http")
    async def observe_mcp(request, call_next):
        if request.method == "POST" and request.url.path == MCP_PATH:
            payload = await request.json()
            if payload.get("method") == "tools/call":
                callbacks.append(payload.get("params", {}).get("name") == "query_papers")
        return await call_next(request)

    app.add_middleware(BoundaryCapture, invalid_receipt=invalid_receipt)
    with patch.object(db, "datetime", FixedDatetime), patch.object(main, "datetime", FixedDatetime), \
            patch.object(engine, "datetime", FixedDatetime), \
            patch.object(planner, "InnoAgentQueryPlanner", partial(planner.InnoAgentQueryPlanner, transport=PiTransport())), \
            patch.object(planner, "_tool_outcome", partial(observe_outcome, planner._tool_outcome)):
        db.Base.metadata.create_all(app.state.engine)
        query_tables = {name for name in inspect(app.state.engine).get_table_names() if name.startswith("query_")}
        assert query_tables == {"query_conversation", "query_run"}, query_tables
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical",
                                               timeout_graceful_shutdown=3))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("FastAPI failed to start.")
                time.sleep(0.05)
            yield app.state.sessions
        finally:
            server.should_exit = True
            thread.join(timeout=6)
            app.state.engine.dispose()


def request(client, method, path, *, status=200, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code != status:
        raise RuntimeError(f"Fixture {method} returned {response.status_code}, expected {status}.")
    return response.json()


def post(client, path, body, *, status=200):
    return request(client, "POST", path, status=status, json=body,
                   headers={"Idempotency-Key": uuid4().hex})


def login(stack, url, username, password):
    client = stack.enter_context(httpx.Client(base_url=url, trust_env=False, timeout=30))
    result = post(client, "/api/v1/auth/login", {"username": username, "password": password})
    client.headers["X-CSRF-Token"] = result["csrf_token"]
    return client, result["user"]["id"]


def add_paper(student, teacher, teacher_id, title, status, dates, *, approved=True):
    submission = post(student, "/api/v1/submissions", {"kind": "paper", "reviewer_id": teacher_id}, status=201)
    path = f"/api/v1/submissions/{submission['id']}"
    proof = request(student, "POST", f"{path}/files", status=201, files={
        "file": ("synthetic-proof.pdf", b"%PDF-1.7 teacher acceptance fixture", "application/pdf"),
    })
    request(student, "PATCH", f"{path}/draft", json={
        "expected_lock_version": 0, "file_ids": [proof["id"]],
        "form": {"title": title, "contribution": "合成测试材料", "publication_status": status, **dates},
    })
    submitted = post(student, f"{path}/submit", {"expected_lock_version": 1}, status=202)
    if approved:
        post(teacher, f"{path}/decision", {
            "expected_lock_version": 2, "version_id": submitted["version_id"],
            "outcome": "approved", "opinion": "合成测试材料",
        })


def archive_rows(connection, actor_id):
    return [dict(row) for row in connection.execute("""
        SELECT submission.id AS id, owner.id AS owner, owner.name, profile.degree,
               json_extract(version.snapshot, '$.form.title') AS title,
               json_extract(version.snapshot, '$.form.publication_status') AS status,
               CASE json_extract(version.snapshot, '$.form.publication_status')
                   WHEN 'submitted' THEN json_extract(version.snapshot, '$.form.submission_date')
                   WHEN 'accepted' THEN json_extract(version.snapshot, '$.form.acceptance_date')
                   WHEN 'published' THEN json_extract(version.snapshot, '$.form.publication_date')
               END AS date
        FROM submissions AS submission
        JOIN users AS owner ON owner.id = submission.student_id
        JOIN student_profiles AS profile ON profile.user_id = owner.id
        JOIN archives AS archive ON archive.id = submission.effective_archive_id
        JOIN submission_versions AS version ON version.id = archive.version_id
            AND version.submission_id = submission.id
        JOIN review_decisions AS decision ON decision.id = archive.decision_id
            AND decision.version_id = version.id AND decision.outcome = 'approved'
        WHERE submission.kind = 'paper' AND EXISTS (
            SELECT 1 FROM supervisions AS supervision
            WHERE supervision.student_id = owner.id AND supervision.teacher_id = ?
                AND supervision.valid_from <= ?
                AND (supervision.valid_to IS NULL OR supervision.valid_to > ?)
        )
    """, (actor_id, TEST_CLOCK.isoformat(), TEST_CLOCK.isoformat()))]


def aggregate(rows, filters):
    groups = {}
    for status in {row["status"] for row in rows}:
        matching = [row for row in rows if row["status"] == status]
        groups[status] = [len(matching), len({row["owner"] for row in matching})]
    return {"rows": rows, "total": len(rows), "students": len({row["owner"] for row in rows}),
            "groups": groups, "filters": filters}


def seed(stack, sessions, db_path, url):
    from app.db import StudentProfile, User
    from app.seed import seed as seed_accounts
    from app.worker import drain

    year = TEST_CLOCK.astimezone(ZoneInfo("Asia/Shanghai")).year
    previous = year - 1
    accounts = seed_accounts(sessions)
    teacher, teacher_id = login(stack, url, "teacher", accounts["teacher"])
    with sessions.begin() as session:
        users = session.scalars(select(User).where(User.role == "student")).all()
        by_degree = {session.get(StudentProfile, user.id).degree: user for user in users}
        doctoral, masters = by_degree["博士"], by_degree["硕士"]
        doctoral.name, masters.name = "联调学生甲", "联调学生乙"
        session.get(StudentProfile, doctoral.id).year = f"{year}级"
        session.get(StudentProfile, masters.id).year = f"{previous}级"
        doctoral_id, doctoral_login, masters_login = doctoral.id, doctoral.username, masters.username
        manager_id = session.scalar(select(User.id).where(User.username == "manager"))
    doctoral_client, _ = login(stack, url, doctoral_login, accounts[doctoral_login])
    masters_client, _ = login(stack, url, masters_login, accounts[masters_login])
    for student, title, status, dates in [
        (doctoral_client, "合成甲当年发表", "published",
         {"publication_date": f"{year}-03-14", "acceptance_date": f"{previous}-12-15"}),
        (doctoral_client, "合成甲当年发表", "published", {"publication_date": f"{year}-03-14"}),
        (doctoral_client, "合成甲当年录用", "accepted",
         {"acceptance_date": f"{year}-04-02", "submission_date": f"{previous}-11-03"}),
        (doctoral_client, "合成甲上年发表", "published", {"publication_date": f"{previous}-12-20"}),
        (masters_client, "合成乙当年发表", "published", {"publication_date": f"{year}-05-09"}),
        (masters_client, "合成乙当年投稿", "submitted", {"submission_date": f"{year}-06-11"}),
        (masters_client, "合成乙上年发表", "published", {"publication_date": f"{previous}-11-30"}),
    ]:
        add_paper(student, teacher, teacher_id, title, status, dates)
    add_paper(doctoral_client, teacher, teacher_id, "合成甲未批准", "published",
              {"publication_date": f"{year}-07-01"}, approved=False)
    drain(sessions)

    dates = {"field": "status_date", "from": f"{year}-01-01", "to": f"{year}-12-31"}
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        teacher_rows = archive_rows(connection, teacher_id)
        manager_rows = archive_rows(connection, manager_id)
    annual = [row for row in teacher_rows if dates["from"] <= row["date"] <= dates["to"]]
    doctoral = [row for row in annual if row["degree"] == "博士"]
    drill = [row for row in doctoral if row["status"] == "published"]
    assert len(drill) >= 2 and len({(row["title"], row["owner"]) for row in drill}) < len(drill)
    assert {row["status"] for row in annual} == {"submitted", "accepted", "published"}
    expected = {
        "dates": dates, "clock": TEST_CLOCK.isoformat(), "overview": aggregate(annual, []),
        "doctoral": aggregate(doctoral, ["degree:eq:博士"]), "drill": drill,
        "studentName": "联调学生甲", "studentId": doctoral_id,
        "namedPapers": [row["title"] for row in teacher_rows
                        if row["owner"] == doctoral_id and row["status"] == "published"],
        "published": [row["title"] for row in manager_rows if row["status"] == "published"
                      and dates["from"] <= row["date"] <= dates["to"]],
    }
    return teacher_id, {
        "accounts": {key: accounts[key] for key in ("teacher", "manager", doctoral_login)},
        "studentLogin": doctoral_login, "fixture": expected,
    }


def main():
    from receipt_trace import evidence, trace_output

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invalid-receipt", action="store_true",
                        help="Inject one empty paper receipt and verify the first turn returns the expected 502.")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime", type=Path, default=REPO.parent / "inno-agent-audit-20261015")
    parser.add_argument("--provider-config", type=Path, default=REPO / "runtime/innoagent/config/config.json")
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", "--verify", f"{args.commit}^{{commit}}"],
                                     cwd=REPO, text=True).strip()
    output = args.output.resolve() if args.output else Path(mkdtemp(prefix="innograd-paper-acceptance-"))
    if args.output:
        output.mkdir(mode=0o700, parents=True)
    print(f"Testing commit {commit}. Evidence: {output}", flush=True)
    trace_output(output / "trace.jsonl")
    try:
        summary = run(args, commit, output)
    finally:
        traced = evidence(output, args.invalid_receipt)
    passed = summary["browser_returncode"] == 0 and summary["browser_checks"] > 0 and traced and summary["valid_calls"]
    save(output / "run-summary.json", {
        "commit": commit, "status": "passed" if passed else "failed",
        "test_clock": TEST_CLOCK.isoformat(), "invalid_receipt": args.invalid_receipt, **summary,
    })
    print(f"Real MCP paper calls: {summary['mcp_paper_calls']}. Summary: {output / 'run-summary.json'}", flush=True)
    return 0 if passed else summary["browser_returncode"] or 1


def run(args, commit, output):
    callbacks = []
    with TemporaryDirectory(prefix="innograd-paper-runtime-") as workdir, ExitStack() as stack:
        home = Path(workdir)
        unpack_and_build(home, commit)
        db_path = home / "fixture.db"
        listener = stack.enter_context(socket.socket())
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        agent, grants = stack.enter_context(innoagent(
            home / "agent", home, args.runtime.resolve(), args.provider_config.resolve(), url, output / "trace.jsonl",
        ))
        sessions = stack.enter_context(api_runtime(home, db_path, listener, agent, grants, callbacks,
                                                  invalid_receipt=args.invalid_receipt))
        teacher_id, inputs = seed(stack, sessions, db_path, url)
        print("Independent archived roster ready. Starting Chromium.", flush=True)
        browser = subprocess.run(
            ["node", str(HERE / "browser_acceptance.cjs")], cwd=home,
            env={**os.environ, "NODE_PATH": os.environ.get(
                "PLAYWRIGHT_NODE_PATH", str(Path.home() / ".bun/install/global/node_modules")),
                "TEST_WORKSPACE_URL": url, "TEST_FIXTURE_DB": str(db_path),
                "TEST_TEACHER_ID": teacher_id, "EVIDENCE_DIR": str(output),
                "TEST_INVALID_RECEIPT": "1" if args.invalid_receipt else "0"},
            text=True, input=json.dumps(inputs, ensure_ascii=False), capture_output=True,
        )
        for stream, text in (("stdout", browser.stdout), ("stderr", browser.stderr)):
            sanitized = text.replace(url, "<local-origin>")
            (output / f"browser.{stream}.log").write_text(sanitized, encoding="utf-8")
            print(sanitized, end="", file=getattr(sys, stream), flush=True)
        observations = output / "browser-observations.json"
        checks = json.loads(observations.read_text(encoding="utf-8"))["checks"] if observations.exists() else []
        return {
            "valid_calls": bool(callbacks) and all(callbacks), "browser_checks": len(checks),
            "browser_passed": sum(check["pass"] for check in checks), "browser_returncode": browser.returncode,
            "published_drill_rows": len(inputs["fixture"]["drill"]), "mcp_paper_calls": sum(callbacks),
        }


if __name__ == "__main__":
    raise SystemExit(main())
