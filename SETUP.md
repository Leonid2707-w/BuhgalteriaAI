# Настройка на Windows 10

Не отправляйте токены, API-ключи и JSON Service Account в чат, Telegram или Git.
Все секреты заполняются самостоятельно в локальном `.env`.

## 1. Telegram и Telegram User ID

1. Откройте официальный `@BotFather`, выполните `/newbot`, задайте имя и username.
2. Скопируйте токен в `TELEGRAM_BOT_TOKEN` файла `.env`.
3. Первый раз можно оставить `TELEGRAM_ALLOWED_USER_IDS` пустым.
4. Запустите бота и отправьте `/myid`. При пустом allowlist другие команды закрыты.
5. Остановите бота, внесите полученный ID в `TELEGRAM_ALLOWED_USER_IDS`. Несколько
   ID разделяются запятыми, затем перезапустите бота.

## 2. OpenAI

1. Создайте аккаунт на https://platform.openai.com/.
2. Настройте биллинг и создайте API key в разделе API keys.
3. Впишите ключ в `OPENAI_API_KEY`.
4. `OPENAI_TRANSCRIPTION_MODEL` по умолчанию равен `gpt-transcribe`. Для
   совместимости можно указать `whisper-1`.
5. Если `LLM_PROVIDER=openai`, также укажите доступную вашему аккаунту модель в
   `OPENAI_CHAT_MODEL`.

Ключ показывается сервисом ограниченное число раз. Храните его в менеджере
паролей и никогда не добавляйте в исходный код.

## 3. DeepSeek

1. Создайте аккаунт в официальной консоли DeepSeek.
2. Настройте оплату и создайте API key.
3. Впишите его в `DEEPSEEK_API_KEY`.
4. Оставьте `DEEPSEEK_BASE_URL=https://api.deepseek.com`, если официальная
   документация не требует иного.
5. В `DEEPSEEK_MODEL` укажите актуальный идентификатор JSON-совместимой chat
   модели из консоли или официальной документации DeepSeek. Проект намеренно не
   фиксирует потенциально устаревшее имя.

Для переключения без изменения кода задайте `LLM_PROVIDER=deepseek` или
`LLM_PROVIDER=openai`.

## 4. Google Cloud и Google Sheets

1. Откройте https://console.cloud.google.com/ и создайте проект.
2. В `APIs & Services` - `Library` включите Google Sheets API.
3. В `IAM & Admin` - `Service Accounts` создайте Service Account.
4. Откройте его, выберите `Keys` - `Add key` - `Create new key` - JSON.
5. Создайте в проекте папку `credentials`.
6. Сохраните скачанный файл как
   `credentials/google-service-account.json`. Не коммитьте его.
7. Создайте обычную Google Таблицу.
8. В URL `https://docs.google.com/spreadsheets/d/ID/edit` скопируйте часть `ID`
   в `GOOGLE_SPREADSHEET_ID`.
9. Найдите `client_email` в JSON Service Account.
10. Через кнопку доступа к таблице добавьте этот email с ролью редактора.
11. Выполните `.\scripts\bootstrap.ps1`. Скрипт создаст только отсутствующие
    листы, заголовки и стартовые данные в пустых листах.

Bootstrap идемпотентен и не удаляет существующие строки. Если заголовки
существующего листа несовместимы, он остановится с понятной ошибкой.

## 5. Python и установка

Установите 64-битный Python 3.12 с https://www.python.org/downloads/windows/ и
включите `Add Python to PATH`.

В PowerShell из корня проекта:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

Скрипт создаёт `.venv`, устанавливает зависимости и копирует `.env.example` в
`.env`, если файла ещё нет.

## 6. Заполнение `.env`

Откройте файл:

```powershell
notepad .env
```

Обязательные значения:

- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_ALLOWED_USER_IDS` после получения ID;
- `OPENAI_API_KEY` для голосовых сообщений;
- `DEEPSEEK_API_KEY` и `DEEPSEEK_MODEL` при `LLM_PROVIDER=deepseek`;
- либо `OPENAI_API_KEY` и `OPENAI_CHAT_MODEL` при `LLM_PROVIDER=openai`;
- `GOOGLE_SPREADSHEET_ID`;
- путь `GOOGLE_SERVICE_ACCOUNT_FILE`.

Проверьте конфигурацию без вывода секретов:

```powershell
.\scripts\check.ps1
```

## 7. Bootstrap, тесты и запуск

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
.\scripts\run.ps1
```

Бот работает через long polling. Для безопасной остановки нажмите `Ctrl+C` один
раз и дождитесь возврата приглашения PowerShell.

## 8. Первый тест

1. Отправьте боту `/start`.
2. Отправьте: `Потратил 1400 рублей на подарок маме с личной карты сегодня`.
3. Проверьте карточку и нажмите `Подтвердить`.
4. Убедитесь, что строка появилась в `Transactions`.
5. Выполните `/balance`.
6. Для проверки отмены выполните `/undo`: строка останется, а статус станет
   `reversed`.

Для голоса произнесите одну операцию. Бот покажет расшифровку, удалит временный
аудиофайл и запустит тот же сценарий подтверждения.

## 9. Какие данные нельзя отправлять боту

- номера карт и полные банковские реквизиты;
- CVV/CVC и SMS-коды;
- пароли и API-ключи;
- seed-фразы и приватные ключи криптокошельков;
- сканы документов и избыточные персональные данные.

Используйте понятные названия счетов, например `Личная карта`, без номера карты.

## Ограничения MVP

- бот рассчитан на одного владельца или небольшой статический allowlist;
- одно сообщение создаёт только одну операцию;
- курсы валют не загружаются, суммы не смешиваются между валютами;
- отчёт в Telegram пока даёт месячные агрегаты, детальные разрезы остаются в
  таблице и базовой структуре Dashboard;
- добавление, переименование, архивирование и восстановление справочников
  доступны через кнопки;
- частичное погашение долга представлено моделью данных, но полный мастер
  погашения остаётся следующим улучшением;
- переход на webhook требует только нового транспортного entrypoint, сервисы и
  бизнес-логика от aiogram polling не зависят.
