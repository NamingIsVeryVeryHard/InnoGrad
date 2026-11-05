"""Reproducible isolated verification. Uses installed dependencies; no model or live DB."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
evidence = Path(tempfile.mkdtemp(prefix="graduate-acceptance-"))
env = dict(os.environ, DATABASE_URL=f"sqlite:///{evidence / 'import.db'}",
           FILE_ROOT=str(evidence / "files"), AI_MODE="rules", AI_API_KEY="",
           AI_BASE_URL="", AI_MODEL="", PYTHON_DOTENV_DISABLED="1",
           PYTHONUTF8="1")
env.pop("PYTHONPYCACHEPREFIX", None)
checks = []


def source_fingerprints():
    result = {}
    for folder, pattern in [('backend/app','*.py'),('backend/tests','*.py'),('backend/migrations','*.py'),('frontend','*.js')]:
        for path in (root.parent/folder).rglob(pattern):
            result[str(path.relative_to(root.parent))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


started_fingerprints = source_fingerprints()


def run(label, command, variables=None):
    result = subprocess.run(command, cwd=root, env=variables or env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    (evidence / (label + ".txt")).write_text(result.stdout, encoding="utf-8")
    checks.append({"check": label, "exit_code": result.returncode})
    print(f"{label}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
    return result.returncode == 0


run("pytest", [sys.executable, "-m", "pytest", "-q", "--basetemp="+str(evidence / "tests"), "--junitxml="+str(evidence / "pytest.xml")])
migration_env = dict(env, DATABASE_URL=f"sqlite:///{evidence / 'migration.db'}")
if run("migration_previous", [sys.executable,"-m","alembic","upgrade","54f51b05aa83"], migration_env):
    with sqlite3.connect(evidence / 'migration.db') as db:
        db.execute("INSERT INTO users (id,username,name,role,password_hash,enabled) VALUES (?,?,?,?,?,?)",
                   ('synthetic-migration', 'synthetic-migration', '合成迁移记录', 'student', 'not-a-login-hash', 0))
    if run("migration_head", [sys.executable,"-m","alembic","upgrade","head"], migration_env):
        run("migration_check", [sys.executable,"-m","alembic","check"], migration_env)
        with sqlite3.connect(evidence / 'migration.db') as db:
            retained = db.execute("SELECT name FROM users WHERE id='synthetic-migration'").fetchone() == ('合成迁移记录',)
        checks.append({"check":"existing_synthetic_row_preserved", "exit_code":0 if retained else 1})
node = shutil.which('node')
if node:
    for name in ('app.js','workflow.js','prototype/app.js'):
        run('syntax_'+name.replace('/','_'), [node,'--check',str(root.parent/'frontend'/name)])
    run('prototype_regression', [node,'--test',str(root.parent/'frontend/prototype/tests/model.test.cjs')])
else:
    checks.append({"check":"node_checks_unavailable", "exit_code":1})
run('python_compile', [sys.executable,'-m','compileall','-q','-b','app','migrations'])
fingerprints = source_fingerprints()
checks.append({"check":"source_unchanged_during_verification", "exit_code":0 if fingerprints == started_fingerprints else 1})
report = {"created_at":datetime.now(timezone.utc).isoformat(), "data":"synthetic only",
          "external_model_calls":False, "checks":checks, "source_sha256":fingerprints,
          "not_run":["browser E2E", "PostgreSQL/S3", "real model quality", "production load/recovery"],
          "frontend_build":"Native HTML/JS; no bundler configured; syntax checked"}
(evidence/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2), encoding="utf-8")
print('Evidence: '+str(evidence))
sys.exit(0 if all(c['exit_code']==0 for c in checks) else 1)
