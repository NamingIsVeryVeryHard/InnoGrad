#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$ROOT/InnoGrad-portable-20261104"
if [[ ! -x "$PROJECT/.venv/bin/python" ]]; then
  print '未找到项目环境，请参阅本目录的《本机演示说明.md》。'
  read -r '?按回车退出'
  exit 1
fi
"$PROJECT/.venv/bin/python" "$PROJECT/deploy/local_demo.py" start || {
  read -r '?启动未完成，按回车关闭窗口'
  exit 1
}
