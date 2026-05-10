#!/bin/bash
# NewsCurating - 주간 뉴스 큐레이션 파이프라인
# 사용법: ./run_curate.sh [--incremental] [--prev-file FILE]

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

mkdir -p data/crawled reports logs feedback

PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

echo "========================================="
echo " NewsCurating - 주간 뉴스 큐레이션"
echo " 날짜: $(date +%Y-%m-%d)"
echo "========================================="

"$PYTHON_BIN" src/main.py pipeline --config config.yaml "$@"
