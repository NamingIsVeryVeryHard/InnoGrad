#!/bin/zsh
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR/backend"
if [[ ! -x ../.venv/bin/python ]]; then
  print '未找到项目 Python 环境，请按 README.md 完成依赖安装。'
  read -r '?按回车退出'
  exit 1
fi
../.venv/bin/python -m app.run_local
