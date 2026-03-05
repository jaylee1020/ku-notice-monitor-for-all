"""사용자 저장소(users.json) 관리 모듈"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_FILTER_LEVELS = {"all", "high", "medium", "low"}
DEFAULT_FILTER_LEVEL = "medium"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_chat_id(chat_id: str | int) -> str:
    return str(chat_id).strip()


def _empty_profile() -> dict:
    return {"major": "", "year": 0, "campus": "", "status": ""}


def _new_user_record(chat_id: str, allowed: bool = False, is_admin: bool = False) -> dict:
    now = _now_iso()
    return {
        "chat_id": chat_id,
        "allowed": bool(allowed or is_admin),
        "active": bool(allowed or is_admin),
        "is_admin": bool(is_admin),
        "filter_level": DEFAULT_FILTER_LEVEL,
        "profile_registered": False,
        "profile_raw": "",
        "profile": _empty_profile(),
        "created_at": now,
        "updated_at": now,
    }


def _normalize_profile(value: object) -> dict:
    profile = _empty_profile()
    if not isinstance(value, dict):
        return profile

    major = str(value.get("major", "")).strip()
    campus = str(value.get("campus", "")).strip()
    status = str(value.get("status", "")).strip()

    try:
        year = int(value.get("year", 0))
    except (TypeError, ValueError):
        year = 0

    profile["major"] = major
    profile["year"] = year if year > 0 else 0
    profile["campus"] = campus
    profile["status"] = status
    return profile


def _has_profile_data(profile: dict) -> bool:
    return bool(
        profile.get("major")
        or profile.get("campus")
        or profile.get("status")
        or int(profile.get("year", 0)) > 0
    )


def _normalize_user_record(chat_id: str, value: object, is_admin: bool = False) -> dict:
    if not isinstance(value, dict):
        return _new_user_record(chat_id, allowed=False, is_admin=is_admin)

    base = _new_user_record(
        chat_id,
        allowed=bool(value.get("allowed", False)),
        is_admin=is_admin or bool(value.get("is_admin", False)),
    )
    base["active"] = bool(value.get("active", base["active"]))

    level = str(value.get("filter_level", DEFAULT_FILTER_LEVEL)).lower()
    base["filter_level"] = level if level in VALID_FILTER_LEVELS else DEFAULT_FILTER_LEVEL

    profile = _normalize_profile(value.get("profile", {}))
    base["profile"] = profile
    base["profile_raw"] = str(value.get("profile_raw", "")).strip()
    base["profile_registered"] = bool(value.get("profile_registered", _has_profile_data(profile)))

    created_at = str(value.get("created_at", "")).strip()
    updated_at = str(value.get("updated_at", "")).strip()
    if created_at:
        base["created_at"] = created_at
    if updated_at:
        base["updated_at"] = updated_at

    if base["is_admin"]:
        base["allowed"] = True
        base["active"] = True

    return base


def _default_users_state() -> dict:
    return {
        "meta": {"last_update_id": 0, "version": 1},
        "users": {},
    }


def load_users(path: str, admin_chat_id: str = "") -> dict:
    """users.json 로드. 파일 누락/손상 시 초기 상태 반환."""
    file_path = Path(path)
    state = _default_users_state()
    admin_id = _normalize_chat_id(admin_chat_id) if str(admin_chat_id).strip() else ""

    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                meta = raw.get("meta", {})
                if isinstance(meta, dict):
                    try:
                        state["meta"]["last_update_id"] = int(meta.get("last_update_id", 0))
                    except (TypeError, ValueError):
                        state["meta"]["last_update_id"] = 0
                    state["meta"]["version"] = int(meta.get("version", 1) or 1)

                users = raw.get("users", {})
                if isinstance(users, dict):
                    normalized: dict[str, dict] = {}
                    for chat_id, value in users.items():
                        cid = _normalize_chat_id(chat_id)
                        is_admin = admin_id != "" and cid == admin_id
                        normalized[cid] = _normalize_user_record(cid, value, is_admin=is_admin)
                    state["users"] = normalized
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("users 파일 로드 실패, 초기 상태로 복구합니다: %s", e)

    if admin_id:
        get_or_create_user(state, admin_id, admin_id)

    return state


def save_users(state: dict, path: str) -> None:
    """users.json 원자적 저장."""
    target = Path(path)
    state.setdefault("meta", {})
    state["meta"]["version"] = int(state["meta"].get("version", 1) or 1)
    try:
        state["meta"]["last_update_id"] = int(state["meta"].get("last_update_id", 0))
    except (TypeError, ValueError):
        state["meta"]["last_update_id"] = 0

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def get_or_create_user(users_state: dict, chat_id: str | int, admin_chat_id: str = "") -> dict:
    """사용자 레코드 조회. 없으면 기본 레코드 생성."""
    users = users_state.setdefault("users", {})
    cid = _normalize_chat_id(chat_id)
    admin_id = _normalize_chat_id(admin_chat_id) if str(admin_chat_id).strip() else ""
    is_admin = bool(admin_id and cid == admin_id)

    record = users.get(cid)
    normalized = _normalize_user_record(cid, record if isinstance(record, dict) else {}, is_admin=is_admin)
    normalized["updated_at"] = _now_iso()
    users[cid] = normalized
    return normalized


def set_allow(
    users_state: dict,
    chat_id: str | int,
    allowed: bool,
    admin_chat_id: str = "",
    max_users: int = 30,
) -> tuple[bool, str]:
    """허용목록 상태를 변경."""
    user = get_or_create_user(users_state, chat_id, admin_chat_id)
    if user.get("is_admin") and not allowed:
        return False, "관리자 계정은 차단할 수 없습니다."

    if allowed and not user.get("allowed", False):
        allowed_count = sum(
            1
            for u in users_state.get("users", {}).values()
            if isinstance(u, dict) and u.get("allowed", False)
        )
        if max_users > 0 and allowed_count >= max_users:
            return False, f"허용 인원 제한({max_users}명)으로 승인할 수 없습니다."

    user["allowed"] = bool(allowed)
    user["active"] = bool(allowed) if not user.get("is_admin", False) else True
    user["updated_at"] = _now_iso()

    if allowed:
        return True, f"chat_id={user['chat_id']} 사용자를 허용했습니다."
    return True, f"chat_id={user['chat_id']} 사용자를 차단했습니다."


def delete_user(users_state: dict, chat_id: str | int) -> bool:
    """사용자 레코드 삭제."""
    cid = _normalize_chat_id(chat_id)
    users = users_state.setdefault("users", {})
    if cid in users:
        users.pop(cid, None)
        return True
    return False


def set_filter(user: dict, level: str) -> None:
    """사용자 필터 레벨 설정."""
    normalized = str(level).lower().strip()
    if normalized not in VALID_FILTER_LEVELS:
        raise ValueError(f"유효하지 않은 필터 레벨: {level}")
    user["filter_level"] = normalized
    user["updated_at"] = _now_iso()


def set_profile(user: dict, profile_raw: str, profile: dict) -> None:
    """사용자 프로필 저장."""
    normalized_profile = _normalize_profile(profile)
    user["profile"] = normalized_profile
    user["profile_raw"] = profile_raw.strip()
    user["profile_registered"] = _has_profile_data(normalized_profile)
    if user["profile_registered"] and str(user.get("filter_level", "")).strip() not in VALID_FILTER_LEVELS:
        user["filter_level"] = DEFAULT_FILTER_LEVEL
    user["updated_at"] = _now_iso()


def iter_active_allowed_users(users_state: dict) -> list[dict]:
    """알림 대상 사용자 목록 반환."""
    users = users_state.get("users", {})
    if not isinstance(users, dict):
        return []
    result = []
    for value in users.values():
        if not isinstance(value, dict):
            continue
        if value.get("allowed", False) and value.get("active", False):
            result.append(value)
    return result
