"""Recurring transaction streams."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date


class RecurrenceFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    SEMI_MONTHLY = "semi_monthly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.UNKNOWN


class RecurringStream(MonarchModel):
    id: str
    name: str
    merchant_id: Optional[str] = Field(default=None, alias="merchantId")
    category_id: Optional[str] = Field(default=None, alias="categoryId")
    category_name: Optional[str] = Field(default=None, alias="categoryName")
    account_id: Optional[str] = Field(default=None, alias="accountId")
    account_name: Optional[str] = Field(default=None, alias="accountName")

    frequency: RecurrenceFrequency = RecurrenceFrequency.UNKNOWN
    average_amount: Optional[Decimal] = Field(default=None, alias="averageAmount")
    next_amount: Optional[Decimal] = Field(default=None, alias="nextAmount")
    next_date: Optional[date] = Field(default=None, alias="nextDate")
    last_date: Optional[date] = Field(default=None, alias="lastDate")
    is_active: bool = Field(default=True, alias="isActive")
    is_income: bool = Field(default=False, alias="isIncome")

    @field_validator("average_amount", "next_amount", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v)

    @field_validator("next_date", "last_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    def annualized_amount(self) -> Decimal | None:
        amt = self.average_amount or self.next_amount
        if amt is None:
            return None
        multiplier = {
            RecurrenceFrequency.DAILY: Decimal(365),
            RecurrenceFrequency.WEEKLY: Decimal(52),
            RecurrenceFrequency.BIWEEKLY: Decimal(26),
            RecurrenceFrequency.SEMI_MONTHLY: Decimal(24),
            RecurrenceFrequency.MONTHLY: Decimal(12),
            RecurrenceFrequency.QUARTERLY: Decimal(4),
            RecurrenceFrequency.SEMI_ANNUAL: Decimal(2),
            RecurrenceFrequency.ANNUAL: Decimal(1),
        }.get(self.frequency)
        if multiplier is None:
            return None
        return amt * multiplier
