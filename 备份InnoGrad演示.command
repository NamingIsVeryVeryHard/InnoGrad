#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$ROOT/InnoGrad-portable-20261104"
"$PROJECT/.venv/bin/python" "$PROJECT/deploy/local_demo.py" backup || {
  read -r '?备份未完成，按回车关闭窗口'
  exit 1
}
read -r '?备份完成，按回车关闭窗口'
