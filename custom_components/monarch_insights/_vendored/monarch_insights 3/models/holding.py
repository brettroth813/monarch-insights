"""Investment holdings, securities, and tax lots."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date, parse_datetime


class SecurityType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    BOND = "bond"
    OPTION = "option"
    CRYPTOCURRENCY = "cryptocurrency"
    CASH = "cash"
    DERIVATIVE = "derivative"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


class Security(MonarchModel):
    id: str
    ticker: Optional[str] = None
    name: Optional[str] = None
    type: SecurityType = Field(default=SecurityType.OTHER)
    cusip: Optional[str] = None
    isin: Optional[str] = None
    currency: str = "USD"
    closing_price: Optional[Decimal] = Field(default=None, alias="closingPrice")
    closing_price_date: Optional[date] = Field(default=None, alias="closingPriceUpdatedAt")

    @field_validator("closing_price", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v)

    @field_validator("closing_price_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        if isinstance(v, str) and len(v) > 10:
            return parse_datetime(v).date() if parse_datetime(v) else None
        return parse_date(v)


class Holding(MonarchModel):
    """A position aggregated to the security level (Monarch doesn't expose per-lot)."""

    id: str
    account_id: str = Field(alias="accountId")
    security_id: Optional[str] = Field(default=None, alias="securityId")
    ticker: Optional[str] = None
    name: Optional[str] = None

    quantity: Decimal
    cost_basis: Optional[Decimal] = Field(default=None, alias="costBasis")
    value: Optional[Decimal] = None
    market_value: Optional[Decimal] = Field(default=None, alias="marketValue")
    closing_price: Optional[Decimal] = Field(default=None, alias="closingPrice")

    last_priced_at: Optional[datetime] = Field(default=None, alias="lastPricedAt")
    is_manual: bool = Field(default=False, alias="isManual")

    @field_validator("quantity", "cost_basis", "value", "market_value", "closing_price", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v)

    @field_validator("last_priced_at", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return parse_datetime(v)

    @property
    def best_value(self) -> Decimal | None:
        return self.market_value or self.value

    @property
    def unrealized_gain(self) -> Decimal | None:
        if self.best_value is None or self.cost_basis is None:
            return None
        return self.best_value - self.cost_basis

    @property
    def unrealized_gain_pct(self) -> Decimal | None:
        if self.cost_basis in (None, Decimal(0)) or self.unrealized_gain is None:
            return None
        return self.unrealized_gain / self.cost_basis


class Lot(MonarchModel):
    """A user-supplied tax lot. Monarch doesn't track this — supplements module owns it."""

    id: str
    account_id: str
    ticker: str
    quantity: Decimal
    acquired_on: date
    cost_per_share: Decimal
    fees: Decimal = Decimal(0)
    notes: Optional[str] = None

    @property
    def cost_basis(self) -> Decimal:
        return (self.quantity * self.cost_per_share) + self.fees

    @property
    def is_long_term(self) -> bool:
        from datetime import date as _date

        return (_date.today() - self.acquired_on).days > 365
