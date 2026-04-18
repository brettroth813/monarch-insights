"""Spending insights — top categories, merchant churn, budget pace."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Budget, Transaction


@dataclass
class MerchantSpend:
    merchant_id: str | None
    merchant_name: str
    total: Decimal
    transaction_count: int
    average_transaction: Decimal
    last_seen: date | None


@dataclass
class CategorySpend:
    category_id: str | None
    category_name: str
    total: Decimal
    transaction_count: int
    pct_of_total: Decimal | None = None


@dataclass
class BudgetPace:
    """Mint-style 'time progress vs budget progress' number."""

    category_id: str | None
    category_name: str
    planned: Decimal
    actual: Decimal
    days_in_period: int
    days_elapsed: int

    @property
    def expected_actual(self) -> Decimal:
        if self.days_in_period == 0:
            return Decimal(0)
        return self.planned * Decimal(self.days_elapsed) / Decimal(self.days_in_period)

    @property
    def pace_delta(self) -> Decimal:
        return self.actual - self.expected_actual

    @property
    def status(self) -> str:
        if self.planned <= 0:
            return "no_budget"
        ratio = self.actual / self.planned if self.planned else Decimal(0)
        time_ratio = Decimal(self.days_elapsed) / Decimal(self.days_in_period or 1)
        gap = ratio - time_ratio
        if gap > Decimal("0.20"):
            return "over_pace"
        if gap > Decimal("0.05"):
            return "behind_pace"
        if gap < Decimal("-0.05"):
            return "ahead_of_pace"
        return "on_pace"


class SpendingInsights:
    @staticmethod
    def top_categories(
        transactions: Iterable[Transaction], limit: int = 10, since: date | None = None
    ) -> list[CategorySpend]:
        totals: dict[str | None, Decimal] = defaultdict(lambda: Decimal(0))
        names: dict[str | None, str] = {}
        counts: dict[str | None, int] = defaultdict(int)
        grand_total = Decimal(0)
        for t in transactions:
            if since and t.on_date < since:
                continue
            if not t.is_outflow or t.is_hidden_from_reports:
                continue
            totals[t.category_id] += abs(t.amount)
            names[t.category_id] = t.category_name or "(uncategorized)"
            counts[t.category_id] += 1
            grand_total += abs(t.amount)
        result = sorted(
            (
                CategorySpend(
                    category_id=cid,
                    category_name=names[cid],
                    total=total,
                    transaction_count=counts[cid],
                    pct_of_total=(total / grand_total) if grand_total else None,
                )
                for cid, total in totals.items()
            ),
            key=lambda c: c.total,
            reverse=True,
        )
        return result[:limit]

    @staticmethod
    def top_merchants(
        transactions: Iterable[Transaction], limit: int = 15, since: date | None = None
    ) -> list[MerchantSpend]:
        totals: dict[tuple[str | None, str], Decimal] = defaultdict(lambda: Decimal(0))
        counts: dict[tuple[str | None, str], int] = defaultdict(int)
        last_seen: dict[tuple[str | None, str], date] = {}
        for t in transactions:
            if since and t.on_date < since:
                continue
            if not t.is_outflow or t.is_hidden_from_reports:
                continue
            key = (t.merchant_id, t.merchant_name or "(unknown)")
            totals[key] += abs(t.amount)
            counts[key] += 1
            if key not in last_seen or t.on_date > last_seen[key]:
                last_seen[key] = t.on_date
        result = []
        for (mid, name), total in totals.items():
            count = counts[(mid, name)]
            result.append(
                MerchantSpend(
                    merchant_id=mid,
                    merchant_name=name,
                    total=total,
                    transaction_count=count,
                    average_transaction=total / Decimal(count) if count else Decimal(0),
                    last_seen=last_seen.get((mid, name)),
                )
            )
        result.sort(key=lambda r: r.total, reverse=True)
        return result[:limit]

    @staticmethod
    def budget_pace(budget: Budget, today: date | None = None) -> list[BudgetPace]:
        today = today or date.today()
        period_start = budget.period_start
        # Monarch's 'endDate' for monthly budgets is also first-of-month; use end of month.
        next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        period_end = next_month - timedelta(days=1)
        days_in_period = (period_end - period_start).days + 1
        days_elapsed = max(0, min((today - period_start).days + 1, days_in_period))

        out: list[BudgetPace] = []
        for item in budget.items:
            out.append(
                BudgetPace(
                    category_id=item.category_id,
                    category_name=item.category_name or "(unknown)",
                    planned=item.planned_amount,
                    actual=item.actual_amount,
                    days_in_period=days_in_period,
                    days_elapsed=days_elapsed,
                )
            )
        return out

    @staticmethod
    def category_growth(
        transactions: Iterable[Transaction], months: int = 3
    ) -> list[dict]:
        """Compare last `months` average vs the prior `months` per category."""
        cutoff_recent = date.today() - timedelta(days=months * 30)
        cutoff_prior = date.today() - timedelta(days=months * 60)
        recent: dict[str | None, Decimal] = defaultdict(lambda: Decimal(0))
        prior: dict[str | None, Decimal] = defaultdict(lambda: Decimal(0))
        names: dict[str | None, str] = {}
        for t in transactions:
            if not t.is_outflow or t.is_hidden_from_reports:
                continue
            names[t.category_id] = t.category_name or "(uncategorized)"
            if t.on_date >= cutoff_recent:
                recent[t.category_id] += abs(t.amount)
            elif t.on_date >= cutoff_prior:
                prior[t.category_id] += abs(t.amount)
        rows = []
        for cid in set(list(recent.keys()) + list(prior.keys())):
            r = recent[cid] / Decimal(months)
            p = prior[cid] / Decimal(months)
            growth = (r - p) / p if p > 0 else None
            rows.append(
                {
                    "category_id": cid,
                    "category_name": names.get(cid, "(unknown)"),
                    "recent_avg_per_month": float(r),
                    "prior_avg_per_month": float(p),
                    "growth_pct": float(growth) if growth is not None else None,
                }
            )
        rows.sort(key=lambda r: r["recent_avg_per_month"], reverse=True)
        return rows
