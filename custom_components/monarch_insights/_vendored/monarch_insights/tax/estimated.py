"""Estimated-tax pacing for self-employed / 1099 / K-1 users."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from monarch_insights.tax.brackets import FilingStatus, federal_tax


@dataclass
class QuarterlyDue:
    quarter: int
    due_date: date
    expected_amount: Decimal
    paid_to_date: Decimal
    shortfall: Decimal


SAFE_HARBOR_PRIOR_YEAR = Decimal("1.10")  # 110% if AGI > $150k, 100% otherwise


class EstimatedTaxTracker:
    def __init__(self, *, status: FilingStatus = FilingStatus.SINGLE) -> None:
        self.status = status

    @staticmethod
    def quarterly_due_dates(year: int) -> list[date]:
        return [
            date(year, 4, 15),
            date(year, 6, 15),
            date(year, 9, 15),
            date(year + 1, 1, 15),
        ]

    def safe_harbor_total(self, prior_year_tax: Decimal, prior_year_agi: Decimal) -> Decimal:
        multiplier = SAFE_HARBOR_PRIOR_YEAR if prior_year_agi > Decimal(150000) else Decimal(1)
        return prior_year_tax * multiplier

    def schedule(
        self,
        year: int,
        prior_year_tax: Decimal,
        prior_year_agi: Decimal,
        payments_made: dict[int, Decimal] | None = None,
    ) -> list[QuarterlyDue]:
        payments_made = payments_made or {}
        total_due = self.safe_harbor_total(prior_year_tax, prior_year_agi)
        per_quarter = total_due / Decimal(4)
        out: list[QuarterlyDue] = []
        cumulative_paid = Decimal(0)
        for i, due_date in enumerate(self.quarterly_due_dates(year), start=1):
            paid = payments_made.get(i, Decimal(0))
            cumulative_paid += paid
            expected_cumulative = per_quarter * Decimal(i)
            shortfall = max(expected_cumulative - cumulative_paid, Decimal(0))
            out.append(
                QuarterlyDue(
                    quarter=i,
                    due_date=due_date,
                    expected_amount=per_quarter,
                    paid_to_date=cumulative_paid,
                    shortfall=shortfall,
                )
            )
        return out

    def pace_alert(self, schedule: list[QuarterlyDue], today: date | None = None) -> dict | None:
        today = today or date.today()
        for q in schedule:
            if today > q.due_date and q.shortfall > 0:
                return {
                    "quarter": q.quarter,
                    "due_date": q.due_date.isoformat(),
                    "shortfall": float(q.shortfall),
                    "severity": "warn",
                    "message": (
                        f"Q{q.quarter} estimated tax was short ${q.shortfall:.0f} as of {q.due_date}. "
                        "Penalty interest is accruing."
                    ),
                }
            if today >= q.due_date - timedelta(days=14) and q.shortfall > 0:
                return {
                    "quarter": q.quarter,
                    "due_date": q.due_date.isoformat(),
                    "shortfall": float(q.shortfall),
                    "severity": "info",
                    "message": (
                        f"Q{q.quarter} estimated tax payment of ~${q.shortfall:.0f} due {q.due_date}."
                    ),
                }
        return None
