from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.utils.redaction import redact_sensitive


def is_user_allowed(user_id: int, allowed_ids: frozenset[int]) -> bool:
    return bool(allowed_ids) and user_id in allowed_ids


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive(str(record.msg))
        if record.args:
            record.args = tuple(redact_sensitive(str(arg)) for arg in record.args)
        return True


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_ids: frozenset[int]) -> None:
        self.allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and is_user_allowed(user.id, self.allowed_ids):
            return await handler(event, data)
        if isinstance(event, Message) and event.text == "/myid":
            return await handler(event, data)
        text = (
            f"Ваш Telegram User ID: {user.id if user else 'не определён'}\n"
            "Добавьте его в TELEGRAM_ALLOWED_USER_IDS файла .env и перезапустите бота."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещён", show_alert=True)
        return None
