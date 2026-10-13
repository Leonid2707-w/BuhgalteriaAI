from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import gspread
from google.oauth2.service_account import Credentials

from app.models import Account, Scope, Transaction

HEADERS = {
    "Transactions": [
        "transaction_id",
        "created_at",
        "operation_date",
        "telegram_user_id",
        "source",
        "raw_text",
        "scope_id",
        "scope_name",
        "operation_type",
        "amount",
        "currency",
        "account_from_id",
        "account_from_name",
        "account_to_id",
        "account_to_name",
        "client_id",
        "client_name",
        "project_id",
        "project_name",
        "category_id",
        "category_name",
        "counterparty",
        "comment",
        "status",
        "reversal_of",
    ],
    "Scopes": [
        "scope_id",
        "name",
        "base_currency",
        "is_default",
        "is_active",
        "created_at",
    ],
    "Clients": ["client_id", "scope_id", "name", "is_active", "created_at"],
    "Projects": [
        "project_id",
        "scope_id",
        "client_id",
        "name",
        "is_active",
        "created_at",
    ],
    "Categories": [
        "category_id",
        "scope_id",
        "operation_type",
        "name",
        "is_active",
        "created_at",
    ],
    "Accounts": [
        "account_id",
        "scope_id",
        "name",
        "currency",
        "opening_balance",
        "is_active",
        "created_at",
    ],
    "Debts": [
        "debt_id",
        "created_at",
        "closed_at",
        "scope_id",
        "direction",
        "counterparty",
        "amount",
        "currency",
        "paid_amount",
        "due_date",
        "client_id",
        "project_id",
        "status",
        "comment",
    ],
    "AuditLog": [
        "event_id",
        "created_at",
        "telegram_user_id",
        "action",
        "entity_type",
        "entity_id",
        "details",
    ],
    "Dashboard": ["Показатель", "Валюта", "Значение", "Обновлено"],
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def seed_rows() -> dict[str, list[list[Any]]]:
    scopes = [
        ["scope_personal", "Личное", "RUB", "TRUE", "TRUE", _now()],
        ["scope_agency", "Агентство", "USD", "FALSE", "TRUE", _now()],
    ]
    clients = [
        ["client_404", "scope_agency", "404 Team", "TRUE", _now()],
        ["client_trading", "scope_agency", "Trading Bot", "TRUE", _now()],
        ["client_scrooge", "scope_agency", "Скрудж", "TRUE", _now()],
    ]
    projects = [
        [
            "project_bigbankclub",
            "scope_agency",
            "client_404",
            "BigBankClub",
            "TRUE",
            _now(),
        ],
        [
            "project_internal",
            "scope_agency",
            "",
            "Внутренние задачи агентства",
            "TRUE",
            _now(),
        ],
    ]
    categories: list[list[Any]] = []
    for idx, name in enumerate(
        [
            "Еда",
            "Транспорт",
            "Одежда",
            "Подарки",
            "Здоровье",
            "Образование",
            "Развлечения",
            "Другое",
        ]
    ):
        categories.append(
            [
                f"category_personal_expense_{idx}",
                "scope_personal",
                "expense",
                name,
                "TRUE",
                _now(),
            ]
        )
    for idx, name in enumerate(["Подарки и помощь", "Возврат долга", "Другой доход"]):
        categories.append(
            [
                f"category_personal_income_{idx}",
                "scope_personal",
                "income",
                name,
                "TRUE",
                _now(),
            ]
        )
    for idx, name in enumerate(
        [
            "AI-сервисы",
            "Подрядчики",
            "Реклама",
            "Подписки",
            "Домены и хостинг",
            "Оборудование",
            "Комиссии",
            "Вывод владельца",
            "Другое",
        ]
    ):
        categories.append(
            [
                f"category_agency_expense_{idx}",
                "scope_agency",
                "expense",
                name,
                "TRUE",
                _now(),
            ]
        )
    for idx, name in enumerate(
        ["Оплата клиента", "Возврат средств", "Вложение владельца", "Другой доход"]
    ):
        categories.append(
            [
                f"category_agency_income_{idx}",
                "scope_agency",
                "income",
                name,
                "TRUE",
                _now(),
            ]
        )
    accounts = [
        [
            "account_personal_card",
            "scope_personal",
            "Личная карта",
            "RUB",
            0,
            "TRUE",
            _now(),
        ],
        ["account_cash", "scope_personal", "Наличные", "RUB", 0, "TRUE", _now()],
        [
            "account_personal_usdt",
            "scope_personal",
            "Личная биржа",
            "USDT",
            0,
            "TRUE",
            _now(),
        ],
        [
            "account_agency_usdt",
            "scope_agency",
            "Агентство USDT",
            "USDT",
            0,
            "TRUE",
            _now(),
        ],
        [
            "account_agency_rub",
            "scope_agency",
            "Агентство RUB",
            "RUB",
            0,
            "TRUE",
            _now(),
        ],
    ]
    return {
        "Scopes": scopes,
        "Clients": clients,
        "Projects": projects,
        "Categories": categories,
        "Accounts": accounts,
    }


class SheetsRepository:
    def __init__(self, spreadsheet_id: str, credentials_file: str) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.credentials_file = credentials_file

    def _open(self) -> gspread.Spreadsheet:
        credentials = Credentials.from_service_account_file(
            self.credentials_file,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        return gspread.authorize(credentials).open_by_key(self.spreadsheet_id)

    async def bootstrap(self) -> None:
        await asyncio.to_thread(self._bootstrap_sync)

    def _bootstrap_sync(self) -> None:
        book = self._open()
        existing = {sheet.title: sheet for sheet in book.worksheets()}
        seeds = seed_rows()
        for title, headers in HEADERS.items():
            sheet = existing.get(title) or book.add_worksheet(
                title, rows=1000, cols=max(20, len(headers))
            )
            first = sheet.row_values(1)
            if not first:
                sheet.append_row(headers)
            elif first != headers:
                raise RuntimeError(f"Заголовки листа {title} не совпадают с ожидаемыми")
            if title in seeds and not sheet.row_values(2):
                sheet.append_rows(seeds[title])
        dashboard = book.worksheet("Dashboard")
        if not dashboard.row_values(2):
            dashboard.append_rows(
                [
                    ["Остатки по счетам", "", "Обновляются ботом", _now()],
                    ["Доходы текущего месяца", "", "По валютам", _now()],
                    ["Расходы текущего месяца", "", "По валютам", _now()],
                    ["Чистый денежный поток", "", "По валютам", _now()],
                    ["Задолженности", "", "По валютам", _now()],
                    ["Клиенты / проекты / категории", "", "См. отчёты бота", _now()],
                ]
            )

    async def list_records(self, sheet_name: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            lambda: self._open().worksheet(sheet_name).get_all_records()
        )

    async def directories(
        self, active_only: bool = True
    ) -> dict[str, list[dict[str, Any]]]:
        names = ["Scopes", "Clients", "Projects", "Categories", "Accounts"]
        values = await asyncio.gather(*(self.list_records(name) for name in names))
        result = dict(zip((name.lower() for name in names), values, strict=True))
        if active_only:
            for key, rows in result.items():
                result[key] = [
                    row for row in rows if str(row.get("is_active")).upper() == "TRUE"
                ]
        return result

    async def append_transaction(self, transaction: Transaction) -> None:
        await asyncio.to_thread(
            lambda: (
                self._open()
                .worksheet("Transactions")
                .append_row(
                    transaction.to_sheet_row(), value_input_option="USER_ENTERED"
                )
            )
        )

    async def append_row(self, sheet_name: str, row: list[Any]) -> None:
        await asyncio.to_thread(
            lambda: (
                self._open()
                .worksheet(sheet_name)
                .append_row(row, value_input_option="USER_ENTERED")
            )
        )

    async def archive(
        self, sheet_name: str, id_column: str, entity_id: str, active: bool = False
    ) -> bool:
        return await asyncio.to_thread(
            self._set_cell_sync,
            sheet_name,
            id_column,
            entity_id,
            "is_active",
            "TRUE" if active else "FALSE",
        )

    async def rename(
        self, sheet_name: str, id_column: str, entity_id: str, new_name: str
    ) -> bool:
        return await asyncio.to_thread(
            self._set_cell_sync, sheet_name, id_column, entity_id, "name", new_name
        )

    async def set_default_scope(self, scope_id: str) -> bool:
        return await asyncio.to_thread(self._set_default_scope_sync, scope_id)

    def _set_default_scope_sync(self, scope_id: str) -> bool:
        sheet = self._open().worksheet("Scopes")
        headers = sheet.row_values(1)
        default_column = headers.index("is_default") + 1
        found = False
        for index, record in enumerate(sheet.get_all_records(), start=2):
            selected = str(record["scope_id"]) == scope_id
            if selected and str(record["is_active"]).upper() != "TRUE":
                return False
            sheet.update_cell(index, default_column, "TRUE" if selected else "FALSE")
            found = found or selected
        return found

    def _set_cell_sync(
        self, sheet_name: str, id_column: str, entity_id: str, field: str, value: Any
    ) -> bool:
        sheet = self._open().worksheet(sheet_name)
        headers = sheet.row_values(1)
        records = sheet.get_all_records()
        for index, record in enumerate(records, start=2):
            if str(record[id_column]) == entity_id:
                sheet.update_cell(index, headers.index(field) + 1, value)
                return True
        return False

    async def reverse_last(self, user_id: int) -> str | None:
        return await asyncio.to_thread(self._reverse_last_sync, user_id)

    def _reverse_last_sync(self, user_id: int) -> str | None:
        sheet = self._open().worksheet("Transactions")
        headers = sheet.row_values(1)
        records = sheet.get_all_records()
        for offset, record in enumerate(reversed(records)):
            if (
                str(record["telegram_user_id"]) == str(user_id)
                and record["status"] == "confirmed"
            ):
                row = len(records) + 1 - offset
                sheet.update_cell(row, headers.index("status") + 1, "reversed")
                self._open().worksheet("AuditLog").append_row(
                    [
                        f"event_{uuid4().hex}",
                        _now(),
                        user_id,
                        "reverse",
                        "transaction",
                        record["transaction_id"],
                        "Отмена через /undo",
                    ]
                )
                return str(record["transaction_id"])
        return None

    async def load_finance(
        self,
    ) -> tuple[list[Account], list[Transaction], list[Scope]]:
        accounts_raw, tx_raw, scopes_raw = await asyncio.gather(
            self.list_records("Accounts"),
            self.list_records("Transactions"),
            self.list_records("Scopes"),
        )
        accounts = [
            Account(
                account_id=row["account_id"],
                scope_id=row["scope_id"],
                name=row["name"],
                currency=row["currency"],
                opening_balance=Decimal(str(row["opening_balance"] or 0)),
                is_active=str(row["is_active"]).upper() == "TRUE",
                created_at=row["created_at"],
            )
            for row in accounts_raw
        ]
        transactions = [Transaction.model_validate(row) for row in tx_raw]
        scopes = [
            Scope(
                scope_id=row["scope_id"],
                name=row["name"],
                base_currency=row["base_currency"],
                is_default=str(row["is_default"]).upper() == "TRUE",
                is_active=str(row["is_active"]).upper() == "TRUE",
                created_at=row["created_at"],
            )
            for row in scopes_raw
        ]
        return accounts, transactions, scopes
