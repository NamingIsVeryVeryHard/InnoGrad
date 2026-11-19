#!/bin/zsh
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$PROJECT_DIR/code/start.sh"
