"""RSS 피드 관련 기능."""

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from feedparser import FeedParserDict

from .utils import normalize_utc


def _find_rss_feed(session: requests.Session, url: str, timeout: int) -> str | None:
    """페이지에서 RSS 피드 URL을 찾는다."""
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for link in soup.find_all("link", type=re.compile(r"(rss|atom)", re.I)):
            href = link.get("href")
            if href:
                return urljoin(url, href)

        for link in soup.find_all("link", attrs={"rel": "alternate"}):
            if link.get("type") and "xml" in link.get("type", ""):
                href = link.get("href")
                if href and ".rss" in href:
                    return urljoin(url, href)

        parsed = urlparse(url)
        if re.match(r"/c/.+/\d+$", parsed.path):
            return url + ".rss"

    except (requests.RequestException, Exception):
        pass
    return None


def _fetch_rss_metadata(
    session: requests.Session,
    rss_url: str,
    source_url: str,
    group: str,
    cutoff: datetime,
    timeout: int,
) -> list[dict]:
    """RSS 피드에서 메타데이터만 수집한다 (본문은 _need_content 플래그)."""
    try:
        resp = session.get(rss_url, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except (requests.RequestException, Exception):
        return []

    articles: list[dict] = []
    for entry in feed.entries:
        pub_date = _parse_feed_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        summary = entry.get("summary", "")
        if summary:
            summary = BeautifulSoup(summary, "lxml").get_text(strip=True)[:500]

        articles.append({
            "source_url": source_url,
            "source_group": group,
            "url": link,
            "title": title,
            "date": pub_date.isoformat() if pub_date else "",
            "summary": summary[:500],
            "content": "",  # Phase 2에서 채움
            "fetch_status": "ok",
            "_need_content": bool(link),
        })

    return articles


def _parse_feed_date(entry: FeedParserDict) -> datetime | None:
    """feedparser 엔트리에서 날짜를 추출한다."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return dt
            except (TypeError, ValueError):
                pass

    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                return normalize_utc(dateparser.parse(raw))
            except (ValueError, AttributeError, TypeError):
                pass
    return None
