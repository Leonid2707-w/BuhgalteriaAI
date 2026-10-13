from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OperationType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    RECEIVABLE = "receivable"
    PAYABLE = "payable"
    DEBT_PAYMENT = "debt_payment"


class DirectoryBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class Scope(DirectoryBase):
    scope_id: str
    base_currency: str
    is_default: bool = False


class Client(DirectoryBase):
    client_id: str
    scope_id: str


class Project(DirectoryBase):
    project_id: str
    scope_id: str
    client_id: str | None = None


class Category(DirectoryBase):
    category_id: str
    scope_id: str
    operation_type: str


class Account(DirectoryBase):
    account_id: str
    scope_id: str
    currency: str
    opening_balance: Decimal = Decimal("0")


class ParsedOperation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    intent: str = "create_transaction"
    operation_type: OperationType | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    scope_id: str | None = None
    client_id: str | None = None
    project_id: str | None = None
    category_id: str | None = None
    account_from_id: str | None = None
    account_to_id: str | None = None
    counterparty: str | None = None
    operation_date: date | None = None
    comment: str | None = None
    suggested_scope_name: str | None = None
    suggested_client_name: str | None = None
    suggested_project_name: str | None = None
    suggested_category_name: str | None = None
    suggested_account_name: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    debt_direction: str | None = None
    due_date: date | None = None
    paid_amount: Decimal = Decimal("0")
    multiple_operations: bool = False

    @model_validator(mode="after")
    def validate_semantics(self) -> ParsedOperation:
        if self.intent != "create_transaction":
            raise ValueError("Поддерживается только intent=create_transaction")
        if self.operation_type == OperationType.TRANSFER:
            if self.account_from_id and self.account_from_id == self.account_to_id:
                raise ValueError("Счета перевода должны различаться")
        if self.paid_amount < 0:
            raise ValueError("paid_amount не может быть отрицательной")
        return self

    def required_missing(self, has_default_scope: bool = False) -> list[str]:
        missing = set(self.missing_fields)
        if self.operation_type is None:
            missing.add("operation_type")
        if self.amount is None:
            missing.add("amount")
        if not self.currency:
            missing.add("currency")
        if not self.scope_id and not has_default_scope:
            missing.add("scope_id")
        if self.operation_type in {
            OperationType.EXPENSE,
            OperationType.TRANSFER,
            OperationType.DEBT_PAYMENT,
        } and not self.account_from_id:
            missing.add("account_from_id")
        if self.operation_type == OperationType.INCOME and not self.account_to_id:
            missing.add("account_to_id")
        if self.operation_type == OperationType.TRANSFER and not self.account_to_id:
            missing.add("account_to_id")
        if self.operation_date is None:
            missing.add("operation_date")
        return sorted(missing)


class Transaction(BaseModel):
    transaction_id: str
    created_at: datetime
    operation_date: date
    telegram_user_id: int
    source: str
    raw_text: str
    scope_id: str
    scope_name: str
    operation_type: OperationType
    amount: Decimal
    currency: str
    account_from_id: str | None = None
    account_from_name: str | None = None
    account_to_id: str | None = None
    account_to_name: str | None = None
    client_id: str | None = None
    client_name: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    counterparty: str | None = None
    comment: str | None = None
    status: str = "confirmed"
    reversal_of: str | None = None

    def to_sheet_row(self) -> list[str | int | float]:
        data = self.model_dump()
        order = [
            "transaction_id", "created_at", "operation_date", "telegram_user_id",
            "source", "raw_text", "scope_id", "scope_name", "operation_type",
            "amount", "currency", "account_from_id", "account_from_name",
            "account_to_id", "account_to_name", "client_id", "client_name",
            "project_id", "project_name", "category_id", "category_name",
            "counterparty", "comment", "status", "reversal_of",
        ]
        result: list[str | int | float] = []
        for key in order:
            value = data[key]
            if isinstance(value, (date, datetime)):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, StrEnum):
                value = value.value
            result.append("" if value is None else value)
        return result


class Debt(BaseModel):
    debt_id: str
    created_at: datetime
    closed_at: datetime | None = None
    scope_id: str
    direction: str
    counterparty: str
    amount: Decimal
    currency: str
    paid_amount: Decimal = Decimal("0")
    due_date: date | None = None
    client_id: str | None = None
    project_id: str | None = None
    status: str = "active"
    comment: str | None = None
