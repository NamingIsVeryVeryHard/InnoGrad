"""Explicit Mac/local demonstration setup, isolated from deployment configuration."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
DATA = PROJECT / "runtime" / "local-demo"
ACCOUNTS = DATA / "演示账号.txt"


def configure():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chdir(BACKEND)
    # Always override inherited production/model settings for this demo only.
    os.environ.update(
        DATABASE_URL="sqlite:///" + str(DATA / "innograd.db"),
        FILE_ROOT=str(DATA / "files"),
        AGENT_LOCK_ROOT=str(DATA / "agent-locks"),
        AI_MODE="rules", AI_API_KEY="", AI_BASE_URL="", AI_MODEL="",
        REVIEW_WORKFLOW="manual", COOKIE_SECURE="0",
        APP_ENV="local-demo", PYTHON_DOTENV_DISABLED="1",
    )
    sys.path.insert(0, str(BACKEND))


def run(*args):
    subprocess.run([sys.executable, *args], cwd=BACKEND, check=True)


def initialize():
    run("-m", "alembic", "upgrade", "head")
    from sqlalchemy import select, func
    from app.db import connect, User
    from app.seed import seed
    from app.seed_scenarios import seed_scenarios
    from zoneinfo import ZoneInfo

    engine, factory = connect()
    try:
        with factory() as session:
            count = session.scalar(select(func.count()).select_from(User))
        if not count:
            # The seed function rejects collisions and never resets passwords.
            with os.fdopen(os.open(ACCOUNTS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                           "w", encoding="utf-8") as output:
                credentials = seed(factory)
                output.write("InnoGrad 本机合成演示账号（请勿公开此文件）\n\n")
                output.write("以下账号使用随机密码；再次启动不会重置。\n")
                for username, password in credentials.items():
                    output.write(f"{username}\t{password}\n")
                output.flush()
                os.fsync(output.fileno())
        elif not ACCOUNTS.exists():
            raise SystemExit("演示库已有账户但缺少凭据文件。请核对原文件；不会重置密码或覆盖数据。")
        result = seed_scenarios(factory, DATA / "files", DATA / "simulation-cohort-v1",
                                datetime.now(ZoneInfo("Asia/Shanghai")).date())
        print("演示数据：", result["status"])
        print("管理教师 / 导师 / 基础学生账号：", ACCOUNTS)
        print("12 位场景学生账号：", DATA / "simulation-cohort-v1" / "accounts.json")
    finally:
        engine.dispose()


def serve(port, no_browser):
    if not (DATA / "innograd.db").is_file():
        raise SystemExit("尚未初始化，请先执行 deploy/local_demo.py init。")
    # Do not attach to or terminate another application's server.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except PermissionError as error:
            raise SystemExit(f"当前执行环境不允许监听本机端口：{error}。请在 Mac 终端中运行，或双击根目录的启动脚本。")
        except OSError as error:
            raise SystemExit(f"无法使用本机端口 {port}：{error}。可用 --port 指定其他端口。")
    run("-m", "alembic", "upgrade", "head")
    children = []
    logs = []

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        for name, command in (
            ("api", ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]),
            ("worker", ["-m", "app.worker"]),
        ):
            log = (DATA / f"{name}.log").open("a", encoding="utf-8")
            logs.append(log)
            children.append(subprocess.Popen([sys.executable, *command], cwd=BACKEND,
                                              stdout=log, stderr=subprocess.STDOUT))
        url = f"http://127.0.0.1:{port}/prototype/"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 30
        ready = False
        while time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("API 或 Worker 已退出，请查看 runtime/local-demo 下的日志。")
            try:
                with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    health = json.load(response)
                from app.db import connect, WorkerHeartbeat
                from datetime import timezone
                engine, factory = connect()
                try:
                    with factory() as session:
                        pulse = session.get(WorkerHeartbeat, "main")
                        fresh = bool(pulse and (datetime.now(timezone.utc) -
                                     datetime.fromisoformat(pulse.last_seen)).total_seconds() < 10)
                finally:
                    engine.dispose()
                if health.get("environment") == "local-demo" and fresh:
                    ready = True
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.3)
        if not ready:
            raise RuntimeError("服务未在 30 秒内就绪，请查看 API 与 Worker 日志。")
        print(f"InnoGrad 本机演示已启动：{url}", flush=True)
        if ACCOUNTS.exists():
            print(f"账号文件：{ACCOUNTS}", flush=True)
        else:
            print("凭据文件未随备份恢复，请使用原账号密码登录。", flush=True)
        print("当前为离线规则与人工确认模式。保持此窗口开启，Ctrl+C 停止。", flush=True)
        if not no_browser:
            webbrowser.open(url)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError("API 或 Worker 意外退出，请检查日志后重新启动。")
    except KeyboardInterrupt:
        print("正在停止 API 与 Worker，已保存的演示数据保留。", flush=True)
    finally:
        # Complete cleanup even if Ctrl+C is pressed a second time.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for log in logs:
            log.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "start", "backup"))
    parser.add_argument("--port", type=int, default=int(os.getenv("INNOGRAD_DEMO_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    configure()
    # Init, serving and backup share a lock; no writes occur during a backup.
    with (DATA / "launcher.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("本项目的演示已运行。请使用已打开的窗口；初始化或备份前先 Ctrl+C 停止。")
        if args.action == "init":
            initialize()
        elif args.action == "start":
            serve(args.port, args.no_browser)
        else:
            backups = PROJECT / "runtime" / "backups"
            backups.mkdir(exist_ok=True, mode=0o700)
            target = backups / ("local-demo-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".tar.gz")
            run(str(PROJECT / "deploy" / "backup.py"), "--data", str(DATA), "--output", str(target))


if __name__ == "__main__":
    main()
