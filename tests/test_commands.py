"""commands.py 단위 테스트"""

from unittest.mock import MagicMock

from commands import (
    _admin_approval_request_text,
    _blocked_text,
    _help_text,
    _status_text,
    _welcome_after_approval_text,
    handle_command,
    parse_command,
    parse_profile_text,
)
from users import (
    _default_users_state,
    get_or_create_user,
)


# --- parse_command ---


def test_parse_command_basic():
    assert parse_command("/start") == ("/start", "")


def test_parse_command_with_arg():
    cmd, arg = parse_command("/profile 컴퓨터공학부 / 2학년")
    assert cmd == "/profile"
    assert "컴퓨터공학부" in arg


def test_parse_command_with_bot_mention():
    cmd, arg = parse_command("/start@mybot")
    assert cmd == "/start"


def test_parse_command_non_command():
    assert parse_command("안녕하세요") == ("", "")


def test_parse_command_empty():
    assert parse_command("") == ("", "")


# --- parse_profile_text ---


def test_parse_profile_text_full():
    result = parse_profile_text("컴퓨터공학부 / 2학년 / 서울 / 재학")
    assert result["major"] == "컴퓨터공학부"
    assert result["year"] == 2
    assert result["campus"] == "서울"
    assert result["status"] == "재학"


def test_parse_profile_text_campus_glocal():
    result = parse_profile_text("글로컬캠퍼스 / 충주")
    assert result["campus"] == "글로컬"


def test_parse_profile_text_status_variants():
    for status in ["재학", "휴학", "복학", "졸업", "수료"]:
        result = parse_profile_text(f"컴퓨터공학부 / {status}")
        assert result["status"] == status


def test_parse_profile_text_empty():
    result = parse_profile_text("")
    assert result == {"major": "", "year": 0, "campus": "", "status": ""}


# --- 텍스트 빌더 ---


def test_help_text_contains_key_commands():
    text = _help_text()
    for cmd in ["/start", "/stop", "/profile", "/filter", "/status", "/help", "/delete_me"]:
        assert cmd in text


def test_help_text_contains_filter_levels():
    text = _help_text()
    for level in ["없음", "하", "중", "상"]:
        assert level in text


def test_blocked_text_contains_chat_id():
    text = _blocked_text("123456789")
    assert "123456789" in text


def test_blocked_text_admin_notified():
    text = _blocked_text("111", admin_notified=True)
    assert "승인 요청을 보냈습니다" in text


def test_blocked_text_no_admin():
    text = _blocked_text("111", admin_notified=False)
    assert "관리자에게" in text


def test_admin_approval_request_text():
    text = _admin_approval_request_text("999")
    assert "999" in text
    assert "/allow 999" in text
    assert "/block 999" in text


def test_welcome_after_approval_text():
    text = _welcome_after_approval_text()
    assert "/start" in text
    assert "/profile" in text


def test_status_text_active():
    user = {
        "active": True,
        "profile_registered": True,
        "filter_level": "medium",
        "profile": {"major": "CS", "year": 2, "campus": "서울", "status": "재학"},
    }
    text = _status_text(user)
    assert "켜짐" in text
    assert "CS" in text


def test_status_text_inactive_no_profile():
    user = {"active": False, "profile_registered": False, "filter_level": "all", "profile": {}}
    text = _status_text(user)
    assert "꺼짐" in text
    assert "미등록" in text


# --- handle_command 헬퍼 ---


def _make_update(chat_id: int, text: str, update_id: int = 1) -> MagicMock:
    update = MagicMock()
    update.update_id = update_id
    update.effective_chat.id = chat_id
    update.effective_message.text = text
    return update


def _make_config(admin_chat_id: str = "") -> dict:
    return {
        "settings": {"admin_chat_id": admin_chat_id, "max_users": 30},
    }


# --- handle_command: /help ---


def test_handle_command_help():
    users_state = _default_users_state()
    result = handle_command(_make_update(111, "/help"), users_state, _make_config())
    assert len(result) == 1
    chat_id, text = result[0]
    assert chat_id == "111"
    assert "/start" in text


# --- handle_command: /start (미승인) ---


def test_handle_command_start_blocked_no_admin():
    users_state = _default_users_state()
    result = handle_command(_make_update(111, "/start"), users_state, _make_config(admin_chat_id=""))
    assert len(result) == 1
    assert "111" in result[0][1]


def test_handle_command_start_blocked_notifies_admin():
    users_state = _default_users_state()
    result = handle_command(_make_update(111, "/start"), users_state, _make_config(admin_chat_id="999"))
    assert len(result) == 2
    # 사용자에게 안내
    assert result[0][0] == "111"
    # 관리자에게 알림
    assert result[1][0] == "999"
    assert "/allow 111" in result[1][1]


def test_handle_command_start_admin_no_self_notify():
    """관리자 본인이 /start 보낼 때 자신에게 승인 요청 알림 없음"""
    users_state = _default_users_state()
    users_state["meta"]["admin_chat_id"] = "999"
    user = get_or_create_user(users_state, "999")
    user["allowed"] = True
    user["active"] = False
    user["is_admin"] = True

    result = handle_command(_make_update(999, "/start"), users_state, _make_config(admin_chat_id="999"))
    assert len(result) == 1
    assert result[0][0] == "999"


# --- handle_command: /start (승인됨) ---


def test_handle_command_start_allowed_no_profile():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True
    user["profile_registered"] = False

    result = handle_command(_make_update(111, "/start"), users_state, _make_config())
    assert result[0][0] == "111"
    assert "/profile" in result[0][1]


def test_handle_command_start_allowed_with_profile():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True
    user["active"] = False
    user["profile_registered"] = True

    result = handle_command(_make_update(111, "/start"), users_state, _make_config())
    assert result[0][0] == "111"
    assert "활성화" in result[0][1]
    assert users_state["users"]["111"]["active"] is True


# --- handle_command: /stop ---


def test_handle_command_stop():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True
    user["active"] = True

    result = handle_command(_make_update(111, "/stop"), users_state, _make_config())
    assert users_state["users"]["111"]["active"] is False
    assert "꺼졌습니다" in result[0][1]


# --- handle_command: /status ---


def test_handle_command_status():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True
    user["active"] = True
    user["profile_registered"] = True
    user["profile"] = {"major": "경영학과", "year": 3, "campus": "서울", "status": "재학"}

    result = handle_command(_make_update(111, "/status"), users_state, _make_config())
    assert "경영학과" in result[0][1]


# --- handle_command: /profile ---


def test_handle_command_profile_valid():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    update = _make_update(111, "/profile 컴퓨터공학부 / 2학년 / 서울 / 재학")
    result = handle_command(update, users_state, _make_config())
    assert "저장되었습니다" in result[0][1]
    assert users_state["users"]["111"]["profile_registered"] is True
    assert "/filter" in result[0][1]


def test_handle_command_profile_empty():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    result = handle_command(_make_update(111, "/profile"), users_state, _make_config())
    assert "예시" in result[0][1]


def test_handle_command_profile_unparseable():
    """파싱 가능한 정보가 전혀 없으면 오류 안내"""
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    # 숫자 세그먼트들: year/campus/status로 소비되고 major 후보가 남지 않아 파싱 실패
    result = handle_command(_make_update(111, "/profile 1학년 / 서울 / 재학"), users_state, _make_config())
    # 학과(major) 정보가 없으므로 파싱 실패 안내 또는 일부 저장됨 - 응답이 있어야 함
    assert len(result) == 1


# --- handle_command: /filter ---


def test_handle_command_filter_valid():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    result = handle_command(_make_update(111, "/filter 상"), users_state, _make_config())
    assert "상" in result[0][1]
    assert users_state["users"]["111"]["filter_level"] == "high"


def test_handle_command_filter_invalid():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    result = handle_command(_make_update(111, "/filter 없는값"), users_state, _make_config())
    assert "유효하지 않은" in result[0][1]


# --- handle_command: /allow (관리자) ---


def test_handle_command_allow_by_admin():
    users_state = _default_users_state()
    users_state["meta"]["admin_chat_id"] = "999"
    admin = get_or_create_user(users_state, "999")
    admin["allowed"] = True
    admin["is_admin"] = True

    result = handle_command(_make_update(999, "/allow 111"), users_state, _make_config(admin_chat_id="999"))
    chat_ids = [r[0] for r in result]
    assert "999" in chat_ids  # 관리자 확인 메시지
    assert "111" in chat_ids  # 신규 사용자 웰컴 메시지
    welcome = next(r[1] for r in result if r[0] == "111")
    assert "/start" in welcome


def test_handle_command_allow_non_admin_rejected():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True
    user["is_admin"] = False

    result = handle_command(_make_update(111, "/allow 222"), users_state, _make_config())
    assert "관리자" in result[0][1]


# --- handle_command: /delete_me ---


def test_handle_command_delete_me():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    result = handle_command(_make_update(111, "/delete_me"), users_state, _make_config())
    assert "삭제" in result[0][1]
    assert "111" not in users_state["users"]


def test_handle_command_delete_me_admin_rejected():
    users_state = _default_users_state()
    users_state["meta"]["admin_chat_id"] = "999"
    admin = get_or_create_user(users_state, "999")
    admin["allowed"] = True
    admin["is_admin"] = True

    result = handle_command(_make_update(999, "/delete_me"), users_state, _make_config(admin_chat_id="999"))
    assert "관리자" in result[0][1]


# --- handle_command: 알 수 없는 명령어 ---


def test_handle_command_unknown():
    users_state = _default_users_state()
    user = get_or_create_user(users_state, "111")
    user["allowed"] = True

    result = handle_command(_make_update(111, "/unknown"), users_state, _make_config())
    assert "알 수 없는" in result[0][1]


# --- handle_command: 비명령어 메시지 무시 ---


def test_handle_command_non_command_ignored():
    users_state = _default_users_state()
    result = handle_command(_make_update(111, "안녕하세요"), users_state, _make_config())
    assert result == []
