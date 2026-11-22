#!/usr/bin/env bash
# Start the current checkout, not the portable demo copy.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  --help|-h)
    echo '用法：bash code/start.sh [--setup]'
    echo '首次使用 --setup 创建 Python 环境并安装依赖；之后直接运行即可。'
    exit 0 ;;
  ''|--setup) ;;
  *) echo '未知参数，请使用 --help。' >&2; exit 2 ;;
esac
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" && -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
fi
if [[ "${1:-}" == '--setup' ]]; then
  if [[ ! -x "$PYTHON" ]]; then
    python3 -c 'import sys; assert sys.version_info >= (3,11), "需要 Python 3.11 或更新版本"'
    python3 -m venv "$ROOT/.venv"
  fi
  "$PYTHON" -m pip install -r "$ROOT/backend/requirements.lock.txt"
fi
if [[ ! -x "$PYTHON" ]]; then
  echo '尚未安装运行环境，请先执行：bash code/start.sh --setup' >&2
  exit 1
fi
if ! "$PYTHON" -c 'import uvicorn, fastapi, sqlalchemy, alembic, pydantic_settings, multipart, httpx, dotenv' 2>/dev/null; then
  echo '依赖不完整，请执行：bash code/start.sh --setup' >&2
  exit 1
fi
if [[ ! -x "$ROOT/frontend/node_modules/.bin/vite" || "${1:-}" == '--setup' ]]; then
  npm --prefix "$ROOT/frontend" ci
fi
npm --prefix "$ROOT/frontend" run build
cd "$ROOT/backend"
echo '正在启动当前仓库的前端、API 与 Worker。'
echo '前端：http://127.0.0.1:8000/prototype/'
echo 'API 文档：http://127.0.0.1:8000/docs'
echo '保持终端开启，按 Ctrl+C 停止。启动时自动升级数据库，不创建或重置账号。'
exec "$PYTHON" -m app.run_local
