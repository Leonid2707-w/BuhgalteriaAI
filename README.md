# BuhgalteriaAI

Персональный Telegram-бот для управленческого учёта личных финансов и небольшого
контент-агентства. Бот принимает текст и голос, извлекает операцию через LLM,
уточняет данные и сохраняет их в Google Sheets только после подтверждения.

## Возможности MVP

- доходы, расходы и переводы по нескольким валютам;
- дебиторская и кредиторская задолженность;
- контуры, клиенты, проекты, категории и счета со стабильными ID;
- динамическое добавление и архивирование справочников;
- DeepSeek или OpenAI для разбора текста;
- OpenAI `gpt-transcribe` или `whisper-1` для голоса;
- черновики и защита от повторных Telegram Update в SQLite;
- балансы, месячный отчёт и безопасная отмена через `/undo`;
- allowlist Telegram User ID и маскирование чувствительных последовательностей.

Валюты не конвертируются и всегда показываются отдельно.

## Быстрый запуск на Windows 10

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
notepad .env
.\scripts\check.ps1
.\scripts\bootstrap.ps1
.\scripts\run.ps1
```

Перед bootstrap создайте Google Таблицу, Service Account и выдайте его email
роль редактора. Полная инструкция находится в [SETUP.md](SETUP.md).

## Проверки

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
```

Секреты хранятся только в локальном `.env`, а ключ Google - в
`credentials/google-service-account.json`. Эти файлы исключены из Git.
