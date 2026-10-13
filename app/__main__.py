from __future__ import annotations

import asyncio
import sys

from aiogram import Bot

from app.bot import create_dispatcher, set_commands
from app.config import load_settings
from app.logging_config import configure_logging
from app.services.llm import create_parser
from app.services.sheets import SheetsRepository
from app.services.transcription import OpenAITranscriber
from app.storage.sqlite import SQLiteStore


async def main() -> int:
    settings = load_settings()
    configure_logging(settings.log_level)
    errors = settings.runtime_errors()
    if errors:
        print("Бот не запущен. Заполните .env:")
        for error in errors:
            print(f"- {error}")
        print("См. SETUP.md и выполните: Copy-Item .env.example .env")
        return 2

    store = SQLiteStore(settings.sqlite_path)
    await store.initialize()
    sheets = SheetsRepository(
        settings.google_spreadsheet_id, str(settings.google_service_account_file)
    )
    parser = create_parser(settings)
    transcriber = OpenAITranscriber(
        settings.openai_api_key,
        settings.openai_transcription_model,
        settings.http_timeout_seconds,
    )
    bot = Bot(settings.telegram_bot_token)
    dispatcher = await create_dispatcher(
        settings, store, sheets, parser, transcriber
    )
    try:
        await set_commands(bot)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
