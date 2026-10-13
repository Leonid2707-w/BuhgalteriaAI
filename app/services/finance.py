from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.models import Account, ParsedOperation, Scope, Transaction
from app.models.domain import OperationType


class DirectoryValidationError(ValueError):
    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields
        super().__init__("Неизвестные или архивные элементы справочника")


def choose_default_scope(
    scopes: list[Scope], selected_id: str | None = None
) -> Scope | None:
    active = [scope for scope in scopes if scope.is_active]
    if selected_id:
        return next((scope for scope in active if scope.scope_id == selected_id), None)
    return next((scope for scope in active if scope.is_default), None)


def validate_directory_ids(
    operation: ParsedOperation, directories: dict[str, list[dict[str, Any]]]
) -> None:
    mapping = {
        "scope_id": ("scopes", "scope_id"),
        "client_id": ("clients", "client_id"),
        "project_id": ("projects", "project_id"),
        "category_id": ("categories", "category_id"),
        "account_from_id": ("accounts", "account_id"),
        "account_to_id": ("accounts", "account_id"),
    }
    invalid: dict[str, str] = {}
    for field, (collection, key) in mapping.items():
        value = getattr(operation, field)
        if value and not any(
            item.get(key) == value and item.get("is_active", True)
            for item in directories.get(collection, [])
        ):
            invalid[field] = value
    if invalid:
        raise DirectoryValidationError(invalid)


def calculate_balances(
    accounts: list[Account], transactions: list[Transaction]
) -> dict[str, Decimal]:
    balances = {account.account_id: account.opening_balance for account in accounts}
    for tx in transactions:
        if tx.status != "confirmed":
            continue
        amount = tx.amount
        if tx.operation_type in {
            OperationType.EXPENSE,
            OperationType.DEBT_PAYMENT,
        } and tx.account_from_id in balances:
            balances[tx.account_from_id] -= amount
        elif tx.operation_type == OperationType.INCOME and tx.account_to_id in balances:
            balances[tx.account_to_id] += amount
        elif tx.operation_type == OperationType.TRANSFER:
            if tx.account_from_id in balances:
                balances[tx.account_from_id] -= amount
            if tx.account_to_id in balances:
                balances[tx.account_to_id] += amount
    return balances


def report_totals(
    transactions: list[Transaction],
) -> dict[str, dict[str, Decimal]]:
    result: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expense": Decimal("0"), "net": Decimal("0")}
    )
    for tx in transactions:
        if tx.status != "confirmed":
            continue
        if tx.operation_type == OperationType.INCOME:
            result[tx.currency]["income"] += tx.amount
            result[tx.currency]["net"] += tx.amount
        elif tx.operation_type == OperationType.EXPENSE:
            result[tx.currency]["expense"] += tx.amount
            result[tx.currency]["net"] -= tx.amount
    return dict(result)
