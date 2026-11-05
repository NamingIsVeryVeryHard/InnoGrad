#!/bin/zsh
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  print '未找到项目 Python 环境，请参阅根目录的本机演示说明。'
  read -r '?按回车退出'
  exit 1
fi
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/deploy/local_demo.py" start || {
  read -r '?启动未完成，按回车关闭窗口'
  exit 1
}
