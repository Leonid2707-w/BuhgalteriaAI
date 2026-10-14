from __future__ import annotations

import logging
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
)

from app.config import Settings
from app.models import Debt, ParsedOperation, Transaction
from app.models.domain import OperationType
from app.services.finance import (
    DirectoryValidationError,
    calculate_balances,
    report_totals,
    validate_directory_ids,
)
from app.services.llm import LLMParser
from app.services.security import AccessMiddleware
from app.services.sheets import SheetsRepository
from app.services.transcription import OpenAITranscriber
from app.storage.sqlite import SQLiteStore

logger = logging.getLogger(__name__)
router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Добавить операцию"), KeyboardButton(text="Баланс")],
        [KeyboardButton(text="Отчёты"), KeyboardButton(text="Долги")],
        [KeyboardButton(text="Структура"), KeyboardButton(text="Настройки")],
    ],
    resize_keyboard=True,
)

CONFIRM = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Подтвердить", callback_data="tx:confirm"),
            InlineKeyboardButton(text="Изменить", callback_data="tx:edit"),
            InlineKeyboardButton(text="Отменить", callback_data="tx:cancel"),
        ]
    ]
)

EDIT_FIELDS = {
    "amount": "сумма",
    "currency": "валюта",
    "operation_date": "дата",
    "scope_id": "контур",
    "client_id": "клиент",
    "project_id": "проект",
    "category_id": "категория",
    "account_from_id": "счёт списания",
    "account_to_id": "счёт зачисления",
    "counterparty": "контрагент",
    "comment": "комментарий",
}

SHEET_META = {
    "scopes": ("Scopes", "scope_id", "Контуры"),
    "clients": ("Clients", "client_id", "Клиенты"),
    "projects": ("Projects", "project_id", "Проекты"),
    "categories": ("Categories", "category_id", "Категории"),
    "accounts": ("Accounts", "account_id", "Счета"),
}


class UpdateMiddleware(BaseMiddleware):
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update = data.get("event_update")
        update_id = getattr(update, "update_id", None) or getattr(
            event, "update_id", None
        )
        if update_id is None:
            return await handler(event, data)
        if not await self.store.claim_update(update_id):
            return None
        return await handler(event, data)


def _bool(value: Any) -> bool:
    return str(value).upper() in {"TRUE", "1"}


def _name(rows: list[dict[str, Any]], key: str, value: str | None) -> str:
    if not value:
        return "-"
    return str(next((row["name"] for row in rows if row.get(key) == value), value))


def _card(payload: dict[str, Any], directories: dict[str, list[dict[str, Any]]]) -> str:
    operation = ParsedOperation.model_validate(payload["operation"])
    labels = {
        "income": "доход",
        "expense": "расход",
        "transfer": "перевод",
        "receivable": "дебиторская задолженность",
        "payable": "кредиторская задолженность",
        "debt_payment": "погашение долга",
    }
    amount = f"{operation.amount:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    account_id = operation.account_from_id or operation.account_to_id
    lines = [
        "Проверь операцию",
        "",
        f"Тип: {labels.get(str(operation.operation_type), operation.operation_type)}",
        f"Сумма: {amount} {operation.currency}",
        f"Контур: {_name(directories['scopes'], 'scope_id', operation.scope_id)}",
        f"Клиент: {_name(directories['clients'], 'client_id', operation.client_id)}",
        f"Проект: {_name(directories['projects'], 'project_id', operation.project_id)}",
        f"Категория: {_name(directories['categories'], 'category_id', operation.category_id)}",
        f"Счёт: {_name(directories['accounts'], 'account_id', account_id)}",
        f"Дата: {operation.operation_date.strftime('%d.%m.%Y') if operation.operation_date else '-'}",
        f"Контрагент: {operation.counterparty or '-'}",
        f"Комментарий: {operation.comment or '-'}",
        f"Источник: {payload['source']}",
    ]
    return "\n".join(lines)


async def _clarify_or_review(
    message: Message,
    operation: ParsedOperation,
    payload: dict[str, Any],
    directories: dict[str, list[dict[str, Any]]],
    store: SQLiteStore,
) -> None:
    missing = operation.required_missing(
        has_default_scope=any(
            _bool(row.get("is_default")) for row in directories["scopes"]
        )
    )
    if not operation.scope_id:
        default = next(
            (row for row in directories["scopes"] if _bool(row.get("is_default"))),
            None,
        )
        if default:
            operation.scope_id = default["scope_id"]
            missing = [item for item in missing if item != "scope_id"]
    try:
        validate_directory_ids(operation, directories)
    except DirectoryValidationError as error:
        missing.extend(error.fields)
    suggested = [
        value
        for key, value in operation.model_dump().items()
        if key.startswith("suggested_") and value
    ]
    if (
        missing
        or operation.ambiguous_fields
        or suggested
        or operation.needs_clarification
    ):
        field = (
            (missing + operation.ambiguous_fields)[0]
            if (missing or operation.ambiguous_fields)
            else "unknown"
        )
        payload["operation"] = operation.model_dump(mode="json")
        payload["waiting_field"] = field
        await store.save_draft(message.from_user.id, payload, "clarification")
        question = operation.clarification_question or (
            f"Нужно уточнить поле: {EDIT_FIELDS.get(field, field)}. "
            "Отправьте значение текстом."
        )
        if suggested:
            question += f"\nНе найдено в справочнике: {', '.join(suggested)}."
            question += (
                "\nСоздайте элемент в разделе Структура или выберите существующий."
            )
        await message.answer(question)
        return
    payload["operation"] = operation.model_dump(mode="json")
    await store.save_draft(message.from_user.id, payload)
    await message.answer(_card(payload, directories), reply_markup=CONFIRM)


async def process_text(
    message: Message,
    text: str,
    source: str,
    parser: LLMParser,
    sheets: SheetsRepository,
    store: SQLiteStore,
    settings: Settings,
) -> None:
    await message.answer("Разбираю операцию...")
    try:
        directories = await sheets.directories()
        operation = await parser.parse(
            text,
            datetime.now(ZoneInfo(settings.timezone)).date(),
            settings.timezone,
            directories,
        )
        payload = {
            "operation": operation.model_dump(mode="json"),
            "raw_text": text,
            "source": source,
        }
        await _clarify_or_review(message, operation, payload, directories, store)
    except Exception:
        logger.exception("Ошибка разбора операции")
        await message.answer(
            "Не удалось надёжно разобрать операцию. Попробуйте сформулировать иначе "
            "или используйте /add для ручного ввода."
        )


@router.message(Command("myid"))
async def my_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram User ID: {message.from_user.id}")


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Финансовый бот готов. Отправьте одну операцию текстом или голосом.",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Отправьте одну финансовую операцию сообщением. Запись появится в таблице "
        "только после подтверждения.\n"
        "/add - добавить\n/balance - остатки\n/report - отчёт\n/debts - долги\n"
        "/structure - справочники\n/undo - отменить последнюю операцию\n"
        "/settings - настройки\n/myid - ваш Telegram ID"
    )


@router.message(Command("add"))
@router.message(F.text == "Добавить операцию")
async def add(message: Message) -> None:
    await message.answer(
        "Опишите одну операцию текстом или отправьте голосовое сообщение.\n"
        "Пример: Потратил 1400 рублей на подарок маме с личной карты сегодня."
    )


@router.message(Command("balance"))
@router.message(F.text == "Баланс")
async def balance(message: Message, sheets: SheetsRepository) -> None:
    try:
        accounts, transactions, scopes = await sheets.load_finance()
        values = calculate_balances(accounts, transactions)
        scope_names = {scope.scope_id: scope.name for scope in scopes}
        lines = ["Текущие остатки"]
        for account in accounts:
            if account.is_active:
                lines.append(
                    f"{scope_names.get(account.scope_id, account.scope_id)} - "
                    f"{account.name}: {values[account.account_id]} {account.currency}"
                )
        await message.answer("\n".join(lines))
    except Exception:
        logger.exception("Ошибка расчёта баланса")
        await message.answer("Не удалось получить баланс. Проверьте доступ к таблице.")


@router.message(Command("report"))
@router.message(F.text == "Отчёты")
async def report(message: Message, sheets: SheetsRepository) -> None:
    try:
        _, transactions, _ = await sheets.load_finance()
        today = date.today()
        current = [
            tx
            for tx in transactions
            if tx.operation_date.year == today.year
            and tx.operation_date.month == today.month
        ]
        totals = report_totals(current)
        lines = ["Отчёт за текущий месяц"]
        for currency, values in sorted(totals.items()):
            lines.append(
                f"{currency}: доход {values['income']}, расход {values['expense']}, "
                f"чистый поток {values['net']}"
            )
        await message.answer(
            "\n".join(lines) if totals else "За текущий месяц операций нет."
        )
    except Exception:
        logger.exception("Ошибка отчёта")
        await message.answer("Не удалось построить отчёт.")


@router.message(Command("debts"))
@router.message(F.text == "Долги")
async def debts(message: Message, sheets: SheetsRepository) -> None:
    try:
        rows = await sheets.list_records("Debts")
        active = [row for row in rows if row["status"] == "active"]
        lines = ["Активные долги"]
        for row in active:
            rest = Decimal(str(row["amount"])) - Decimal(str(row["paid_amount"] or 0))
            overdue = (
                " - просрочен"
                if row["due_date"]
                and date.fromisoformat(str(row["due_date"])) < date.today()
                else ""
            )
            lines.append(
                f"{row['direction']} - {row['counterparty']}: {rest} {row['currency']}{overdue}"
            )
        lines.append("\nЧтобы добавить долг, опишите его обычным сообщением.")
        await message.answer("\n".join(lines))
    except Exception:
        logger.exception("Ошибка списка долгов")
        await message.answer("Не удалось получить долги.")


def structure_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"struct:list:{key}")]
            for key, (_, _, title) in SHEET_META.items()
        ]
    )


@router.message(Command("structure"))
@router.message(F.text == "Структура")
async def structure(message: Message) -> None:
    await message.answer("Выберите справочник", reply_markup=structure_keyboard())


@router.callback_query(F.data.startswith("struct:list:"))
async def list_structure(callback: CallbackQuery, sheets: SheetsRepository) -> None:
    kind = callback.data.split(":")[2]
    sheet, id_key, title = SHEET_META[kind]
    rows = await sheets.list_records(sheet)
    buttons = []
    for row in rows[:30]:
        active = _bool(row["is_active"])
        state = "архивировать" if active else "восстановить"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{row['name']} - {state}",
                    callback_data=f"struct:toggle:{kind}:{row[id_key]}:{int(active)}",
                ),
                InlineKeyboardButton(
                    text="Переименовать",
                    callback_data=f"struct:rename:{kind}:{row[id_key]}",
                ),
            ]
        )
        if kind == "scopes" and active and not _bool(row.get("is_default")):
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{row['name']} - сделать по умолчанию",
                        callback_data=f"struct:default:{row[id_key]}",
                    )
                ]
            )
    buttons.append(
        [InlineKeyboardButton(text="Добавить", callback_data=f"struct:add:{kind}")]
    )
    await callback.message.edit_text(
        title, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("struct:toggle:"))
async def toggle_structure(callback: CallbackQuery, sheets: SheetsRepository) -> None:
    _, _, kind, entity_id, was_active = callback.data.split(":", 4)
    sheet, id_key, _ = SHEET_META[kind]
    await sheets.archive(sheet, id_key, entity_id, active=not bool(int(was_active)))
    await callback.answer("Справочник обновлён")
    callback.data = f"struct:list:{kind}"
    await list_structure(callback, sheets)


@router.callback_query(F.data.startswith("struct:rename:"))
async def rename_structure(callback: CallbackQuery, store: SQLiteStore) -> None:
    _, _, kind, entity_id = callback.data.split(":", 3)
    await store.save_draft(
        callback.from_user.id,
        {
            "structure_action": "rename",
            "structure_kind": kind,
            "structure_entity_id": entity_id,
        },
        "structure_rename",
    )
    await callback.message.answer("Введите новое название.")
    await callback.answer()


@router.callback_query(F.data.startswith("struct:default:"))
async def default_scope(callback: CallbackQuery, sheets: SheetsRepository) -> None:
    scope_id = callback.data.split(":", 2)[2]
    changed = await sheets.set_default_scope(scope_id)
    await callback.answer(
        "Контур по умолчанию обновлён" if changed else "Не удалось выбрать контур",
        show_alert=not changed,
    )


@router.callback_query(F.data.startswith("struct:add:"))
async def add_structure(callback: CallbackQuery, store: SQLiteStore) -> None:
    kind = callback.data.split(":")[2]
    await store.save_draft(
        callback.from_user.id,
        {"structure_action": "add", "structure_kind": kind},
        "structure_add",
    )
    formats = {
        "scopes": "Название | валюта",
        "clients": "Название | scope_id",
        "projects": "Название | scope_id | client_id (можно пусто)",
        "categories": "Название | scope_id | income/expense/both",
        "accounts": "Название | scope_id | валюта | начальный баланс",
    }
    await callback.message.answer(f"Введите: {formats[kind]}")
    await callback.answer()


@router.message(Command("undo"))
async def undo(message: Message, sheets: SheetsRepository) -> None:
    try:
        transaction_id = await sheets.reverse_last(message.from_user.id)
        await message.answer(
            f"Операция {transaction_id} аннулирована."
            if transaction_id
            else "Подтверждённых операций для отмены нет."
        )
    except Exception:
        logger.exception("Ошибка отмены")
        await message.answer("Не удалось отменить операцию.")


@router.message(Command("settings"))
@router.message(F.text == "Настройки")
async def settings_command(message: Message, settings: Settings) -> None:
    await message.answer(
        f"Часовой пояс: {settings.timezone}\n"
        f"LLM-провайдер: {settings.llm_provider}\n"
        f"Транскрипция: {settings.openai_transcription_model}\n"
        "Настройки меняются в файле .env."
    )


@router.callback_query(F.data == "tx:cancel")
async def cancel(callback: CallbackQuery, store: SQLiteStore) -> None:
    await store.delete_draft(callback.from_user.id)
    await callback.message.edit_text("Операция отменена. В таблицу ничего не записано.")
    await callback.answer()


@router.callback_query(F.data == "tx:edit")
async def edit(callback: CallbackQuery) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label.capitalize(), callback_data=f"tx:field:{field}"
                )
            ]
            for field, label in EDIT_FIELDS.items()
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("tx:field:"))
async def choose_edit_field(callback: CallbackQuery, store: SQLiteStore) -> None:
    field = callback.data.split(":", 2)[2]
    draft = await store.get_draft(callback.from_user.id)
    if not draft:
        await callback.answer("Черновик не найден", show_alert=True)
        return
    draft["waiting_field"] = field
    await store.save_draft(callback.from_user.id, draft, "edit")
    await callback.message.answer(
        f"Введите новое значение поля «{EDIT_FIELDS[field]}». Для справочника укажите ID."
    )
    await callback.answer()


@router.callback_query(F.data == "tx:confirm")
async def confirm(
    callback: CallbackQuery,
    store: SQLiteStore,
    sheets: SheetsRepository,
    settings: Settings,
) -> None:
    draft = await store.get_draft(callback.from_user.id)
    if not draft:
        await callback.answer("Черновик не найден", show_alert=True)
        return
    try:
        operation = ParsedOperation.model_validate(draft["operation"])
        directories = await sheets.directories()
        validate_directory_ids(operation, directories)
        if operation.required_missing():
            raise ValueError("Не все обязательные поля заполнены")
        scope = _name(directories["scopes"], "scope_id", operation.scope_id)
        if operation.operation_type in {
            OperationType.RECEIVABLE,
            OperationType.PAYABLE,
        }:
            debt = Debt(
                debt_id=f"debt_{uuid4().hex}",
                created_at=datetime.now(UTC),
                scope_id=operation.scope_id or "",
                direction="receivable"
                if operation.operation_type == OperationType.RECEIVABLE
                else "payable",
                counterparty=operation.counterparty or "Не указан",
                amount=operation.amount or Decimal(0),
                currency=operation.currency or "",
                due_date=operation.due_date,
                client_id=operation.client_id,
                project_id=operation.project_id,
                comment=operation.comment,
            )
            await sheets.append_row(
                "Debts",
                [
                    debt.debt_id,
                    debt.created_at.isoformat(),
                    "",
                    debt.scope_id,
                    debt.direction,
                    debt.counterparty,
                    float(debt.amount),
                    debt.currency,
                    float(debt.paid_amount),
                    debt.due_date.isoformat() if debt.due_date else "",
                    debt.client_id or "",
                    debt.project_id or "",
                    debt.status,
                    debt.comment or "",
                ],
            )
            record_id = debt.debt_id
        else:
            transaction = Transaction(
                transaction_id=f"tx_{uuid4().hex}",
                created_at=datetime.now(UTC),
                operation_date=operation.operation_date or date.today(),
                telegram_user_id=callback.from_user.id,
                source=draft["source"],
                raw_text=draft["raw_text"] if settings.store_raw_text else "",
                scope_id=operation.scope_id or "",
                scope_name=scope,
                operation_type=operation.operation_type,
                amount=operation.amount or Decimal(0),
                currency=operation.currency or "",
                account_from_id=operation.account_from_id,
                account_from_name=_name(
                    directories["accounts"], "account_id", operation.account_from_id
                ),
                account_to_id=operation.account_to_id,
                account_to_name=_name(
                    directories["accounts"], "account_id", operation.account_to_id
                ),
                client_id=operation.client_id,
                client_name=_name(
                    directories["clients"], "client_id", operation.client_id
                ),
                project_id=operation.project_id,
                project_name=_name(
                    directories["projects"], "project_id", operation.project_id
                ),
                category_id=operation.category_id,
                category_name=_name(
                    directories["categories"], "category_id", operation.category_id
                ),
                counterparty=operation.counterparty,
                comment=operation.comment,
            )
            await sheets.append_transaction(transaction)
            for kind, entity_id in [
                ("scope", operation.scope_id),
                ("client", operation.client_id),
                ("project", operation.project_id),
                ("category", operation.category_id),
                ("account", operation.account_from_id or operation.account_to_id),
            ]:
                if entity_id:
                    await store.mark_entity_used(kind, entity_id)
            record_id = transaction.transaction_id
        await store.delete_draft(callback.from_user.id)
        await callback.message.edit_text(f"Операция подтверждена. ID: {record_id}")
        await callback.answer()
    except Exception:
        logger.exception("Ошибка подтверждения")
        await callback.answer("Не удалось записать операцию", show_alert=True)


async def _handle_structure_input(
    message: Message,
    draft: dict[str, Any],
    sheets: SheetsRepository,
    store: SQLiteStore,
) -> bool:
    kind = draft.get("structure_kind")
    if not kind:
        return False
    if draft.get("structure_action") == "rename":
        sheet, id_key, _ = SHEET_META[kind]
        new_name = (message.text or "").strip()
        if not new_name:
            await message.answer("Название не может быть пустым.")
            return True
        changed = await sheets.rename(
            sheet, id_key, draft["structure_entity_id"], new_name
        )
        if changed:
            await store.delete_draft(message.from_user.id)
            await message.answer(
                "Название обновлено. Старые операции сохранили связь по ID."
            )
        else:
            await message.answer("Элемент не найден.")
        return True
    parts = [part.strip() for part in (message.text or "").split("|")]
    now = datetime.now(UTC).isoformat()
    entity_id = f"{kind[:-1]}_{uuid4().hex[:12]}"
    expected = {
        "scopes": 2,
        "clients": 2,
        "projects": 3,
        "categories": 3,
        "accounts": 4,
    }
    if len(parts) != expected[kind]:
        await message.answer("Неверный формат. Разделяйте поля символом |.")
        return True
    rows = {
        "scopes": [entity_id, parts[0], parts[1].upper(), "FALSE", "TRUE", now],
        "clients": [entity_id, parts[1], parts[0], "TRUE", now],
        "projects": [entity_id, parts[1], parts[2], parts[0], "TRUE", now],
        "categories": [entity_id, parts[1], parts[2], parts[0], "TRUE", now],
        "accounts": [
            entity_id,
            parts[1],
            parts[0],
            parts[2].upper(),
            parts[3],
            "TRUE",
            now,
        ],
    }
    await sheets.append_row(SHEET_META[kind][0], rows[kind])
    await store.delete_draft(message.from_user.id)
    await message.answer(f"Добавлено. ID: {entity_id}")
    return True


@router.message(F.voice)
async def voice(
    message: Message,
    bot: Bot,
    transcriber: OpenAITranscriber,
    parser: LLMParser,
    sheets: SheetsRepository,
    store: SQLiteStore,
    settings: Settings,
) -> None:
    if (
        message.voice.file_size
        and message.voice.file_size > settings.max_voice_size_mb * 1024 * 1024
    ):
        await message.answer(f"Голосовое больше {settings.max_voice_size_mb} МБ.")
        return
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp:
            path = Path(temp.name)
        await bot.download(message.voice.file_id, destination=path)
        text = await transcriber.transcribe(path)
        await message.answer(f"Расшифровка:\n{text}")
        await process_text(
            message, text, "голосовое сообщение", parser, sheets, store, settings
        )
    except Exception:
        logger.exception("Ошибка распознавания голоса")
        await message.answer(
            "Не удалось распознать голосовое. Повторите запись или отправьте операцию текстом."
        )
    finally:
        if path:
            path.unlink(missing_ok=True)


@router.message(F.text)
async def text(
    message: Message,
    parser: LLMParser,
    sheets: SheetsRepository,
    store: SQLiteStore,
    settings: Settings,
) -> None:
    draft = await store.get_draft(message.from_user.id)
    if (
        draft
        and draft.get("structure_kind")
        and await _handle_structure_input(message, draft, sheets, store)
    ):
        return
    if draft and draft.get("waiting_field"):
        field = draft.pop("waiting_field")
        operation = draft["operation"]
        value: Any = message.text.strip()
        if field == "amount":
            value = value.replace(",", ".").replace(" ", "")
        operation[field] = value
        try:
            parsed = ParsedOperation.model_validate(operation)
            directories = await sheets.directories()
            await _clarify_or_review(message, parsed, draft, directories, store)
        except Exception:  # noqa: BLE001 - пользователь не должен видеть stack trace
            await message.answer(
                "Значение не принято. Проверьте формат и попробуйте ещё раз."
            )
        return
    await process_text(
        message, message.text, "текстовое сообщение", parser, sheets, store, settings
    )


async def create_dispatcher(
    settings: Settings,
    store: SQLiteStore,
    sheets: SheetsRepository,
    parser: LLMParser,
    transcriber: OpenAITranscriber,
) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(UpdateMiddleware(store))
    dispatcher.message.outer_middleware(AccessMiddleware(settings.allowed_user_ids))
    dispatcher.callback_query.outer_middleware(
        AccessMiddleware(settings.allowed_user_ids)
    )
    dispatcher.include_router(router)
    dispatcher["settings"] = settings
    dispatcher["store"] = store
    dispatcher["sheets"] = sheets
    dispatcher["parser"] = parser
    dispatcher["transcriber"] = transcriber
    return dispatcher


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="myid", description="Показать Telegram ID"),
            BotCommand(command="add", description="Добавить операцию"),
            BotCommand(command="balance", description="Баланс"),
            BotCommand(command="report", description="Отчёты"),
            BotCommand(command="debts", description="Долги"),
            BotCommand(command="structure", description="Структура"),
            BotCommand(command="undo", description="Отменить последнюю операцию"),
            BotCommand(command="settings", description="Настройки"),
        ]
    )
