"""건국대학교 공지 모니터링 에이전트 - 메인 실행 파일"""

import asyncio
import copy
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic

import yaml

from commands import fetch_updates, handle_command
from feeds import (
    check_ssl_health,
    enrich_articles_with_body,
    fetch_all_feeds,
    filter_new_articles,
    load_state,
    mark_as_seen,
    save_state,
)
from matcher import match_articles
from notifier import notify_all_new, notify_error, notify_no_new, notify_no_relevant, notify_relevant, send_telegram
from users import (
    get_or_create_user,
    has_profile_data,
    iter_active_allowed_users,
    load_users,
    save_users,
    set_profile,
)


def setup_logging() -> None:
    """구조화된 로깅 초기화"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _load_json_env(var_name: str, fallback: dict) -> dict:
    """JSON 환경변수를 안전하게 로드하고, 파싱 실패 시 fallback 반환"""
    logger = logging.getLogger(__name__)
    raw = os.environ.get(var_name, "")
    if not raw:
        return fallback

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("%s 파싱 실패: %s. config.yaml 기본값을 사용합니다.", var_name, e)
        return fallback

    if not isinstance(value, dict):
        logger.warning("%s는 JSON 객체여야 합니다. config.yaml 기본값을 사용합니다.", var_name)
        return fallback

    return value


def _resolve_admin_chat_id(raw_value: object) -> str:
    from_env = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if from_env:
        return from_env
    text = str(raw_value).strip()
    return text


def load_config() -> dict:
    """config.yaml 로드 후 환경변수 오버라이드"""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config["profile"] = _load_json_env("PROFILE_JSON", config.get("profile", {}))
    config["keywords"] = _load_json_env("KEYWORDS_JSON", config.get("keywords", {}))
    config.setdefault("gemini", {})
    max_calls = int(config["gemini"].get("max_calls_per_run", 120) or 120)
    min_interval = float(config["gemini"].get("min_call_interval_sec", 4.2) or 4.2)
    config["gemini"]["max_calls_per_run"] = max(0, max_calls)
    config["gemini"]["min_call_interval_sec"] = max(0.0, min_interval)
    config["gemini"]["disable_after_fallback"] = bool(config["gemini"].get("disable_after_fallback", True))
    config.setdefault("settings", {})
    config["settings"]["admin_chat_id"] = _resolve_admin_chat_id(config["settings"].get("admin_chat_id", ""))
    config["settings"]["users_file"] = config["settings"].get("users_file", "users.json")
    config["settings"]["max_users"] = int(config["settings"].get("max_users", 30) or 30)
    return config


def validate_config(config: dict) -> None:
    """필수 설정 값 유효성 검사. 구조 오류 시 ValueError, 권장사항은 경고 로그."""
    logger = logging.getLogger(__name__)

    required_sections = ["profile", "keywords", "feeds", "gemini", "settings"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"config.yaml에 필수 섹션 '{section}'이 없습니다.")

    for feed_name, feed_config in config["feeds"].items():
        if "id" not in feed_config:
            raise ValueError(f"피드 '{feed_name}'에 필수 필드 'id'가 없습니다.")

    if "model" not in config.get("gemini", {}):
        raise ValueError("gemini 섹션에 필수 필드 'model'이 없습니다.")

    required_settings = ["state_file", "users_file", "base_url", "rss_url_template"]
    for field in required_settings:
        if field not in config.get("settings", {}):
            raise ValueError(f"settings 섹션에 필수 필드 '{field}'가 없습니다.")

    if not os.environ.get("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY가 설정되지 않았습니다. 키워드 매칭으로 대체됩니다.")

    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        logger.warning("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. 명령 수집/텔레그램 알림이 비활성화됩니다.")

    enabled_feeds = [name for name, fc in config["feeds"].items() if fc.get("enabled", True)]
    if not enabled_feeds:
        logger.warning("활성화된 RSS 피드가 없습니다. config.yaml의 feeds 설정을 확인하세요.")


def _log_run_summary(stats: dict) -> None:
    """실행 결과 요약을 로그로 출력"""
    logger = logging.getLogger(__name__)
    logger.info(
        "실행 요약: 피드 %d개, 수집 %d건, 신규 %d건, 사용자 %d명, 응답 %d건, 알림 %d건, "
        "Gemini호출 %d건, 강제키워드그룹 %d건, 분석: %s",
        stats["feeds_collected"],
        stats["articles_found"],
        stats["new_articles"],
        stats["active_users"],
        stats["command_responses"],
        stats["notifications_sent"],
        stats["gemini_calls_used"],
        stats["keyword_forced_groups"],
        stats["method"],
    )


def _filter_level_to_threshold(level: str) -> int:
    normalized = (level or "medium").lower().strip()
    if normalized == "high":
        return 4
    if normalized == "low":
        return 2
    return 3


async def _process_command_updates(config: dict, users_state: dict) -> int:
    """하루 1회 텔레그램 업데이트 수집 후 명령어 처리."""
    logger = logging.getLogger(__name__)
    last_update_id = int(users_state.get("meta", {}).get("last_update_id", 0) or 0)
    updates = await fetch_updates(last_update_id)
    if not updates:
        return 0

    responses: list[tuple[str, str]] = []
    max_update_id = last_update_id

    for update in updates:
        if update.update_id is not None:
            max_update_id = max(max_update_id, int(update.update_id))
        responses.extend(handle_command(update, users_state, config))

    users_state.setdefault("meta", {})
    users_state["meta"]["last_update_id"] = max_update_id

    if responses:
        await asyncio.gather(*(send_telegram(text, chat_id=chat_id) for chat_id, text in responses))
    sent = len(responses)

    logger.info("명령 처리 완료: 업데이트 %d건, 응답 %d건", len(updates), sent)
    return sent


def _finalize_run(
    all_articles: list,
    state: dict,
    users_state: dict,
    stats: dict,
    state_path: Path,
    users_path: Path,
) -> None:
    """공지 확인 처리, 상태 저장, 실행 요약 로그 출력"""
    logger = logging.getLogger(__name__)
    mark_as_seen(all_articles, state)
    state["last_run_stats"] = stats
    save_state(state, str(state_path))
    save_users(users_state, str(users_path))
    logger.info(
        "상태 저장 완료 (공지: %d건, 사용자: %d명)",
        len(state.get("seen_ids", {})),
        len(users_state.get("users", {})),
    )
    _log_run_summary(stats)


def _build_user_match_config(base_config: dict, user: dict, threshold: int) -> dict:
    config_copy = copy.deepcopy(base_config)
    config_copy["profile"] = user.get("profile", {})
    config_copy.setdefault("gemini", {})
    config_copy["gemini"]["relevance_threshold"] = threshold
    return config_copy


def _migrate_legacy_single_user(config: dict, users_state: dict) -> None:
    """기존 단일 사용자 환경변수를 다중 사용자 저장소로 1회 마이그레이션."""
    logger = logging.getLogger(__name__)
    users = users_state.get("users", {})
    if isinstance(users, dict) and users:
        return

    legacy_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not legacy_chat_id:
        return

    user = get_or_create_user(users_state, legacy_chat_id)
    user["allowed"] = True
    user["active"] = True

    profile = config.get("profile", {})
    if isinstance(profile, dict) and has_profile_data(profile):
        set_profile(user, "legacy PROFILE_JSON", profile)
    else:
        user["profile_registered"] = False
        user["filter_level"] = "all"

    logger.info("기존 TELEGRAM_CHAT_ID 기반 사용자 마이그레이션 완료: %s", legacy_chat_id)


async def run() -> None:
    logger = logging.getLogger(__name__)
    logger.info("=== 건국대 공지 모니터링 시작 ===")

    stats = {
        "timestamp": datetime.now().isoformat(),
        "feeds_collected": 0,
        "articles_found": 0,
        "new_articles": 0,
        "matched_articles": 0,
        "method": "none",
        "active_users": 0,
        "command_responses": 0,
        "notifications_sent": 0,
        "gemini_calls_used": 0,
        "keyword_forced_groups": 0,
    }

    config = load_config()
    validate_config(config)

    state_path = Path(__file__).parent / config["settings"]["state_file"]
    users_path = Path(__file__).parent / config["settings"]["users_file"]

    state = load_state(str(state_path))
    users_state = load_users(str(users_path), admin_chat_id=str(config["settings"].get("admin_chat_id", "")))
    _migrate_legacy_single_user(config, users_state)

    logger.info("기존 확인 공지: %d건", len(state.get("seen_ids", {})))

    stats["command_responses"] = await _process_command_updates(config, users_state)

    recipients = iter_active_allowed_users(users_state)
    stats["active_users"] = len(recipients)
    logger.info("활성 사용자: %d명", len(recipients))

    ssl_verify = config.get("settings", {}).get("ssl_verify", False)
    if not ssl_verify:
        await check_ssl_health(config)

    logger.info("RSS 피드 수집 중...")
    all_articles = await fetch_all_feeds(config)
    enabled_feeds = [n for n, fc in config["feeds"].items() if fc.get("enabled", True)]
    stats["feeds_collected"] = len(enabled_feeds)
    stats["articles_found"] = len(all_articles)
    logger.info("총 %d건 수집", len(all_articles))

    new_articles = filter_new_articles(all_articles, state)
    stats["new_articles"] = len(new_articles)
    logger.info("새 공지: %d건", len(new_articles))

    if not recipients:
        logger.info("활성 사용자가 없어 알림 전송을 건너뜁니다.")
        _finalize_run(all_articles, state, users_state, stats, state_path, users_path)
        return

    if not new_articles:
        logger.info("새로운 공지가 없습니다.")
        await asyncio.gather(*(notify_no_new(chat_id=user["chat_id"]) for user in recipients))
        stats["notifications_sent"] += len(recipients)
        _finalize_run(all_articles, state, users_state, stats, state_path, users_path)
        return

    logger.info("새 공지 본문 수집 중... (%d건)", len(new_articles))
    await enrich_articles_with_body(new_articles, config)

    cache: dict[tuple[str, int], tuple[list[tuple], str]] = {}
    methods: set[str] = set()
    gemini_calls_used = 0
    last_gemini_call_at = 0.0
    gemini_cfg = config["gemini"]
    max_calls_per_run = gemini_cfg["max_calls_per_run"]
    min_call_interval_sec = gemini_cfg["min_call_interval_sec"]
    disable_after_fallback = gemini_cfg["disable_after_fallback"]
    gemini_enabled = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    notification_tasks: list[asyncio.coroutines] = []

    for user in recipients:
        chat_id = user["chat_id"]
        profile_registered = bool(user.get("profile_registered", False))
        level = str(user.get("filter_level", "medium")).lower().strip()

        if not profile_registered or level == "all":
            notification_tasks.append(notify_all_new(new_articles, chat_id=chat_id))
            stats["notifications_sent"] += 1
            continue

        threshold = _filter_level_to_threshold(level)
        cache_key = (json.dumps(user.get("profile", {}), ensure_ascii=False, sort_keys=True), threshold)

        if cache_key not in cache:
            user_config = _build_user_match_config(config, user, threshold)
            force_keyword = (not gemini_enabled) or (max_calls_per_run > 0 and gemini_calls_used >= max_calls_per_run)
            if force_keyword:
                matched, method = await match_articles(new_articles, user_config, force_method="keyword")
                stats["keyword_forced_groups"] += 1
            else:
                if gemini_calls_used > 0 and min_call_interval_sec > 0:
                    elapsed = monotonic() - last_gemini_call_at
                    wait_sec = min_call_interval_sec - elapsed
                    if wait_sec > 0:
                        await asyncio.sleep(wait_sec)
                matched, method = await match_articles(new_articles, user_config)
                gemini_calls_used += 1
                last_gemini_call_at = monotonic()
                if method != "gemini" and disable_after_fallback:
                    gemini_enabled = False
            cache[cache_key] = (matched, method)
        else:
            matched, method = cache[cache_key]

        methods.add(method)
        stats["matched_articles"] += len(matched)
        if matched:
            notification_tasks.append(notify_relevant(matched, len(new_articles), chat_id=chat_id))
        else:
            notification_tasks.append(notify_no_relevant(len(new_articles), chat_id=chat_id))
        stats["notifications_sent"] += 1

    if notification_tasks:
        await asyncio.gather(*notification_tasks)

    stats["gemini_calls_used"] = gemini_calls_used
    if methods:
        stats["method"] = ",".join(sorted(methods))

    _finalize_run(all_articles, state, users_state, stats, state_path, users_path)
    logger.info("=== 완료 ===")


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    try:
        asyncio.run(run())
    except Exception as e:
        logger.exception("모니터링 실행 중 치명적 오류 발생: %s", e)
        admin_chat_id = os.environ.get("ADMIN_CHAT_ID", "").strip() or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        asyncio.run(notify_error(str(e), chat_id=admin_chat_id or None))
        sys.exit(1)


if __name__ == "__main__":
    main()
