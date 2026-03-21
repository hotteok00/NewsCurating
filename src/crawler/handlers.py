"""특수 사이트 핸들러 (arxiv, huggingface, alphaxiv, youtube)."""

import re
import shutil
import subprocess
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:  # pragma: no cover - optional dependency fallback
    YouTubeTranscriptApi = None

from log import get_logger

logger = get_logger("crawler")

from .utils import (
    get_delay_factor,
    get_max_articles_per_source,
)


def _scrape_limited_list(
    items: list[tuple[str, str]],
    url: str,
    group: str,
    *,
    date_str: str = "",
    need_content: bool = False,
) -> list[dict]:
    """공통: 제목+URL 리스트에서 MAX_ARTICLES_PER_SOURCE 개까지 기사 항목을 생성한다.

    items: [(paper_url, title), ...]
    """
    articles: list[dict] = []
    seen_urls: set[str] = set()
    max_articles = get_max_articles_per_source()
    for paper_url, title in items:
        if len(title) < 10 or paper_url in seen_urls:
            continue
        seen_urls.add(paper_url)

        articles.append({
            "source_url": url,
            "source_group": group,
            "url": paper_url,
            "title": title,
            "date": date_str,
            "summary": "",
            "content": title if not need_content else "",
            "fetch_status": "ok",
            "_need_content": need_content,
        })

        if len(articles) >= max_articles:
            break

    return articles


def _scrape_arxiv(
    session: requests.Session,
    url: str,
    group: str,
    cutoff: datetime,
    timeout: int,
    delay: float,
    max_len: int,
) -> list[dict]:
    """arxiv 최근 논문 목록을 파싱한다."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    articles: list[dict] = []
    for dt_tag in soup.find_all("dt"):
        dd = dt_tag.find_next_sibling("dd")
        if not dd:
            continue

        a = dt_tag.find("a", title="Abstract")
        if not a:
            continue
        paper_url = urljoin("https://arxiv.org", a["href"])

        title_div = dd.find("div", class_="list-title")
        title = title_div.get_text(strip=True).replace("Title:", "").strip() if title_div else ""

        authors_div = dd.find("div", class_="list-authors")
        authors = authors_div.get_text(strip=True).replace("Authors:", "").strip() if authors_div else ""

        summary = ""
        try:
            time.sleep(delay * get_delay_factor())
            abs_resp = session.get(paper_url, timeout=timeout)
            abs_resp.raise_for_status()
            abs_soup = BeautifulSoup(abs_resp.text, "lxml")
            abs_block = abs_soup.find("blockquote", class_="abstract")
            if abs_block:
                summary = abs_block.get_text(strip=True).replace("Abstract:", "").strip()[:max_len]
        except (requests.Timeout, requests.ConnectionError, requests.RequestException):
            pass

        articles.append({
            "source_url": url,
            "source_group": group,
            "url": paper_url,
            "title": title,
            "date": date.today().isoformat(),
            "summary": summary,
            "content": f"Authors: {authors}\n\n{summary}",
            "fetch_status": "ok",
            "_need_content": False,
        })

        if len(articles) >= get_max_articles_per_source():
            break

    return articles


def _scrape_huggingface(
    session: requests.Session,
    url: str,
    group: str,
    cutoff: datetime,
    timeout: int,
    delay: float,
    max_len: int,
) -> list[dict]:
    """HuggingFace Papers 페이지를 파싱한다."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    items: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=re.compile(r"/papers/")):
        paper_url = urljoin("https://huggingface.co", a["href"])
        title = a.get_text(strip=True)
        items.append((paper_url, title))

    return _scrape_limited_list(
        items, url, group,
        date_str=date.today().isoformat(),
    )


def _scrape_alphaxiv(
    session: requests.Session,
    url: str,
    group: str,
    cutoff: datetime,
    timeout: int,
    delay: float,
    max_len: int,
) -> list[dict]:
    """alphaXiv 트렌딩 페이지를 파싱한다."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    items: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=re.compile(r"(abs|paper)")):
        href = a["href"]
        paper_url = urljoin(url, href)
        title = a.get_text(strip=True)
        items.append((paper_url, title))

    return _scrape_limited_list(items, url, group)


def _handle_youtube(
    url: str,
    group: str,
    session: requests.Session | None = None,
    timeout: int = 10,
    cutoff=None,
    max_len: int = 2000,
) -> list[dict]:
    """유튜브 채널에서 RSS로 최신 영상 목록을 가져온다.

    1) 채널 페이지에서 channel_id 추출
    2) YouTube RSS 피드로 최근 영상 목록 + 설명문 수집
    3) 실패 시 기존 방식(URL만 기록)으로 폴백
    """
    if session is None:
        session = requests.Session()

    channel_id = _extract_channel_id(session, url, timeout)
    if not channel_id:
        logger.info("  [YT] channel_id 추출 실패, 폴백: %s", url[:60])
        return [_youtube_channel_fallback(url, group)]

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    articles = _fetch_youtube_rss(session, rss_url, url, group, cutoff, timeout, max_len)

    if articles:
        logger.info("  [YT] RSS에서 %d개 영상 발견: %s", len(articles), url[:60])
        return articles

    logger.info("  [YT] RSS 영상 없음, 폴백: %s", url[:60])
    return [_youtube_channel_fallback(url, group)]


def _youtube_channel_fallback(url: str, group: str) -> dict:
    """유튜브 채널 폴백: URL만 기록."""
    return {
        "source_url": url,
        "source_group": group,
        "url": url,
        "title": url.split("/@")[-1].split("/")[0] if "/@" in url else "YouTube Channel",
        "date": "",
        "summary": "유튜브 채널 - RSS 수집 실패",
        "content": "",
        "fetch_status": "youtube_channel",
        "_need_content": False,
    }


def _extract_channel_id(session: requests.Session, url: str, timeout: int) -> str | None:
    """채널 페이지 HTML에서 channel_id를 추출한다."""
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        text = resp.text

        # 방법 1: meta itemprop="channelId"
        match = re.search(r'<meta\s+itemprop="channelId"\s+content="([^"]+)"', text)
        if match:
            return match.group(1)

        # 방법 2: JSON 내 externalId
        match = re.search(r'"externalId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', text)
        if match:
            return match.group(1)

        # 방법 3: canonical URL에서 추출
        match = re.search(r'youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})', text)
        if match:
            return match.group(1)

    except (requests.RequestException, Exception):
        pass
    return None


def _fetch_youtube_rss(
    session: requests.Session,
    rss_url: str,
    source_url: str,
    group: str,
    cutoff,
    timeout: int,
    max_len: int,
) -> list[dict]:
    """YouTube RSS 피드에서 영상 목록 + 설명문을 가져온다."""
    try:
        resp = session.get(rss_url, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except (requests.RequestException, Exception):
        return []

    articles = []
    for entry in feed.entries[: get_max_articles_per_source()]:
        # 날짜 파싱
        pub_date = None
        for field in ("published_parsed", "updated_parsed"):
            parsed = entry.get(field)
            if parsed:
                try:
                    pub_date = datetime(
                        *parsed[:6], tzinfo=timezone.utc
                    )
                except (TypeError, ValueError):
                    pass
                break

        if cutoff and pub_date and pub_date < cutoff:
            continue

        video_url = entry.get("link", "")
        title = entry.get("title", "").strip()

        # 설명문 추출: media_description > summary
        description = ""
        media_group = entry.get("media_group")
        if media_group:
            if isinstance(media_group, list):
                for mg in media_group:
                    desc_list = mg.get("media_description", [])
                    if desc_list and isinstance(desc_list, list):
                        desc_entry = desc_list[0]
                        if isinstance(desc_entry, dict):
                            description = desc_entry.get("content", "")
                        elif isinstance(desc_entry, str):
                            description = desc_entry
                    if description:
                        break
            elif isinstance(media_group, dict):
                desc_list = media_group.get("media_description", [])
                if desc_list and isinstance(desc_list, list):
                    desc_entry = desc_list[0]
                    if isinstance(desc_entry, dict):
                        description = desc_entry.get("content", "")
                    elif isinstance(desc_entry, str):
                        description = desc_entry

        if not description:
            description = entry.get("summary", "")
            if description:
                description = BeautifulSoup(description, "lxml").get_text(strip=True)

        articles.append({
            "source_url": source_url,
            "source_group": group,
            "url": video_url,
            "title": title,
            "date": pub_date.isoformat() if pub_date else "",
            "summary": description[:500],
            "content": "",  # Phase 2에서 자막 시도
            "fetch_status": "ok",
            "_need_content": True,
            "_yt_description": description[:max_len],  # 자막 실패 시 폴백용
        })

    return articles


def _fetch_youtube_content(video_id: str, max_len: int) -> tuple[str, str]:
    """유튜브 영상 콘텐츠를 가져온다 (yt-dlp 1회 호출 → transcript-api 폴백).

    Returns:
        (content, method) — method: "subtitle", "auto-subtitle",
                           "description", "transcript-api", ""
    """
    # 1차: yt-dlp 1회 호출로 자막+설명문 동시 추출
    content, method = _ytdlp_fetch_all(video_id, max_len)
    if content:
        return content, method

    # 2차: 기존 transcript-api (폴백)
    content = _fetch_youtube_transcript_legacy(video_id, max_len)
    if content:
        return content, "transcript-api"

    return "", ""


def _ytdlp_fetch_all(video_id: str, max_len: int) -> tuple[str, str]:
    """yt-dlp 1회 호출로 자막과 설명문을 동시에 추출한다.

    --print description + --write-sub --write-auto-sub을 한 번에 실행.
    자막이 있으면 자막 우선, 없으면 설명문 사용.

    Returns:
        (content, method) — method: "subtitle", "auto-subtitle", "description", ""
    """
    ytdlp_path = shutil.which("yt-dlp")
    if not ytdlp_path:
        return "", ""

    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_tpl = str(Path(tmpdir) / "sub")

        try:
            result = subprocess.run(
                [
                    ytdlp_path,
                    "--print", "description",
                    "--write-sub", "--write-auto-sub",
                    "--sub-lang", "ko,en",
                    "--sub-format", "vtt",
                    "--skip-download",
                    "-o", output_tpl,
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "", ""

        # 자막 확인 (자막 우선)
        tmppath = Path(tmpdir)
        for lang in ["ko", "en"]:
            manual = tmppath / f"sub.{lang}.vtt"
            if manual.exists():
                text = _parse_vtt(manual, max_len)
                if text:
                    return text, "subtitle"

        for lang in ["ko", "en"]:
            for vtt_file in sorted(tmppath.glob(f"*.{lang}*.vtt")):
                text = _parse_vtt(vtt_file, max_len)
                if text:
                    return text, "auto-subtitle"

        for vtt_file in sorted(tmppath.glob("*.vtt")):
            text = _parse_vtt(vtt_file, max_len)
            if text:
                return text, "auto-subtitle"

        # 자막 없으면 설명문 사용 (stdout에서)
        description = result.stdout.strip()[:max_len] if result.stdout else ""
        if description and len(description) >= 30:
            return description, "description"

    return "", ""


def _parse_vtt(vtt_path: Path, max_len: int) -> str:
    """WebVTT 파일에서 순수 텍스트를 추출한다.

    타임스탬프, 빈 줄, 중복 라인을 제거하고 순수 대사만 반환한다.
    """
    try:
        raw = vtt_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = raw.split("\n")
    texts: list[str] = []
    prev_line = ""

    for line in lines:
        line = line.strip()
        # WebVTT 헤더, 타임스탬프, 빈 줄 건너뛰기
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->", line):
            continue
        if re.match(r"^\d+$", line):
            continue

        # HTML 태그 제거
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if not clean:
            continue

        # 중복 라인 제거 (auto-sub은 중복이 많음)
        if clean != prev_line:
            texts.append(clean)
            prev_line = clean

    result = " ".join(texts)
    return result[:max_len]


def _fetch_youtube_transcript_legacy(video_id: str, max_len: int) -> str:
    """기존 youtube-transcript-api로 자막을 가져온다 (3차 폴백)."""
    if YouTubeTranscriptApi is None:
        return ""
    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=["ko", "en"])
        text = " ".join(snippet.text for snippet in transcript)
        return text[:max_len]
    except Exception:
        return ""


# 하위호환: 기존 import를 유지
_fetch_youtube_transcript = _fetch_youtube_content
