#!/bin/bash
# NewsCurating - 주간 뉴스 큐레이션 파이프라인
# 사용법: ./run_curate.sh [--incremental] [--prev-file FILE]

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

mkdir -p data/crawled reports logs feedback

echo "========================================="
echo " NewsCurating - 주간 뉴스 큐레이션"
echo " 날짜: $(date +%Y-%m-%d)"
echo "========================================="

python3 src/main.py pipeline --config config.yaml "$@"
