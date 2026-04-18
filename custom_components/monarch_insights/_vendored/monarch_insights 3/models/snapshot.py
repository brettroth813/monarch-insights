"""Net worth and aggregate snapshots over time."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date


class NetWorthSnapshot(MonarchModel):
    """A single date's totals across all included accounts."""

    on_date: date = Field(alias="date")
    assets: Decimal = Decimal(0)
    liabilities: Decimal = Decimal(0)

    @field_validator("on_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator("assets", "liabilities", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities


class AggregateSnapshot(MonarchModel):
    """Per-account-type aggregate at a point in time."""

    on_date: date = Field(alias="date")
    account_type: str = Field(alias="accountType")
    balance: Decimal
    asset: bool = True

    @field_validator("on_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator("balance", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)
