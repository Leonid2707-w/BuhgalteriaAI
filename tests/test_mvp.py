from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Account, ParsedOperation, Scope, Transaction
from app.models.domain import OperationType
from app.services.finance import (
    DirectoryValidationError,
    calculate_balances,
    choose_default_scope,
    validate_directory_ids,
)
from app.services.security import is_user_allowed
from app.services.sheets import SheetsRepository
from app.storage.sqlite import SQLiteStore
from app.utils.dates import parse_relative_date
from app.utils.redaction import redact_sensitive


def test_allowlist() -> None:
    assert is_user_allowed(42, frozenset({42}))
    assert not is_user_allowed(41, frozenset({42}))
    assert not is_user_allowed(42, frozenset())


def test_llm_response_validation() -> None:
    parsed = ParsedOperation.model_validate(
        {
            "operation_type": "expense",
            "amount": 1400,
            "currency": "RUB",
            "scope_id": "scope_personal",
            "account_from_id": "account_card",
            "operation_date": "2026-09-27",
        }
    )
    assert parsed.amount == Decimal(1400)
    with pytest.raises(ValidationError):
        ParsedOperation.model_validate({"intent": "delete_everything"})


def test_required_fields() -> None:
    parsed = ParsedOperation()
    assert {
        "operation_type",
        "amount",
        "currency",
        "scope_id",
        "operation_date",
    }.issubset(parsed.required_missing())


def test_default_scope() -> None:
    scopes = [
        Scope(
            scope_id="one",
            name="Личное",
            base_currency="RUB",
            is_default=True,
        )
    ]
    assert choose_default_scope(scopes).scope_id == "one"


def test_directory_ids() -> None:
    parsed = ParsedOperation(scope_id="missing")
    with pytest.raises(DirectoryValidationError):
        validate_directory_ids(
            parsed,
            {
                "scopes": [{"scope_id": "known", "is_active": True}],
                "clients": [],
                "projects": [],
                "categories": [],
                "accounts": [],
            },
        )


def test_relative_dates() -> None:
    today = date(2026, 10, 13)
    assert parse_relative_date("сегодня", today) == today
    assert parse_relative_date("вчера", today) == date(2026, 10, 12)
    assert parse_relative_date("2026-09-27", today) == date(2026, 9, 27)


def transaction(**overrides: object) -> Transaction:
    data = {
        "transaction_id": "tx_1",
        "created_at": datetime(2026, 10, 13),
        "operation_date": date(2026, 10, 13),
        "telegram_user_id": 42,
        "source": "текст",
        "raw_text": "тест",
        "scope_id": "scope",
        "scope_name": "Личное",
        "operation_type": OperationType.EXPENSE,
        "amount": Decimal(100),
        "currency": "RUB",
        "account_from_id": "a",
        "status": "confirmed",
    }
    data.update(overrides)
    return Transaction.model_validate(data)


def test_transaction_sheet_row() -> None:
    row = transaction().to_sheet_row()
    assert len(row) == 25
    assert row[0] == "tx_1"
    assert row[9] == 100.0


def test_balance_and_reversed_exclusion() -> None:
    account = Account(
        account_id="a",
        scope_id="scope",
        name="Карта",
        currency="RUB",
        opening_balance=Decimal(1000),
    )
    values = calculate_balances(
        [account],
        [
            transaction(),
            transaction(transaction_id="tx_2", amount=Decimal(500), status="reversed"),
        ],
    )
    assert values["a"] == Decimal(900)


def test_transfer_between_accounts() -> None:
    accounts = [
        Account(
            account_id="a", scope_id="s", name="A", currency="RUB", opening_balance=100
        ),
        Account(
            account_id="b", scope_id="s", name="B", currency="RUB", opening_balance=0
        ),
    ]
    tx = transaction(
        operation_type=OperationType.TRANSFER,
        account_from_id="a",
        account_to_id="b",
        amount=Decimal(40),
    )
    assert calculate_balances(accounts, [tx]) == {
        "a": Decimal(60),
        "b": Decimal(40),
    }


@pytest.mark.asyncio
async def test_idempotency(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    await store.initialize()
    assert await store.claim_update(100)
    assert not await store.claim_update(100)


@pytest.mark.asyncio
async def test_draft_edit(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    await store.initialize()
    await store.save_draft(42, {"amount": 1})
    await store.update_draft(42, {"amount": 2})
    assert await store.get_draft(42) == {"amount": 2}


@pytest.mark.asyncio
async def test_archive_directory(monkeypatch) -> None:
    repository = SheetsRepository("sheet", "credentials.json")
    calls: list[tuple[object, ...]] = []

    def fake(*args: object) -> bool:
        calls.append(args)
        return True

    monkeypatch.setattr(repository, "_set_cell_sync", fake)
    assert await repository.archive("Scopes", "scope_id", "scope_1")
    assert calls[0][-1] == "FALSE"


@pytest.mark.asyncio
async def test_used_entity_cannot_be_deleted(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    await store.initialize()
    assert await store.can_physically_delete("scope", "scope_1")
    await store.mark_entity_used("scope", "scope_1")
    assert not await store.can_physically_delete("scope", "scope_1")


def test_card_number_redaction() -> None:
    source = "Карта 4111 1111 1111 1111, сумма 100"
    result = redact_sensitive(source)
    assert "4111" not in result
    assert "[СКРЫТО]" in result
