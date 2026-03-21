"""메인 크롤링 함수 (2-Phase 아키텍처).

Phase 1: 메타데이터 수집 (병렬) -- RSS/페이지 파싱으로 기사 URL + 유튜브 video ID 확보
Phase 2: 본문 수집 (동시) -- 웹 워커풀(병렬) + 유튜브 워커(순차, 딜레이) 동시 실행
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from log import get_logger

logger = get_logger("crawler")

from .handlers import (
    _fetch_youtube_content,
    _handle_youtube,
    _scrape_alphaxiv,
    _scrape_arxiv,
    _scrape_huggingface,
)
from .metrics import CrawlMetrics
from .rss import _fetch_rss_metadata, _find_rss_feed
from .utils import (
    ARTICLE_URL_PATTERN,
    MIN_TITLE_LENGTH,
    VALID_YEAR_RANGE,
    _error_entry,
    _extract_content,
    _extract_summary,
    _extract_title,
    _extract_youtube_video_id,
    get_delay_factor,
    get_max_articles_per_source,
    normalize_utc,
    set_runtime_crawl_options,
)


# ─── 공개 API ──────────────────────────────────────────────────────────────

def load_prev_urls(json_path: str) -> set[str]:
    """이전 크롤링 결과에서 URL 집합을 로드한다."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            articles = json.load(f)
        urls = {a["url"] for a in articles if a.get("url")}
        logger.info("이전 데이터 로드: %s (%d개 URL)", json_path, len(urls))
        return urls
    except FileNotFoundError:
        logger.info("이전 데이터 파일 없음: %s", json_path)
        return set()
    except (json.JSONDecodeError, KeyError) as e:
        logger.info("이전 데이터 로드 실패: %s", e)
        return set()


def find_latest_crawled_json(crawled_dir: str) -> str | None:
    """crawled_dir에서 가장 최근 JSON 파일 경로를 반환한다."""
    out_path = Path(crawled_dir)
    if not out_path.exists():
        return None
    json_files = sorted(out_path.glob("*.json"), reverse=True)
    # 오늘 날짜 파일은 제외 (현재 실행 결과일 수 있음)
    today_str = date.today().isoformat()
    for f in json_files:
        if not f.stem.startswith(today_str):
            return str(f)
    return None


def crawl_sources(
    sources: list[dict],
    config: dict,
    days: int = 7,
    prev_urls: set[str] | None = None,
) -> list[dict]:
    """소스 목록에서 최근 N일 기사를 2-Phase로 수집한다.

    prev_urls가 주어지면 이미 수집된 URL은 Phase 2 본문 수집을 스킵한다.
    """
    timeout: int = config.get("timeout", 10)
    delay: float = config.get("delay", 1.5)
    max_len: int = config.get("max_content_length", 2000)
    user_agent: str = config.get("user_agent", "NewsCurating/1.0")
    max_workers: int = config.get("max_workers", 5)
    yt_delay: float = config.get("yt_delay", 2.0)
    cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=days)

    headers = {
        "User-Agent": user_agent,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    set_runtime_crawl_options(config)

    metrics = CrawlMetrics()

    # ── Phase 1: 메타데이터 수집 (병렬) ──────────────────────────────
    logger.info("\n━━━ Phase 1: 메타데이터 수집 ━━━")
    metrics.phase1_start = time.time()

    all_articles: list[dict] = []
    yt_queue: list[tuple[int, str]] = []
    web_queue: list[tuple[int, str]] = []
    total = len(sources)

    def _collect_metadata(i: int, source: dict) -> list[dict]:
        session: requests.Session = requests.Session()
        session.headers.update(headers)
        url = source["url"]
        group = source.get("folder", "")
        logger.info("[%d/%d] 메타데이터: %s", i, total, url[:70])

        try:
            articles = _process_source_metadata(
                session, url, group, cutoff, timeout, delay, max_len
            )
            logger.info("[%d/%d] → %d개 발견", i, total, len(articles))
            return articles
        except (requests.Timeout, requests.ConnectionError) as e:
            logger.info("[%d/%d] → 네트워크 오류: %s", i, total, e)
            return [_make_error_article(url, group, source, e)]
        except requests.RequestException as e:
            logger.info("[%d/%d] → 요청 실패: %s", i, total, e)
            return [_make_error_article(url, group, source, e)]
        except Exception as e:
            logger.info("[%d/%d] → 실패: %s", i, total, e)
            return [_make_error_article(url, group, source, e)]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_collect_metadata, i, src): i
            for i, src in enumerate(sources, 1)
        }
        for future in as_completed(futures):
            all_articles.extend(future.result())

    # 본문/자막 큐 분류 (증분 크롤링: 이전 URL은 스킵)
    skipped_count = 0
    for idx, article in enumerate(all_articles):
        if not article.pop("_need_content", False):
            continue
        if prev_urls and article["url"] in prev_urls:
            skipped_count += 1
            article["fetch_status"] = "skipped:incremental"
            continue
        yt_vid = _extract_youtube_video_id(article["url"])
        if yt_vid:
            yt_queue.append((idx, yt_vid))
        else:
            web_queue.append((idx, article["url"]))

    metrics.phase1_end = time.time()
    skip_msg = ", 증분 스킵 %d개" % skipped_count if skipped_count else ""
    logger.info(
        "\nPhase 1 완료: 기사 %d개 (웹 본문 %d개 + 유튜브 자막 %d개 대기%s)",
        len(all_articles), len(web_queue), len(yt_queue), skip_msg,
    )

    # ── Phase 2: 본문 수집 (웹 병렬 + 유튜브 순차, 동시 실행) ────────
    logger.info("\n━━━ Phase 2: 본문 수집 ━━━")
    metrics.phase2_start = time.time()

    # 스레드에서 수집한 결과를 안전하게 저장할 dict (idx → content)
    web_results: dict[int, str] = {}
    yt_results: dict[int, str] = {}
    _results_lock = Lock()

    # 웹 본문 fetch 워커 (병렬)
    def _web_worker() -> None:
        def _fetch_one(item: tuple[int, tuple[int, str]]) -> None:
            i, (idx, url) = item
            session = requests.Session()
            session.headers.update(headers)
            try:
                content = _fetch_article_content(session, url, timeout, max_len)
                if content:
                    with _results_lock:
                        web_results[idx] = content
                metrics.inc_web(ok=bool(content))
            except (requests.Timeout, requests.ConnectionError):
                metrics.inc_web(ok=False)
            except requests.RequestException:
                metrics.inc_web(ok=False)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(_fetch_one, enumerate(web_queue, 1)))
        metrics.web_end = time.time()
        logger.info("  [웹] 전체 %d건 완료", len(web_queue))

    # 유튜브 콘텐츠 fetch 워커 (병렬)
    yt_workers: int = config.get("yt_workers", 5)

    def _yt_worker() -> None:
        total_yt = len(yt_queue)

        def _fetch_one_yt(item: tuple[int, tuple[int, str]]) -> None:
            i, (idx, vid) = item
            title_short = all_articles[idx]["title"][:40]

            content, method = _fetch_youtube_content(vid, max_len)

            if content:
                with _results_lock:
                    yt_results[idx] = content
                metrics.inc_yt(ok=True)
                logger.info("  [YT] %d/%d %s: %s", i, total_yt, method, title_short)
            else:
                fallback = all_articles[idx].get("_yt_description", "")
                if fallback:
                    with _results_lock:
                        yt_results[idx] = fallback
                    metrics.inc_yt(ok=True)
                    logger.info("  [YT] %d/%d RSS 폴백: %s", i, total_yt, title_short)
                else:
                    metrics.inc_yt(ok=False)
                    logger.info("  [YT] %d/%d 실패: %s", i, total_yt, title_short)

        with ThreadPoolExecutor(max_workers=yt_workers) as pool:
            list(pool.map(_fetch_one_yt, enumerate(yt_queue, 1)))
        metrics.yt_end = time.time()
        logger.info("  [YT] 전체 %d건 완료", total_yt)

    # 웹은 ThreadPool, 유튜브는 단일 스레드 -- 동시 시작
    yt_thread = Thread(target=_yt_worker, daemon=True)
    web_thread = Thread(target=_web_worker, daemon=True)

    if yt_queue:
        yt_thread.start()
    else:
        metrics.yt_end = metrics.phase2_start

    if web_queue:
        web_thread.start()
    else:
        metrics.web_end = metrics.phase2_start

    if yt_queue:
        yt_thread.join()
    if web_queue:
        web_thread.join()

    # 타이밍 보정 (스레드가 없었을 경우)
    if not web_queue:
        metrics.web_end = metrics.phase2_start
    if not yt_queue:
        metrics.yt_end = metrics.phase2_start

    # 스레드 결과를 메인 스레드에서 안전하게 병합
    for idx, content in web_results.items():
        all_articles[idx]["content"] = content
    for idx, content in yt_results.items():
        all_articles[idx]["content"] = content
        all_articles[idx].pop("_yt_description", None)

    # _need_content 플래그 정리 (혹시 남아있으면)
    for article in all_articles:
        article.pop("_need_content", None)
        article.pop("_yt_description", None)

    logger.info("\n%s", metrics.report())
    return all_articles


def save_crawled_data(articles: list[dict], output_dir: str) -> str:
    """크롤링 결과를 날짜별 JSON 파일로 저장한다."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    filename = f"{date.today().isoformat()}.json"
    filepath = out_path / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    ok = sum(1 for a in articles if a["fetch_status"] == "ok")
    yt = sum(1 for a in articles if a["fetch_status"] == "youtube_channel")
    skipped = sum(1 for a in articles if a["fetch_status"] == "skipped:incremental")
    err = len(articles) - ok - yt - skipped
    skip_msg = " | 증분 스킵 %d개" % skipped if skipped else ""
    logger.info(
        "\n수집 완료: 기사 %d개 | 유튜브 %d개 | 실패 %d개%s → %s",
        ok, yt, err, skip_msg, filepath,
    )
    has_content = sum(1 for a in articles if len(a.get("content", "").strip()) >= 50)
    content_pct = (has_content / len(articles) * 100) if articles else 0
    logger.info("  본문 보유: %d/%d개 (%.0f%%)", has_content, len(articles), content_pct)
    return str(filepath)


# ─── Phase 1: 메타데이터 전용 소스 처리 ──────────────────────────────────

def _make_error_article(url: str, group: str, source: dict, error: Exception) -> dict:
    """소스 처리 실패 시 에러 기사 항목을 생성한다."""
    return {
        "source_url": url,
        "source_group": group,
        "url": url,
        "title": source.get("title", ""),
        "date": "",
        "summary": "",
        "content": "",
        "fetch_status": f"error:{type(error).__name__}",
        "_need_content": False,
    }


def _process_source_metadata(
    session: requests.Session,
    url: str,
    group: str,
    cutoff: datetime,
    timeout: int,
    delay: float,
    max_len: int,
) -> list[dict]:
    """소스 메타데이터만 수집한다 (본문/자막은 Phase 2에서)."""

    # 1) RSS 피드 시도
    rss_url = _find_rss_feed(session, url, timeout)
    if rss_url:
        logger.info("  RSS 발견: %s", rss_url[:60])
        articles = _fetch_rss_metadata(session, rss_url, url, group, cutoff, timeout)
        if articles:
            return articles

    # 2) 특수 사이트 핸들러
    domain = urlparse(url).netloc
    if "arxiv.org" in domain:
        return _scrape_arxiv(session, url, group, cutoff, timeout, delay, max_len)
    if "huggingface.co" in domain:
        return _scrape_huggingface(session, url, group, cutoff, timeout, delay, max_len)
    if "alphaxiv.org" in domain:
        return _scrape_alphaxiv(session, url, group, cutoff, timeout, delay, max_len)
    if "youtube.com" in domain:
        return _handle_youtube(url, group, session=session, timeout=timeout, cutoff=cutoff, max_len=max_len)

    # 3) 일반 뉴스 사이트 -- 링크 추출 + 메타데이터만
    return _scrape_news_metadata(session, url, group, cutoff, timeout, delay, max_len)


def _scrape_news_metadata(
    session: requests.Session,
    url: str,
    group: str,
    cutoff: datetime,
    timeout: int,
    delay: float,
    max_len: int,
) -> list[dict]:
    """뉴스 사이트에서 기사 링크 + 메타데이터를 수집한다."""
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
    except (requests.Timeout, requests.ConnectionError) as e:
        return [_error_entry(url, group, str(e))]
    except requests.RequestException as e:
        return [_error_entry(url, group, str(e))]

    article_links = _extract_article_links(soup, url)
    logger.info("  페이지에서 %d개 기사 링크 발견", len(article_links))

    articles: list[dict] = []
    for link_url, link_title in article_links[: get_max_articles_per_source()]:
        time.sleep(delay * get_delay_factor())
        try:
            article = _fetch_article_metadata(session, link_url, link_title, group, url, cutoff, timeout)
            if article:
                articles.append(article)
        except (requests.Timeout, requests.ConnectionError):
            continue
        except requests.RequestException:
            continue

    return articles


def _fetch_article_metadata(
    session: requests.Session,
    url: str,
    title: str,
    group: str,
    source_url: str,
    cutoff: datetime,
    timeout: int,
) -> dict | None:
    """개별 기사 메타데이터만 수집 (본문은 Phase 2)."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")

    article_date = _extract_date_from_page(soup)
    if article_date and article_date < cutoff:
        return None

    page_title = _extract_title(soup) or title
    summary = _extract_summary(soup)

    return {
        "source_url": source_url,
        "source_group": group,
        "url": url,
        "title": page_title,
        "date": article_date.isoformat() if article_date else "",
        "summary": summary,
        "content": "",  # Phase 2에서 채움
        "fetch_status": "ok",
        "_need_content": True,
    }


# ─── 일반 뉴스 사이트 유틸 ────────────────────────────────────────────────

def _extract_article_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """페이지에서 기사 링크를 추출한다."""
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    base_domain = urlparse(base_url).netloc

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc != base_domain:
            continue
        if full_url in seen:
            continue

        is_article = bool(ARTICLE_URL_PATTERN.search(full_url))

        if not is_article:
            continue

        title = a.get_text(strip=True)
        if len(title) < MIN_TITLE_LENGTH:
            continue

        seen.add(full_url)
        links.append((full_url, title))

    return links


def _extract_date_from_page(soup: BeautifulSoup) -> datetime | None:
    """페이지에서 발행일을 추출한다."""
    for attr in [
        {"property": "article:published_time"},
        {"property": "og:article:published_time"},
        {"name": "pubdate"},
        {"name": "date"},
        {"property": "dc.date"},
        {"name": "DC.date"},
    ]:
        tag = soup.find("meta", attrs=attr)
        if tag and tag.get("content"):
            try:
                return normalize_utc(dateparser.parse(tag["content"]))
            except (ValueError, AttributeError, TypeError):
                pass

    for time_tag in soup.find_all("time", datetime=True):
        try:
            return normalize_utc(dateparser.parse(time_tag["datetime"]))
        except (ValueError, AttributeError, TypeError):
            pass

    text = soup.get_text()
    date_patterns = [
        r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if VALID_YEAR_RANGE[0] <= y <= VALID_YEAR_RANGE[1] and 1 <= m <= 12 and 1 <= d <= 31:
                    return datetime(y, m, d, tzinfo=timezone.utc)
            except (ValueError, OverflowError):
                pass

    return None


def _fetch_article_content(
    session: requests.Session,
    url: str,
    timeout: int,
    max_len: int,
) -> str:
    """개별 기사의 본문을 가져온다."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    return _extract_content(soup, max_len)
