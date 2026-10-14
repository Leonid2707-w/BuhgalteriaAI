from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.models import ParsedOperation
from app.utils.redaction import sanitize_for_ai


def build_prompt(
    text: str,
    today: date,
    timezone: str,
    directories: dict[str, list[dict[str, Any]]],
    validation_error: str | None = None,
) -> str:
    payload = {
        "current_date": today.isoformat(),
        "timezone": timezone,
        "user_text": sanitize_for_ai(text),
        "directories": directories,
        "required_json_schema": ParsedOperation.model_json_schema(),
        "rules": [
            "Выбирай только существующие активные ID.",
            "Если совпадения нет, верни ID=null и suggested_*_name.",
            "Перевод между своими счетами - transfer, не доход и не расход.",
            "Обещанная выплата - receivable, а не income.",
            "Долг пользователя - payable, долг пользователю - receivable.",
            "Вывод владельца использует отдельную категорию.",
            "Если операций несколько, multiple_operations=true.",
            "Отвечай одним JSON-объектом без markdown.",
        ],
        "previous_validation_error": validation_error,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


class LLMParser(ABC):
    @abstractmethod
    async def _request(self, prompt: str) -> str:
        raise NotImplementedError

    async def parse(
        self,
        text: str,
        today: date,
        timezone: str,
        directories: dict[str, list[dict[str, Any]]],
    ) -> ParsedOperation:
        error: str | None = None
        for _ in range(3):
            response = await self._request(
                build_prompt(text, today, timezone, directories, error)
            )
            try:
                operation = ParsedOperation.model_validate_json(response)
                if operation.multiple_operations:
                    raise ValueError(
                        "В сообщении несколько операций. Отправьте каждую отдельно."
                    )
                return operation
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                error = str(exc)[:1500]
        raise ValueError(
            "Не удалось надёжно разобрать операцию после двух повторных попыток"
        )


class DeepSeekParser(LLMParser):
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def _request(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Ты финансовый парсер. Верни JSON, соответствующий "
                                "переданным правилам и полям ParsedOperation."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]


class OpenAIParser(LLMParser):
    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model

    async def _request(self, prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "Верни только JSON финансовой операции."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return response.choices[0].message.content or ""


def create_parser(settings: Any) -> LLMParser:
    if settings.llm_provider == "deepseek":
        return DeepSeekParser(
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
            settings.http_timeout_seconds,
        )
    return OpenAIParser(
        settings.openai_api_key,
        settings.openai_chat_model,
        settings.http_timeout_seconds,
    )
