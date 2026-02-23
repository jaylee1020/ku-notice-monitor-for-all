"""건국대학교 공지 모니터링 에이전트 - 메인 실행 파일"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from feeds import fetch_all_feeds, filter_new_articles, load_state, save_state, mark_as_seen, enrich_articles_with_body
from matcher import match_articles
from notifier import notify_relevant, notify_no_new, notify_no_relevant, notify_error


def setup_logging() -> None:
    """구조화된 로깅 초기화"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_config() -> dict:
    """config.yaml 로드 후 환경변수로 개인정보 오버라이드"""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    profile_json = os.environ.get("PROFILE_JSON", "")
    if profile_json:
        config["profile"] = json.loads(profile_json)

    keywords_json = os.environ.get("KEYWORDS_JSON", "")
    if keywords_json:
        config["keywords"] = json.loads(keywords_json)

    return config


def validate_config(config: dict) -> None:
    """필수 설정 값 유효성 검사. 문제 발견 시 경고 로그 출력."""
    logger = logging.getLogger(__name__)

    required_sections = ["profile", "keywords", "feeds", "gemini", "settings"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"config.yaml에 필수 섹션 '{section}'이 없습니다.")

    if not os.environ.get("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY가 설정되지 않았습니다. 키워드 매칭으로 대체됩니다.")

    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        logger.warning("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. 텔레그램 알림이 비활성화됩니다.")

    if not os.environ.get("TELEGRAM_CHAT_ID"):
        logger.warning("TELEGRAM_CHAT_ID가 설정되지 않았습니다. 텔레그램 알림이 비활성화됩니다.")

    enabled_feeds = [name for name, fc in config["feeds"].items() if fc.get("enabled", True)]
    if not enabled_feeds:
        logger.warning("활성화된 RSS 피드가 없습니다. config.yaml의 feeds 설정을 확인하세요.")


async def run() -> None:
    logger = logging.getLogger(__name__)
    logger.info("=== 건국대 공지 모니터링 시작 ===")

    config = load_config()
    validate_config(config)

    state_path = Path(__file__).parent / config["settings"]["state_file"]
    state = load_state(str(state_path))
    logger.info("기존 확인 공지: %d건", len(state.get("seen_ids", {})))

    logger.info("RSS 피드 수집 중...")
    all_articles = await fetch_all_feeds(config)
    logger.info("총 %d건 수집", len(all_articles))

    new_articles = filter_new_articles(all_articles, state)
    logger.info("새 공지: %d건", len(new_articles))

    if not new_articles:
        logger.info("새로운 공지가 없습니다.")
        await notify_no_new()
        mark_as_seen(all_articles, state)
        save_state(state, str(state_path))
        return

    logger.info("새 공지 본문 수집 중... (%d건)", len(new_articles))
    await enrich_articles_with_body(new_articles, config)

    logger.info("Gemini로 관련도 분석 중...")
    matched = match_articles(new_articles, config)
    logger.info("관련 공지: %d건", len(matched))

    if matched:
        logger.info("텔레그램으로 관련 공지 전송 중...")
        await notify_relevant(matched, len(new_articles))
        logger.info("전송 완료")
    else:
        logger.info("관련 공지 없음 알림 전송 중...")
        await notify_no_relevant(len(new_articles))
        logger.info("전송 완료")

    mark_as_seen(all_articles, state)
    save_state(state, str(state_path))
    logger.info("상태 저장 완료 (총 %d건 기록)", len(state["seen_ids"]))
    logger.info("=== 완료 ===")


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    try:
        asyncio.run(run())
    except Exception as e:
        logger.exception("모니터링 실행 중 치명적 오류 발생: %s", e)
        asyncio.run(notify_error(str(e)))
        sys.exit(1)


if __name__ == "__main__":
    main()
