"""Start API + worker together; never seed or overwrite accounts."""
import json
from datetime import datetime, timezone
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    url='http://127.0.0.1:8000/prototype/'
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as response:
            if response.status==200 and json.load(response).get('status')=='ok':
                webbrowser.open(url)
                from .db import connect, WorkerHeartbeat
                engine,factory=connect()
                with factory() as session:
                    pulse=session.get(WorkerHeartbeat,'main')
                    active=bool(pulse and (datetime.now(timezone.utc)-datetime.fromisoformat(pulse.last_seen)).total_seconds()<30)
                engine.dispose()
                if active:
                    print('业务服务与 Worker 已运行。')
                    return
                child=subprocess.Popen([sys.executable,'-m','app.worker'],cwd=root)
                print('已为现有 API 启动 Worker。保持终端开启，Ctrl+C 退出。')
                try: child.wait()
                except KeyboardInterrupt:
                    child.terminate()
                    child.wait(timeout=10)
                return
    except Exception:
        pass
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,check=True)
    api=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000'],cwd=root)
    worker=subprocess.Popen([sys.executable,'-m','app.worker'],cwd=root)
    def stop(*_):
        for child in (api,worker):
            if child.poll() is None: child.terminate()
        for child in (api,worker):
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill()
        raise SystemExit(0)
    signal.signal(signal.SIGINT,stop)
    signal.signal(signal.SIGTERM,stop)
    for _ in range(30):
        if api.poll() is not None: stop()
        try:
            urllib.request.urlopen(url,timeout=1).close()
            webbrowser.open(url)
            break
        except Exception: time.sleep(.3)
    print('API 与 Worker 已启动。保持终端开启；Ctrl+C 安全退出。')
    while api.poll() is None and worker.poll() is None: time.sleep(1)
    stop()


if __name__=='__main__': main()
