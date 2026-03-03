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
            xml_data = await resp.read()
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
    """state.json 로드. 없으면 초기 상태 반환"""
    path = Path(state_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_ids": {}, "last_run": None}


def save_state(state: dict, state_path: str) -> None:
    """state.json 저장 + 90일 지난 ID 자동 정리 (원자적 쓰기)"""
    cutoff = (datetime.now() - timedelta(days=STATE_RETENTION_DAYS)).isoformat()
    state["seen_ids"] = {
        k: v for k, v in state["seen_ids"].items()
        if v > cutoff
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
    return [a for a in articles if a.id not in seen]


async def _fetch_article_body_async(
    session: aiohttp.ClientSession,
    url: str,
    ssl_context: ssl.SSLContext,
) -> str:
    """게시물 웹페이지에서 본문 텍스트를 비동기로 크롤링 (최대 500자)"""
    from bs4 import BeautifulSoup

    try:
        async with session.get(url, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=ARTICLE_BODY_TIMEOUT)) as resp:
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

    async with aiohttp.ClientSession(headers=_DEFAULT_HEADERS) as session:
        tasks = [
            _fetch_article_body_async(session, a.link, ssl_context)
            for a in articles
            if a.link
        ]
        bodies = await asyncio.gather(*tasks, return_exceptions=True)

    link_articles = [a for a in articles if a.link]
    for article, body in zip(link_articles, bodies):
        if isinstance(body, Exception):
            logger.warning("본문 크롤링 예외 - %s: %s", article.link, body)
        elif body:
            article.description = body


def mark_as_seen(articles: list[Article], state: dict) -> None:
    """공지 ID를 state에 기록"""
    now = datetime.now().isoformat()
    for a in articles:
        state["seen_ids"][a.id] = now


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
