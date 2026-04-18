"""Year-end tax packets — a single artifact you can hand to your CPA or paste into TurboTax."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from monarch_insights.tax.capital_gains import CapitalGainsReport
from monarch_insights.tax.deductions import DeductionCandidate
from monarch_insights.tax.income import IncomeReport


@dataclass
class TaxPacket:
    year: int
    income: IncomeReport
    deductions: list[DeductionCandidate] = field(default_factory=list)
    capital_gains: CapitalGainsReport | None = None
    documents: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_deductions(self) -> Decimal:
        return sum((d.amount for d in self.deductions), Decimal(0))

    def to_markdown(self) -> str:
        lines = [f"# Tax packet — {self.year}", ""]
        lines.append("## Income")
        lines.append(f"- Wages: ${self.income.wages:,.0f}")
        lines.append(f"- Self-employment: ${self.income.self_employment:,.0f}")
        lines.append(f"- Interest: ${self.income.investment.interest:,.0f}")
        lines.append(
            f"- Ordinary dividends: ${self.income.investment.ordinary_dividends:,.0f}"
        )
        lines.append(
            f"- Qualified dividends: ${self.income.investment.qualified_dividends:,.0f}"
        )
        lines.append(
            f"- Short-term capital gains: ${self.income.investment.short_term_gains:,.0f}"
        )
        lines.append(
            f"- Long-term capital gains: ${self.income.investment.long_term_gains:,.0f}"
        )
        lines.append(f"- Rental: ${self.income.rental:,.0f}")
        lines.append(f"- Other: ${self.income.other:,.0f}")
        lines.append(f"- **Gross income: ${self.income.gross_income:,.0f}**")
        lines.append("")

        if self.deductions:
            lines.append("## Deduction candidates")
            for d in self.deductions:
                lines.append(f"- {d.label}: ${d.amount:,.0f} ({len(d.transaction_ids)} txns)")
            lines.append(f"- **Total: ${self.total_deductions:,.0f}**")
            lines.append("")

        if self.capital_gains:
            lines.append("## Realized capital gains")
            lines.append(f"- Short-term: ${self.capital_gains.short_term_total:,.0f}")
            lines.append(f"- Long-term: ${self.capital_gains.long_term_total:,.0f}")
            if self.capital_gains.wash_sale_count:
                lines.append(
                    f"- ⚠️ {self.capital_gains.wash_sale_count} wash-sale candidates flagged"
                )
            lines.append("")

        if self.documents:
            lines.append("## Documents on file")
            for doc in self.documents:
                lines.append(f"- {doc.get('doc_type')}: {doc.get('title')}")
            lines.append("")

        if self.notes:
            lines.append("## Notes")
            for n in self.notes:
                lines.append(f"- {n}")
        return "\n".join(lines)


def build_packet(
    year: int,
    income: IncomeReport,
    deductions: Iterable[DeductionCandidate] = (),
    capital_gains: CapitalGainsReport | None = None,
    documents: Iterable[dict] = (),
    notes: Iterable[str] = (),
) -> TaxPacket:
    return TaxPacket(
        year=year,
        income=income,
        deductions=list(deductions),
        capital_gains=capital_gains,
        documents=list(documents),
        notes=list(notes),
    )
