"""Annual income aggregation, with breakouts that 1099 categorisation requires."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Transaction
from monarch_insights.supplements.income import IncomeEvent, IncomeKind


@dataclass
class InvestmentIncomeBreakdown:
    interest: Decimal = Decimal(0)
    qualified_dividends: Decimal = Decimal(0)
    ordinary_dividends: Decimal = Decimal(0)
    short_term_gains: Decimal = Decimal(0)
    long_term_gains: Decimal = Decimal(0)


@dataclass
class IncomeReport:
    year: int
    wages: Decimal = Decimal(0)
    self_employment: Decimal = Decimal(0)
    investment: InvestmentIncomeBreakdown = field(default_factory=InvestmentIncomeBreakdown)
    rental: Decimal = Decimal(0)
    other: Decimal = Decimal(0)
    by_source: dict[str, Decimal] = field(default_factory=dict)
    estimated_withholding: Decimal = Decimal(0)

    @property
    def gross_income(self) -> Decimal:
        return (
            self.wages
            + self.self_employment
            + self.investment.interest
            + self.investment.qualified_dividends
            + self.investment.ordinary_dividends
            + self.investment.short_term_gains
            + self.investment.long_term_gains
            + self.rental
            + self.other
        )


# Heuristics for tagging Monarch transaction descriptions when no IncomeSource is wired.
_INTEREST_KEYWORDS = ("interest paid", "interest earned", "credit interest", "yield")
_DIVIDEND_KEYWORDS = ("dividend", "div paid", "div received")
_PAYROLL_KEYWORDS = ("payroll", "direct dep", "salary", "wages")


class IncomeAggregator:
    def aggregate(
        self,
        year: int,
        transactions: Iterable[Transaction] = (),
        events: Iterable[IncomeEvent] = (),
    ) -> IncomeReport:
        report = IncomeReport(year=year)
        by_source: dict[str, Decimal] = defaultdict(lambda: Decimal(0))

        # Pre-bucketed events take precedence over inferred transactions.
        for ev in events:
            if ev.on_date.year != year:
                continue
            taxable = ev.effective_taxable
            report.estimated_withholding += ev.withholding_amount
            by_source[ev.source_id] += taxable

        # Now sweep transactions for things the user hasn't yet tagged.
        for tx in transactions:
            if tx.on_date.year != year or tx.is_hidden_from_reports:
                continue
            if not tx.is_inflow:
                continue
            name = (tx.merchant_name or tx.original_description or "").lower()
            amount = tx.amount
            if any(k in name for k in _PAYROLL_KEYWORDS):
                report.wages += amount
            elif any(k in name for k in _DIVIDEND_KEYWORDS):
                report.investment.ordinary_dividends += amount
            elif any(k in name for k in _INTEREST_KEYWORDS):
                report.investment.interest += amount
            else:
                report.other += amount
        report.by_source = dict(by_source)
        return report

    def add_investment_breakdown(
        self,
        report: IncomeReport,
        breakdown: InvestmentIncomeBreakdown,
    ) -> None:
        report.investment.interest += breakdown.interest
        report.investment.ordinary_dividends += breakdown.ordinary_dividends
        report.investment.qualified_dividends += breakdown.qualified_dividends
        report.investment.short_term_gains += breakdown.short_term_gains
        report.investment.long_term_gains += breakdown.long_term_gains
