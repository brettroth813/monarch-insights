"""Aggregated cashflow models (category, group, merchant)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date


class CashflowGrouping(str, Enum):
    CATEGORY = "category"
    GROUP = "group"
    MERCHANT = "merchant"
    ACCOUNT = "account"
    TAG = "tag"


class CashflowEntry(MonarchModel):
    """One row in a cashflow report for a slice of time."""

    grouping: CashflowGrouping
    key_id: Optional[str] = None
    key_name: str
    income: Decimal = Decimal(0)
    expense: Decimal = Decimal(0)
    net: Decimal = Decimal(0)
    transaction_count: int = 0

    @field_validator("income", "expense", "net", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)


class CashflowSummary(MonarchModel):
    """Top-level totals for a period."""

    period_start: date = Field(alias="startDate")
    period_end: date = Field(alias="endDate")
    sum_income: Decimal = Field(default=Decimal(0), alias="sumIncome")
    sum_expense: Decimal = Field(default=Decimal(0), alias="sumExpense")
    savings: Decimal = Field(default=Decimal(0), alias="savings")
    savings_rate: Optional[Decimal] = Field(default=None, alias="savingsRate")

    @field_validator("period_start", "period_end", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator("sum_income", "sum_expense", "savings", "savings_rate", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v)

    def computed_savings_rate(self) -> Decimal | None:
        if not self.sum_income or self.sum_income == 0:
            return None
        return (self.sum_income - self.sum_expense) / self.sum_income
