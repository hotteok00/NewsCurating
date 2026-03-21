"""공용 유틸리티 함수들."""

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from log import get_logger

logger = get_logger("crawler")

# ─── 상수 ──────────────────────────────────────────────────────────────────

ARTICLE_URL_PATTERN = re.compile(
    r"(article|news|post|view|read|detail|story)[/=]|"
    r"/\d{4,}/|"
    r"[?&](id|idx|no|seq|article_id)=\d+|"
    r"/\d{5,}$",
    re.I,
)

YOUTUBE_VIDEO_ID_PATTERN = re.compile(
    r"(?:v=|youtu\.be/|/v/|/embed/)([a-zA-Z0-9_-]{11})"
)

DEFAULT_DELAY_FACTOR = 0.3
DEFAULT_MAX_ARTICLES_PER_SOURCE = 15
VALID_YEAR_RANGE = (2020, 2030)
MIN_TITLE_LENGTH = 5

_RUNTIME_CRAWL_OPTIONS = {
    "delay_factor": DEFAULT_DELAY_FACTOR,
    "max_articles_per_source": DEFAULT_MAX_ARTICLES_PER_SOURCE,
}


def set_runtime_crawl_options(config: dict | None = None) -> None:
    """크롤러 런타임 옵션을 설정 파일 기준으로 갱신한다."""
    config = config or {}

    delay_factor = config.get("delay_factor", DEFAULT_DELAY_FACTOR)
    max_articles = config.get("max_articles_per_source", DEFAULT_MAX_ARTICLES_PER_SOURCE)

    try:
        delay_factor = float(delay_factor)
    except (TypeError, ValueError):
        delay_factor = DEFAULT_DELAY_FACTOR

    try:
        max_articles = int(max_articles)
    except (TypeError, ValueError):
        max_articles = DEFAULT_MAX_ARTICLES_PER_SOURCE

    _RUNTIME_CRAWL_OPTIONS["delay_factor"] = delay_factor if delay_factor > 0 else DEFAULT_DELAY_FACTOR
    _RUNTIME_CRAWL_OPTIONS["max_articles_per_source"] = (
        max_articles if max_articles > 0 else DEFAULT_MAX_ARTICLES_PER_SOURCE
    )


def get_delay_factor() -> float:
    """현재 런타임 delay factor를 반환한다."""
    return float(_RUNTIME_CRAWL_OPTIONS["delay_factor"])


def get_max_articles_per_source() -> int:
    """현재 소스별 최대 기사 수를 반환한다."""
    return int(_RUNTIME_CRAWL_OPTIONS["max_articles_per_source"])


def normalize_utc(dt: datetime) -> datetime:
    """datetime을 UTC aware 형태로 정규화한다."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ─── 콘텐츠 추출 ──────────────────────────────────────────────────────────

def _extract_title(soup: BeautifulSoup) -> str:
    """페이지에서 제목을 추출한다."""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    return ""


def _extract_summary(soup: BeautifulSoup) -> str:
    """페이지에서 요약(description)을 추출한다."""
    for attr in [
        {"property": "og:description"},
        {"name": "description"},
    ]:
        tag = soup.find("meta", attrs=attr)
        if tag and tag.get("content"):
            return tag["content"].strip()[:500]
    return ""


def _extract_content(soup: BeautifulSoup, max_length: int) -> str:
    """페이지에서 본문 텍스트를 추출한다."""
    for tag_name in ["script", "style", "nav", "header", "footer", "aside", "iframe"]:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for container in [soup.find("article"), soup.find("main"), soup.find("body")]:
        if container:
            text = container.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            return "\n".join(lines)[:max_length]

    return ""


def _error_entry(url: str, group: str, error_msg: str) -> dict:
    """에러 발생 시 기본 기사 항목을 생성한다."""
    return {
        "source_url": url,
        "source_group": group,
        "url": url,
        "title": "",
        "date": "",
        "summary": "",
        "content": "",
        "fetch_status": f"error:{error_msg}",
        "_need_content": False,
    }


def _extract_youtube_video_id(url: str) -> str | None:
    """URL에서 유튜브 video ID를 추출한다."""
    match = YOUTUBE_VIDEO_ID_PATTERN.search(url)
    return match.group(1) if match else None
