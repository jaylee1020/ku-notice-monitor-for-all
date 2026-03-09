"""텔레그램 명령 수집/파싱/처리 모듈"""

from __future__ import annotations

import logging
import re

from telegram import Update

from notifier import get_bot
from users import delete_user, get_or_create_user, has_profile_data, set_allow, set_filter, set_profile

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


def _help_text() -> str:
    return (
        "건국대 공지 모니터 도움말\n"
        "\n"
        "[ 기본 명령어 ]\n"
        "/start        - 알림 시작\n"
        "/stop         - 알림 일시 중지\n"
        "/status       - 내 설정 확인\n"
        "/help         - 이 도움말\n"
        "\n"
        "[ 맞춤 설정 ]\n"
        "/profile <정보>  - 프로필 등록 (맞춤 알림 활성화)\n"
        "  예시: /profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학\n"
        "\n"
        "/filter <강도>  - 관련도 필터 설정\n"
        "  없음  모든 공지 수신\n"
        "  하    낮은 관련도 이상\n"
        "  중    중간 관련도 이상 (기본값)\n"
        "  상    높은 관련도만\n"
        "\n"
        "[ 기타 ]\n"
        "/delete_me    - 내 정보 삭제\n"
        "\n"
        "알림은 매일 오전 10시에 전송됩니다.\n"
        "(관리자) /allow <chat_id>  /block <chat_id>"
    )


def _status_text(user: dict) -> str:
    profile = user.get("profile", {})
    active_str = "켜짐" if user.get("active") else "꺼짐"
    profile_str = "등록됨" if user.get("profile_registered") else "미등록 (프로필 없으면 전체 공지 수신)"
    filter_str = FILTER_LABEL.get(user.get("filter_level", "medium"), "중")
    return (
        "[ 내 설정 ]\n"
        f"알림: {active_str}\n"
        f"필터: {filter_str}\n"
        f"프로필: {profile_str}\n"
        f"  학과: {profile.get('major', '') or '-'}\n"
        f"  학년: {profile.get('year', 0) or '-'}\n"
        f"  캠퍼스: {profile.get('campus', '') or '-'}\n"
        f"  재학상태: {profile.get('status', '') or '-'}"
    )


def _blocked_text(chat_id: str, admin_notified: bool = False) -> str:
    base = (
        "이 봇은 관리자 승인 후 이용할 수 있습니다.\n"
        "\n"
        f"내 Chat ID: {chat_id}\n"
    )
    if admin_notified:
        base += "\n관리자에게 승인 요청을 보냈습니다. 승인되면 다시 /start 를 입력해 주세요."
    else:
        base += "\n위 Chat ID를 관리자에게 전달해 승인을 요청해 주세요."
    return base


def _admin_approval_request_text(chat_id: str) -> str:
    return (
        "새 사용자 승인 요청이 왔습니다.\n"
        f"Chat ID: {chat_id}\n"
        "\n"
        f"승인하려면: /allow {chat_id}\n"
        f"차단하려면: /block {chat_id}"
    )


def _welcome_after_approval_text() -> str:
    return (
        "봇 사용이 승인되었습니다.\n"
        "\n"
        "[ 시작 방법 ]\n"
        "1. /start  를 입력해 알림을 활성화하세요.\n"
        "2. /profile 로 프로필을 등록하면 맞춤 공지를 받을 수 있습니다.\n"
        "   예시: /profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학\n"
        "3. /filter 로 관련도 필터를 설정할 수 있습니다.\n"
        "\n"
        "자세한 명령어는 /help 를 확인하세요.\n"
        "알림은 매일 오전 10시에 전송됩니다."
    )


async def fetch_updates(last_update_id: int) -> list[Update]:
    """텔레그램 업데이트 조회 (하루 1회 배치)."""
    bot = get_bot()
    if not bot:
        return []
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

    max_users = int(config.get("settings", {}).get("max_users", 30) or 30)
    chat_id = str(chat.id)
    user = get_or_create_user(users_state, chat_id)

    if command == "/help":
        return [(chat_id, _help_text())]

    if command == "/start":
        if not user.get("allowed", False):
            admin_chat_id = str(config.get("settings", {}).get("admin_chat_id", "")).strip()
            admin_notified = bool(admin_chat_id and admin_chat_id != chat_id)
            responses: list[tuple[str, str]] = [(chat_id, _blocked_text(chat_id, admin_notified=admin_notified))]
            if admin_notified:
                responses.append((admin_chat_id, _admin_approval_request_text(chat_id)))
            return responses
        user["active"] = True
        if not user.get("profile_registered"):
            return [(
                chat_id,
                "알림이 활성화되었습니다.\n"
                "\n"
                "프로필을 등록하면 내 관심사에 맞는 공지만 받을 수 있습니다.\n"
                "예시: /profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학\n"
                "\n"
                "등록하지 않으면 모든 새 공지를 수신합니다.\n"
                "도움말: /help",
            )]
        return [(chat_id, "알림이 활성화되었습니다. 매일 오전 10시에 공지를 전송합니다.")]

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
            max_users=max_users,
        )
        if ok and command == "/allow" and target_id != chat_id:
            return [
                (chat_id, result),
                (target_id, _welcome_after_approval_text()),
            ]
        return [(chat_id, result)]

    if not user.get("allowed", False):
        return [(chat_id, _blocked_text(chat_id))]

    if command == "/status":
        return [(chat_id, _status_text(user))]

    if command == "/stop":
        user["active"] = False
        return [(chat_id, "알림이 꺼졌습니다. 다시 받으려면 /start 를 입력하세요.")]

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
        if not has_profile_data(profile):
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
                f"  학과: {profile.get('major') or '-'}\n"
                f"  학년: {profile.get('year') or '-'}\n"
                f"  캠퍼스: {profile.get('campus') or '-'}\n"
                f"  재학상태: {profile.get('status') or '-'}\n"
                "\n"
                "이제 맞춤 공지 알림이 활성화됩니다.\n"
                "필터 강도를 설정할 수 있습니다.\n"
                "  /filter 없음  모든 공지\n"
                "  /filter 하    낮은 관련도 이상\n"
                "  /filter 중    중간 관련도 이상 (기본값)\n"
                "  /filter 상    높은 관련도만",
            )
        ]

    return [(chat_id, "알 수 없는 명령어입니다. /help 를 확인하세요.")]
