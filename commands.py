"""텔레그램 명령 수집/파싱/처리 모듈"""

from __future__ import annotations

import logging
import os
import re

from telegram import Bot, Update

from users import delete_user, get_or_create_user, set_allow, set_filter, set_profile

logger = logging.getLogger(__name__)

FILTER_MAP = {
    "없음": "all",
    "all": "all",
    "하": "low",
    "low": "low",
    "중": "medium",
    "medium": "medium",
    "상": "high",
    "high": "high",
}

FILTER_LABEL = {
    "all": "없음",
    "low": "하",
    "medium": "중",
    "high": "상",
}


def parse_command(text: str) -> tuple[str, str]:
    """메시지 텍스트에서 (/command, arg) 파싱."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return "", ""

    parts = raw.split(maxsplit=1)
    command = parts[0].lower()
    if "@" in command:
        command = command.split("@", 1)[0]
    arg = parts[1].strip() if len(parts) > 1 else ""
    return command, arg


def parse_profile_text(text: str) -> dict:
    """자연어 1줄 프로필 파싱 (major/year/campus/status)."""
    profile = {"major": "", "year": 0, "campus": "", "status": ""}
    raw = (text or "").strip()
    if not raw:
        return profile

    # key=value 입력 지원 (보조)
    major_match = re.search(r"major\s*=\s*([^,/;|]+)", raw, flags=re.IGNORECASE)
    campus_match = re.search(r"campus\s*=\s*([^,/;|]+)", raw, flags=re.IGNORECASE)
    status_match = re.search(r"status\s*=\s*([^,/;|]+)", raw, flags=re.IGNORECASE)
    year_match = re.search(r"year\s*=\s*(\d+)", raw, flags=re.IGNORECASE)

    if major_match:
        profile["major"] = major_match.group(1).strip()
    if campus_match:
        profile["campus"] = campus_match.group(1).strip()
    if status_match:
        profile["status"] = status_match.group(1).strip()
    if year_match:
        try:
            value = int(year_match.group(1))
            profile["year"] = value if value > 0 else 0
        except ValueError:
            profile["year"] = 0

    segments = [s.strip() for s in re.split(r"[\/,;|]", raw) if s.strip()]
    if not segments:
        segments = [raw]

    major_candidates: list[str] = []
    for seg in segments:
        if profile["year"] == 0:
            m_year = re.search(r"([1-6])\s*학년|([1-6])\s*년", seg)
            if m_year:
                year_str = m_year.group(1) or m_year.group(2)
                try:
                    profile["year"] = int(year_str)
                    continue
                except ValueError:
                    pass

        if not profile["campus"]:
            if "서울" in seg:
                profile["campus"] = "서울"
                continue
            if "글로컬" in seg or "충주" in seg:
                profile["campus"] = "글로컬"
                continue

        if not profile["status"]:
            for status_kw in ["재학", "휴학", "복학", "졸업", "수료", "재적"]:
                if status_kw in seg:
                    profile["status"] = status_kw
                    break
            if profile["status"]:
                continue

        major_candidates.append(seg)

    if not profile["major"] and major_candidates:
        for cand in major_candidates:
            if any(kw in cand for kw in ["학과", "학부", "전공", "대학"]):
                profile["major"] = cand
                break
        if not profile["major"]:
            profile["major"] = major_candidates[0]

    return profile


def _has_profile_data(profile: dict) -> bool:
    return bool(
        profile.get("major")
        or profile.get("campus")
        or profile.get("status")
        or int(profile.get("year", 0)) > 0
    )


def _help_text() -> str:
    return (
        "사용 가능한 명령어\n"
        "/start - 알림 활성화\n"
        "/help - 도움말\n"
        "/profile <자연어> - 개인정보 등록\n"
        "예시: /profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학\n"
        "/filter 없음|상|중|하 - 필터 강도 설정\n"
        "/status - 내 설정 확인\n"
        "/stop - 알림 비활성화\n"
        "/delete_me - 내 정보 삭제\n"
        "(관리자) /allow <chat_id>, /block <chat_id>"
    )


def _status_text(user: dict) -> str:
    profile = user.get("profile", {})
    return (
        f"허용 여부: {'허용' if user.get('allowed') else '차단'}\n"
        f"알림 상태: {'활성' if user.get('active') else '비활성'}\n"
        f"필터: {FILTER_LABEL.get(user.get('filter_level', 'medium'), '중')}\n"
        f"프로필 등록: {'완료' if user.get('profile_registered') else '미등록'}\n"
        f"학과: {profile.get('major', '') or '-'}\n"
        f"학년: {profile.get('year', 0) or '-'}\n"
        f"캠퍼스: {profile.get('campus', '') or '-'}\n"
        f"상태: {profile.get('status', '') or '-'}"
    )


def _blocked_text(chat_id: str) -> str:
    return (
        "이 봇은 허용된 사용자만 이용할 수 있습니다.\n"
        "관리자에게 아래 chat_id를 전달해 승인받아 주세요.\n"
        f"chat_id: {chat_id}"
    )


async def fetch_updates(last_update_id: int) -> list[Update]:
    """텔레그램 업데이트 조회 (하루 1회 배치)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return []

    bot = Bot(token=token)
    offset = int(last_update_id) + 1 if isinstance(last_update_id, int) else None
    try:
        return await bot.get_updates(
            offset=offset,
            limit=100,
            timeout=0,
            allowed_updates=["message"],
        )
    except Exception as e:
        logger.error("텔레그램 업데이트 조회 실패: %s", e)
        return []


def handle_command(update: Update, users_state: dict, config: dict) -> list[tuple[str, str]]:
    """단일 업데이트(명령어) 처리 후 응답 목록 반환."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not message.text:
        return []

    command, arg = parse_command(message.text)
    if not command:
        return []

    admin_chat_id = str(config.get("settings", {}).get("admin_chat_id", "")).strip()
    max_users = int(config.get("settings", {}).get("max_users", 30) or 30)
    chat_id = str(chat.id)
    user = get_or_create_user(users_state, chat_id, admin_chat_id=admin_chat_id)

    if command == "/help":
        return [(chat_id, _help_text())]

    if command == "/start":
        if not user.get("allowed", False):
            return [(chat_id, _blocked_text(chat_id))]
        user["active"] = True
        return [(chat_id, "알림이 활성화되었습니다. /help 로 명령어를 확인하세요.")]

    if command in {"/allow", "/block"}:
        if not user.get("is_admin", False):
            return [(chat_id, "관리자 전용 명령어입니다.")]
        target_id = arg.split()[0].strip() if arg else ""
        if not target_id:
            usage = "/allow <chat_id>" if command == "/allow" else "/block <chat_id>"
            return [(chat_id, f"사용법: {usage}")]
        ok, result = set_allow(
            users_state,
            target_id,
            allowed=(command == "/allow"),
            admin_chat_id=admin_chat_id,
            max_users=max_users,
        )
        if ok and command == "/allow" and target_id != chat_id:
            return [
                (chat_id, result),
                (target_id, "관리자 승인으로 봇 사용이 허용되었습니다. /start 를 입력해 시작하세요."),
            ]
        return [(chat_id, result)]

    if not user.get("allowed", False):
        return [(chat_id, _blocked_text(chat_id))]

    if command == "/status":
        return [(chat_id, _status_text(user))]

    if command == "/stop":
        user["active"] = False
        return [(chat_id, "알림을 비활성화했습니다. 다시 받으려면 /start 를 입력하세요.")]

    if command == "/delete_me":
        if user.get("is_admin", False):
            return [(chat_id, "관리자 계정은 /delete_me 를 사용할 수 없습니다.")]
        deleted = delete_user(users_state, chat_id)
        if deleted:
            return [(chat_id, "개인정보와 사용자 정보가 삭제되었습니다.")]
        return [(chat_id, "삭제할 사용자 정보가 없습니다.")]

    if command == "/filter":
        if not arg:
            return [(chat_id, "사용법: /filter 없음|상|중|하")]
        level = FILTER_MAP.get(arg.strip().lower(), FILTER_MAP.get(arg.strip()))
        if not level:
            return [(chat_id, "유효하지 않은 값입니다. /filter 없음|상|중|하 중에서 선택하세요.")]
        set_filter(user, level)
        return [(chat_id, f"필터가 '{FILTER_LABEL[level]}'로 설정되었습니다.")]

    if command == "/profile":
        if not arg:
            return [(chat_id, "예시: /profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학")]
        profile = parse_profile_text(arg)
        if not _has_profile_data(profile):
            return [
                (
                    chat_id,
                    "프로필을 해석하지 못했습니다. 예시 형식으로 다시 입력해 주세요.\n"
                    "예시: /profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학",
                )
            ]
        set_profile(user, arg, profile)
        return [
            (
                chat_id,
                "프로필이 저장되었습니다.\n"
                f"학과: {profile.get('major') or '-'} / "
                f"학년: {profile.get('year') or '-'} / "
                f"캠퍼스: {profile.get('campus') or '-'} / "
                f"상태: {profile.get('status') or '-'}",
            )
        ]

    return [(chat_id, "알 수 없는 명령어입니다. /help 를 확인하세요.")]
