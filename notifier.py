"""텔레그램 봇 알림 모듈"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from telegram import Bot

from constants import MAX_TELEGRAM_MESSAGE_LENGTH
from feeds import Article

logger = logging.getLogger(__name__)


def build_relevant_message(
    matched: list[tuple[Article, int, str]],
    total_new: int,
) -> str:
    """관련 공지가 있을 때 텔레그램 메시지 생성"""
    today = datetime.now().strftime("%Y-%m-%d")
    header = f"{today} 새 공지 {total_new}건 중 관련 {len(matched)}건\n"

    items: list[str] = []
    for i, (article, score, reason) in enumerate(matched, 1):
        item = (
            f"\n{i}. [{article.board_name}] {article.title}\n"
            f"→ {reason}\n"
            f"{article.link}"
        )
        items.append(item)

    return header + "\n".join(items)


def build_all_new_message(articles: list[Article]) -> str:
    """필터 없이 전체 공지를 보낼 때 메시지."""
    today = datetime.now().strftime("%Y-%m-%d")
    header = f"{today} 새 공지 {len(articles)}건 (전체 전달)\n"
    items: list[str] = []
    for i, article in enumerate(articles, 1):
        items.append(f"\n{i}. [{article.board_name}] {article.title}\n{article.link}")
    return header + "\n".join(items)


def build_no_new_message() -> str:
    """새 공지가 없을 때 메시지"""
    today = datetime.now().strftime("%Y-%m-%d")
    return f"{today} 새로운 공지가 없습니다."


def build_no_relevant_message(total_new: int) -> str:
    """새 공지는 있지만 관련 공지가 없을 때 메시지"""
    today = datetime.now().strftime("%Y-%m-%d")
    return f"{today} 새 공지 {total_new}건 확인, 관련 공지 없음"


def build_error_message(error_detail: str) -> str:
    """워크플로우 오류 알림 메시지"""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"[오류] {today} 모니터링 실패\n{error_detail}"


def split_message(text: str) -> list[str]:
    """텔레그램 메시지 길이 제한에 맞게 분할"""
    limit = MAX_TELEGRAM_MESSAGE_LENGTH
    if len(text) <= limit:
        return [text]

    messages: list[str] = []
    current = ""

    for raw_line in text.split("\n"):
        line = raw_line

        while len(line) > limit:
            if current:
                messages.append(current)
                current = ""
            messages.append(line[:limit])
            line = line[limit:]

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                messages.append(current)
            current = line
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages


async def send_telegram(text: str, chat_id: str | int | None = None) -> None:
    """텔레그램 봇으로 메시지 전송"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat_id = str(chat_id).strip() if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not target_chat_id:
        logger.warning(
            "TELEGRAM_BOT_TOKEN 또는 chat_id가 설정되지 않았습니다. "
            "메시지를 전송하지 않고 콘솔에 출력합니다."
        )
        logger.info("--- 메시지 미리보기 ---\n%s", text)
        return

    bot = Bot(token=token)
    parts = split_message(text)
    sent = 0
    try:
        for msg in parts:
            await bot.send_message(chat_id=target_chat_id, text=msg)
            sent += 1
    except Exception as e:
        logger.error("텔레그램 메시지 전송 실패 (chat_id=%s): %s", target_chat_id, e)
        return
    logger.info("텔레그램 메시지 전송 완료 (chat_id=%s, %d개 분할)", target_chat_id, sent)


async def notify_relevant(
    matched: list[tuple[Article, int, str]],
    total_new: int,
    chat_id: str | int | None = None,
) -> None:
    """관련 공지를 텔레그램으로 전송"""
    text = build_relevant_message(matched, total_new)
    await send_telegram(text, chat_id=chat_id)


async def notify_all_new(articles: list[Article], chat_id: str | int | None = None) -> None:
    """새 공지를 필터 없이 전송."""
    text = build_all_new_message(articles)
    await send_telegram(text, chat_id=chat_id)


async def notify_no_new(chat_id: str | int | None = None) -> None:
    """새 공지 없음 알림"""
    text = build_no_new_message()
    await send_telegram(text, chat_id=chat_id)


async def notify_no_relevant(total_new: int, chat_id: str | int | None = None) -> None:
    """새 공지는 있지만 관련 공지 없음 알림"""
    text = build_no_relevant_message(total_new)
    await send_telegram(text, chat_id=chat_id)


async def notify_error(error_detail: str, chat_id: str | int | None = None) -> None:
    """워크플로우 오류 발생 시 텔레그램으로 알림"""
    text = build_error_message(error_detail)
    await send_telegram(text, chat_id=chat_id)
