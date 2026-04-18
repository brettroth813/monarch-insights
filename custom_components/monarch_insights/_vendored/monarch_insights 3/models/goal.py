"""Savings/financial goals."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date


class GoalType(str, Enum):
    EMERGENCY_FUND = "emergency_fund"
    SAVINGS = "savings"
    DEBT_PAYDOWN = "debt_paydown"
    RETIREMENT = "retirement"
    HOME = "home"
    EDUCATION = "education"
    VACATION = "vacation"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


class GoalContribution(MonarchModel):
    on_date: date = Field(alias="date")
    amount: Decimal

    @field_validator("on_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)


class Goal(MonarchModel):
    id: str
    name: str
    type: GoalType = GoalType.OTHER
    target_amount: Decimal = Field(alias="targetAmount")
    current_amount: Decimal = Field(default=Decimal(0), alias="currentAmount")
    target_date: Optional[date] = Field(default=None, alias="targetDate")
    monthly_contribution: Optional[Decimal] = Field(
        default=None, alias="monthlyContribution"
    )
    linked_account_ids: list[str] = Field(default_factory=list, alias="linkedAccountIds")
    is_complete: bool = Field(default=False, alias="isComplete")
    contributions: list[GoalContribution] = Field(default_factory=list)

    @field_validator("target_amount", "current_amount", "monthly_contribution", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v)

    @field_validator("target_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @property
    def remaining(self) -> Decimal:
        return max(self.target_amount - self.current_amount, Decimal(0))

    @property
    def progress_pct(self) -> Decimal | None:
        if self.target_amount == 0:
            return None
        return self.current_amount / self.target_amount

    def months_to_goal(self, monthly_contrib: Decimal | None = None) -> int | None:
        contrib = monthly_contrib or self.monthly_contribution
        if not contrib or contrib <= 0:
            return None
        return int((self.remaining / contrib).to_integral_value(rounding="ROUND_CEILING"))
