from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.services.sheets import SheetsRepository


async def main() -> int:
    settings = load_settings()
    if not settings.google_spreadsheet_id:
        print("GOOGLE_SPREADSHEET_ID не заполнен в .env")
        return 2
    if not settings.google_service_account_file.exists():
        print(f"Файл не найден: {settings.google_service_account_file}")
        return 2
    repository = SheetsRepository(
        settings.google_spreadsheet_id, str(settings.google_service_account_file)
    )
    try:
        await repository.bootstrap()
    except Exception as error:  # noqa: BLE001 - CLI преобразует ошибку в краткое сообщение
        print(f"Не удалось подготовить таблицу: {error}")
        return 1
    print("Таблица подготовлена. Существующие данные не изменены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
