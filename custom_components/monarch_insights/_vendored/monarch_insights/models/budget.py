"""Budget plan models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date


class BudgetPeriod(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.MONTHLY


class BudgetItem(MonarchModel):
    """One row in a Monarch budget plan: typically a category w/ planned + actual."""

    id: str
    category_id: Optional[str] = Field(default=None, alias="categoryId")
    category_name: Optional[str] = Field(default=None, alias="categoryName")
    group_id: Optional[str] = Field(default=None, alias="groupId")
    group_name: Optional[str] = Field(default=None, alias="groupName")

    planned_amount: Decimal = Field(default=Decimal(0), alias="plannedCashFlowAmount")
    actual_amount: Decimal = Field(default=Decimal(0), alias="actualAmount")
    rollover_amount: Decimal = Field(default=Decimal(0), alias="rolloverAmount")
    remaining: Optional[Decimal] = Field(default=None, alias="remainingAmount")

    period: BudgetPeriod = BudgetPeriod.MONTHLY
    flex_budgeted: Optional[Decimal] = Field(default=None, alias="flexBudgetedAmount")

    @field_validator(
        "planned_amount",
        "actual_amount",
        "rollover_amount",
        "remaining",
        "flex_budgeted",
        mode="before",
    )
    @classmethod
    def _parse_money(cls, v):
        return money(v) if v is not None else None

    @property
    def variance(self) -> Decimal:
        return self.planned_amount - self.actual_amount

    @property
    def utilization(self) -> Decimal | None:
        if self.planned_amount == 0:
            return None
        return self.actual_amount / self.planned_amount


class Budget(MonarchModel):
    """A complete budget plan for a date range (typically one month)."""

    period_start: date = Field(alias="startDate")
    period_end: date = Field(alias="endDate")
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    items: list[BudgetItem] = Field(default_factory=list)

    total_planned_income: Decimal = Field(default=Decimal(0), alias="totalPlannedIncome")
    total_planned_expense: Decimal = Field(default=Decimal(0), alias="totalPlannedExpense")
    total_actual_income: Decimal = Field(default=Decimal(0), alias="totalActualIncome")
    total_actual_expense: Decimal = Field(default=Decimal(0), alias="totalActualExpense")

    @field_validator("period_start", "period_end", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator(
        "total_planned_income",
        "total_planned_expense",
        "total_actual_income",
        "total_actual_expense",
        mode="before",
    )
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)

    @property
    def planned_savings(self) -> Decimal:
        return self.total_planned_income - self.total_planned_expense

    @property
    def actual_savings(self) -> Decimal:
        return self.total_actual_income - self.total_actual_expense
