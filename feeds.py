"""건국대학교 RSS 피드 수집 및 파싱 모듈"""

import asyncio
import json
import logging
import os
import re
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
import certifi
import feedparser

from constants import (
    ARTICLE_BODY_TIMEOUT,
    BOARD_CONTENT_CLASS,
    EMPTY_FEED_SENTINEL,
    FEED_FETCH_TIMEOUT,
    MAX_ARTICLE_BODY_LENGTH,
    STATE_RETENTION_DAYS,
)

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _make_ssl_context(ssl_verify: bool) -> ssl.SSLContext:
    if ssl_verify:
        return ssl.create_default_context(cafile=certifi.where())
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@dataclass
class Article:
    id: str
    title: str
    link: str
    pub_date: str
    author: str
    description: str
    board_name: str
    board_id: int
    view_count: int
    is_pinned: bool
    attachment_count: int


def parse_pub_date(date_str: str) -> datetime:
    """건국대 RSS의 비표준 날짜 포맷 파싱: 'YYYY-MM-DD HH:MM:SS.mmm'"""
    base = date_str.split(".")[0]
    return datetime.strptime(base, "%Y-%m-%d %H:%M:%S")


def extract_article_id(link: str) -> str:
    """링크 경로에서 게시물 ID 추출: /bbs/konkuk/234/1166860/artclView.do"""
    match = re.search(r"/bbs/konkuk/\d+/(\d+)/artclView", link)
    if not match:
        logger.debug("게시물 ID 추출 실패, 링크를 ID로 사용: %s", link)
    return match.group(1) if match else link


def normalize_link(link: str, base_url: str) -> str:
    """상대 링크를 절대 URL로 변환하고 불필요한 쿼리 파라미터 제거"""
    link = link.split("?")[0]
    if link.startswith("/"):
        return base_url + link
    return link


def is_empty_feed_item(entry) -> bool:
    """빈 피드의 센티널 값 감지"""
    title = entry.get("title", "")
    return EMPTY_FEED_SENTINEL in title.lower()


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _article_key(article: Article) -> str:
    """보드 간 ID 충돌 방지를 위한 고유 키"""
    return f"{article.board_id}:{article.id}"




async def _fetch_feed_async(
    session: aiohttp.ClientSession,
    board_name: str,
    board_id: int,
    feed_config: dict,
    config: dict,
    ssl_context: ssl.SSLContext,
) -> list[Article]:
    """단일 RSS 피드를 비동기로 수집하고 Article 리스트로 반환"""
    base_url = config["settings"]["base_url"]
    url = feed_config.get("rss_url") or config["settings"]["rss_url_template"].format(board_id=board_id)

    try:
        async with session.get(url, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=FEED_FETCH_TIMEOUT)) as resp:
            resp.raise_for_status()
            xml_data = await resp.read()

        if b"<rss" not in xml_data.lower():
            logger.warning("RSS 형식이 아닌 응답 - %s (board_id=%d, url=%s)", board_name, board_id, url)
            return []

        feed = feedparser.parse(xml_data)
    except Exception as e:
        logger.error("피드 수집 실패 - %s (board_id=%d): %s", board_name, board_id, e)
        return []

    articles: list[Article] = []
    for entry in feed.entries:
        if is_empty_feed_item(entry):
            continue

        link = normalize_link(entry.get("link", ""), base_url)
        article_id = extract_article_id(entry.get("link", ""))

        articles.append(Article(
            id=article_id,
            title=entry.get("title", "").strip(),
            link=link,
            pub_date=entry.get("pubdate", entry.get("published", "")),
            author=entry.get("author", ""),
            description=entry.get("description", "").strip(),
            board_name=board_name,
            board_id=board_id,
            view_count=_to_int(entry.get("viewco", 0) or 0),
            is_pinned=entry.get("topchk", "") == "FIXTOP",
            attachment_count=_to_int(entry.get("atchco", 0) or 0),
        ))

    logger.debug("%s: %d건 수집", board_name, len(articles))
    return articles


async def fetch_all_feeds(config: dict) -> list[Article]:
    """모든 활성화된 피드에서 게시물을 비동기로 병렬 수집"""
    ssl_verify = config.get("settings", {}).get("ssl_verify", False)
    if not ssl_verify:
        logger.warning("SSL 인증서 검증 비활성화 상태. ssl_verify: true로 변경하면 보안이 강화됩니다.")
    ssl_context = _make_ssl_context(ssl_verify)

    async with aiohttp.ClientSession(headers=_DEFAULT_HEADERS) as session:
        tasks = [
            _fetch_feed_async(session, board_name, feed_config["id"], feed_config, config, ssl_context)
            for board_name, feed_config in config["feeds"].items()
            if feed_config.get("enabled", True)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: list[Article] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("피드 수집 중 예외 발생: %s", result)
        else:
            all_articles.extend(result)

    return all_articles


def load_state(state_path: str) -> dict:
    """state.json 로드. 없거나 손상되면 초기 상태 반환"""
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return {"seen_ids": {}, "last_run": None}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("state 파일 로드 실패, 초기 상태로 복구합니다: %s", e)
        return {"seen_ids": {}, "last_run": None}

    if not isinstance(state, dict):
        logger.warning("state 파일 형식 오류(객체 아님). 초기 상태로 복구합니다.")
        return {"seen_ids": {}, "last_run": None}

    state.setdefault("seen_ids", {})
    state.setdefault("last_run", None)
    if not isinstance(state["seen_ids"], dict):
        state["seen_ids"] = {}

    normalized_seen: dict[str, str] = {}
    for k, v in state["seen_ids"].items():
        if isinstance(v, str):
            normalized_seen[str(k)] = v
    state["seen_ids"] = normalized_seen

    return state


def save_state(state: dict, state_path: str) -> None:
    """state.json 저장 + 90일 지난 ID 자동 정리 (원자적 쓰기)"""
    cutoff = (datetime.now() - timedelta(days=STATE_RETENTION_DAYS)).isoformat()
    state["seen_ids"] = {
        str(k): v for k, v in state["seen_ids"].items()
        if isinstance(v, str) and v > cutoff
    }
    state["last_run"] = datetime.now().isoformat()

    target = Path(state_path)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, state_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    logger.debug("상태 저장 완료: %s", state_path)


def filter_new_articles(articles: list[Article], state: dict) -> list[Article]:
    """이미 확인한 공지를 제외하고 새 공지만 반환"""
    seen = state.get("seen_ids", {})
    new_articles: list[Article] = []

    for article in articles:
        key = _article_key(article)

        # 신규 포맷 키가 이미 있으면 스킵
        if key in seen:
            continue

        # 구형 포맷(id 단독) 키를 발견하면 즉시 신규 포맷으로 마이그레이션
        # 이후 보드 간 ID 충돌 영향을 줄이기 위해 구형 키는 제거
        if article.id in seen:
            seen[key] = seen[article.id]
            seen.pop(article.id, None)
            continue

        new_articles.append(article)

    return new_articles


async def _fetch_article_body_async(
    session: aiohttp.ClientSession,
    url: str,
    ssl_context: ssl.SSLContext,
) -> str:
    """게시물 웹페이지에서 본문 텍스트를 비동기로 크롤링 (최대 500자)"""
    from bs4 import BeautifulSoup

    try:
        async with session.get(url, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=ARTICLE_BODY_TIMEOUT)) as resp:
            resp.raise_for_status()
            html = await resp.text(encoding="utf-8", errors="replace")

        soup = BeautifulSoup(html, "lxml")
        content_div = soup.find("div", class_=BOARD_CONTENT_CLASS)
        if not content_div:
            return ""

        text = content_div.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:MAX_ARTICLE_BODY_LENGTH]
    except Exception as e:
        logger.warning("본문 크롤링 실패 - %s: %s", url, e)
        return ""


async def enrich_articles_with_body(articles: list[Article], config: dict) -> None:
    """새 공지들의 본문을 비동기 병렬로 크롤링하여 description에 추가"""
    if not articles:
        return

    ssl_verify = config.get("settings", {}).get("ssl_verify", False)
    ssl_context = _make_ssl_context(ssl_verify)

    link_articles = [a for a in articles if a.link]
    async with aiohttp.ClientSession(headers=_DEFAULT_HEADERS) as session:
        tasks = [
            _fetch_article_body_async(session, a.link, ssl_context)
            for a in link_articles
        ]
        bodies = await asyncio.gather(*tasks, return_exceptions=True)

    for article, body in zip(link_articles, bodies):
        if isinstance(body, Exception):
            logger.warning("본문 크롤링 예외 - %s: %s", article.link, body)
        elif body:
            article.description = body


def mark_as_seen(articles: list[Article], state: dict) -> None:
    """공지 ID를 state에 기록"""
    now = datetime.now().isoformat()
    for a in articles:
        state["seen_ids"][_article_key(a)] = now


async def check_ssl_health(config: dict) -> bool:
    """건국대 SSL 인증서 상태를 점검하고 결과를 로그로 기록"""
    base_url = config.get("settings", {}).get("base_url", "")
    if not base_url:
        return False

    ssl_context = _make_ssl_context(ssl_verify=True)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                base_url,
                ssl=ssl_context,
                timeout=aiohttp.ClientTimeout(total=FEED_FETCH_TIMEOUT),
            ) as resp:
                logger.info(
                    "SSL 인증서 점검 성공 (status=%d). ssl_verify: true로 전환을 권장합니다.",
                    resp.status,
                )
                return True
    except Exception as e:
        logger.info("SSL 인증서 점검 실패 (현재 설정 유지): %s", e)
        return False
