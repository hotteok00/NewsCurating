"""크롤러 패키지 — 뉴스 소스에서 기사를 수집한다.

공개 API:
    crawl_sources       — 소스 목록에서 기사를 2-Phase로 수집
    save_crawled_data   — 크롤링 결과를 JSON 파일로 저장
    load_prev_urls      — 이전 크롤링 결과에서 URL 집합 로드
    find_latest_crawled_json — 가장 최근 크롤링 JSON 경로 반환
"""

from .core import (
    crawl_sources,
    find_latest_crawled_json,
    load_prev_urls,
    save_crawled_data,
)
from .metrics import PipelineMetrics

__all__ = [
    "crawl_sources",
    "save_crawled_data",
    "load_prev_urls",
    "find_latest_crawled_json",
    "PipelineMetrics",
]
