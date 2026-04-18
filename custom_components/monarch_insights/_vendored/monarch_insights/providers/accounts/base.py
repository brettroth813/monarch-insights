"""Shared types for account providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass
class AccountSnapshot:
    """A single read of one account at a point in time."""

    institution: str
    external_account_id: str
    display_name: str
    account_type: str  # depository | credit | brokerage | loan | …
    balance: Decimal
    as_of: datetime
    available_balance: Decimal | None = None
    currency: str = "USD"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeRecord:
    """A single trade lot — feeds the cost-basis ledger."""

    institution: str
    external_account_id: str
    ticker: str
    quantity: Decimal
    price_per_share: Decimal
    side: str  # "buy" | "sell"
    on_date: date
    fees: Decimal = Decimal(0)
    settlement_date: date | None = None
    external_id: str | None = None


@dataclass
class StatementReference:
    institution: str
    external_account_id: str
    period_end: date
    url: str | None
    storage_kind: str = "url"


@runtime_checkable
class AccountProvider(Protocol):
    name: str
    institution: str
    auth_kind: str  # "oauth" | "api_key" | "scrape" | "email" | "manual"

    async def list_accounts(self) -> list[AccountSnapshot]: ...
    async def list_trades(
        self, account_id: str, start: date | None = None, end: date | None = None
    ) -> list[TradeRecord]: ...
    async def list_statements(
        self, account_id: str, since: date | None = None
    ) -> list[StatementReference]: ...
