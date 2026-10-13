from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""
    timezone: str = "Asia/Yekaterinburg"
    default_language: str = "ru"
    openai_api_key: str = ""
    openai_transcription_model: str = "gpt-transcribe"
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = ""
    openai_chat_model: str = ""
    google_spreadsheet_id: str = ""
    google_service_account_file: Path = Path("credentials/google-service-account.json")
    sqlite_path: Path = Path("data/finance_bot.db")
    log_level: str = "INFO"
    store_raw_text: bool = True
    max_voice_size_mb: int = Field(default=20, ge=1, le=25)
    http_timeout_seconds: float = Field(default=30, ge=5, le=120)

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        value = value.lower()
        if value not in {"deepseek", "openai"}:
            raise ValueError("LLM_PROVIDER должен быть deepseek или openai")
        return value

    @cached_property
    def allowed_user_ids(self) -> frozenset[int]:
        if not self.telegram_allowed_user_ids.strip():
            return frozenset()
        try:
            return frozenset(
                int(item.strip())
                for item in self.telegram_allowed_user_ids.split(",")
                if item.strip()
            )
        except ValueError as error:
            raise ValueError(
                "TELEGRAM_ALLOWED_USER_IDS должен содержать ID через запятую"
            ) from error

    def runtime_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN не заполнен")
        if not self.google_spreadsheet_id:
            errors.append("GOOGLE_SPREADSHEET_ID не заполнен")
        if not self.google_service_account_file.exists():
            errors.append(
                f"Файл Service Account не найден: {self.google_service_account_file}"
            )
        if not self.openai_api_key:
            errors.append(
                "OPENAI_API_KEY не заполнен - он нужен для голосовых сообщений"
            )
        if self.llm_provider == "deepseek":
            if not self.deepseek_api_key:
                errors.append("DEEPSEEK_API_KEY не заполнен")
            if not self.deepseek_model:
                errors.append("DEEPSEEK_MODEL не заполнен")
        elif not self.openai_chat_model:
            errors.append("OPENAI_CHAT_MODEL не заполнен")
        return errors


def load_settings() -> Settings:
    return Settings()
