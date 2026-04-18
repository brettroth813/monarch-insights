"""Cashflow insights — month-over-month income, expense, savings, savings-rate."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, stdev
from typing import Iterable

from monarch_insights.models import Transaction


@dataclass
class MonthlyCashflow:
    month: str  # YYYY-MM
    income: Decimal = Decimal(0)
    expense: Decimal = Decimal(0)
    transfers: Decimal = Decimal(0)
    transaction_count: int = 0

    @property
    def net(self) -> Decimal:
        return self.income - self.expense

    @property
    def savings_rate(self) -> Decimal | None:
        if self.income == 0:
            return None
        return (self.income - self.expense) / self.income


class CashflowInsights:
    @staticmethod
    def monthly(transactions: Iterable[Transaction], months: int = 12) -> list[MonthlyCashflow]:
        cutoff = date.today().replace(day=1) - timedelta(days=months * 32)
        buckets: dict[str, MonthlyCashflow] = {}
        for t in transactions:
            if t.on_date < cutoff:
                continue
            if t.is_hidden_from_reports:
                continue
            month_key = t.on_date.strftime("%Y-%m")
            mc = buckets.setdefault(month_key, MonthlyCashflow(month=month_key))
            mc.transaction_count += 1
            if t.is_inflow:
                mc.income += t.amount
            else:
                mc.expense += abs(t.amount)
        return sorted(buckets.values(), key=lambda m: m.month)

    @staticmethod
    def average_monthly_spend(monthly: list[MonthlyCashflow], months: int = 6) -> Decimal:
        recent = monthly[-months:] if monthly else []
        if not recent:
            return Decimal(0)
        return Decimal(sum(m.expense for m in recent)) / Decimal(len(recent))

    @staticmethod
    def expense_volatility(monthly: list[MonthlyCashflow]) -> Decimal | None:
        if len(monthly) < 3:
            return None
        values = [float(m.expense) for m in monthly]
        return Decimal(str(stdev(values)))

    @staticmethod
    def project_balance(
        starting_balance: Decimal,
        upcoming_inflows: list[tuple[date, Decimal]],
        upcoming_outflows: list[tuple[date, Decimal]],
        horizon_days: int = 60,
    ) -> list[dict]:
        """Day-by-day projected checking balance over the horizon."""
        events = sorted(
            [(d, Decimal(amt)) for d, amt in upcoming_inflows]
            + [(d, -Decimal(amt)) for d, amt in upcoming_outflows]
        )
        result: list[dict] = []
        balance = starting_balance
        cursor = date.today()
        for offset in range(horizon_days + 1):
            day = cursor + timedelta(days=offset)
            day_delta = sum((amt for d, amt in events if d == day), Decimal(0))
            balance += day_delta
            result.append({"date": day.isoformat(), "balance": float(balance)})
        return result

    @staticmethod
    def detect_low_balance(projection: list[dict], floor: Decimal) -> list[dict]:
        return [p for p in projection if Decimal(str(p["balance"])) < floor]
