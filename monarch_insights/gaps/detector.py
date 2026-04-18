"""Detects what data we'd need next to give the user a better answer.

The goal is to be specific. Instead of "your data is incomplete", produce:
"Cost basis is missing for AAPL in Schwab Brokerage; without it we can't classify
realized gain/loss on the 22 March sale. Provide a 1099-B or enter lots manually."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.gaps.requests import InfoRequest, RequestKind, Severity
from monarch_insights.models import (
    Account,
    AccountType,
    Holding,
    RecurringStream,
    Transaction,
)
from monarch_insights.supplements.store import SupplementStore


@dataclass
class GapReport:
    """A run of the gap detector. ``requests`` is the actionable list to surface."""

    generated_at: date
    requests: list[InfoRequest] = field(default_factory=list)
    summary_by_kind: dict[str, int] = field(default_factory=dict)

    def add(self, req: InfoRequest) -> None:
        self.requests.append(req)
        self.summary_by_kind[req.kind.value] = self.summary_by_kind.get(req.kind.value, 0) + 1

    def critical(self) -> list[InfoRequest]:
        return [r for r in self.requests if r.severity == Severity.CRITICAL]

    def to_markdown(self) -> str:
        if not self.requests:
            return "*No information gaps detected today.*"
        lines = [f"# Data Gaps as of {self.generated_at.isoformat()}", ""]
        for sev in (Severity.CRITICAL, Severity.WARN, Severity.INFO):
            relevant = [r for r in self.requests if r.severity == sev]
            if not relevant:
                continue
            lines.append(f"## {sev.value.title()}")
            for r in relevant:
                lines.append(f"- **{r.kind.value}** — {r.summary}")
                if r.suggested_action:
                    lines.append(f"  - _Action_: {r.suggested_action}")
            lines.append("")
        return "\n".join(lines)


class GapDetector:
    """Walks Monarch + supplement data and emits actionable info-requests."""

    def __init__(self, store: SupplementStore) -> None:
        self.store = store

    # ---------------------------------------------------- entry point

    def run(
        self,
        accounts: Iterable[Account],
        holdings: Iterable[Holding],
        transactions: Iterable[Transaction],
        recurring: Iterable[RecurringStream] | None = None,
        persist: bool = True,
    ) -> GapReport:
        report = GapReport(generated_at=date.today())
        accounts = list(accounts)
        holdings = list(holdings)
        transactions = list(transactions)
        recurring = list(recurring or [])

        for req in self._missing_cost_basis(holdings):
            report.add(req)
        for req in self._missing_paystub_for_inflows(transactions):
            report.add(req)
        for req in self._uncategorized_or_review(transactions):
            report.add(req)
        for req in self._stale_holdings(holdings):
            report.add(req)
        for req in self._missing_account_metadata(accounts):
            report.add(req)
        for req in self._missing_allocation_targets(accounts, holdings):
            report.add(req)
        for req in self._recurring_anomalies(recurring):
            report.add(req)
        for req in self._tax_doc_check(transactions, accounts):
            report.add(req)

        if persist:
            for r in report.requests:
                self.store.add_info_request(r.to_storage_dict())
        return report

    # ---------------------------------------------------- detectors

    def _missing_cost_basis(self, holdings: Iterable[Holding]) -> list[InfoRequest]:
        out: list[InfoRequest] = []
        for h in holdings:
            ticker = (h.ticker or "").strip()
            if not ticker:
                continue
            if h.cost_basis is not None and h.cost_basis > 0:
                continue
            existing_lots = self.store.lots_for(h.account_id, ticker)
            if existing_lots:
                covered_qty = sum(Decimal(str(l["quantity"])) for l in existing_lots)
                if covered_qty >= h.quantity:
                    continue
            out.append(
                InfoRequest.new(
                    kind=RequestKind.COST_BASIS,
                    summary=f"Cost basis missing for {ticker} in account {h.account_id}",
                    severity=Severity.WARN,
                    suggested_action=(
                        f"Provide acquisition lots for {h.quantity} shares of {ticker} "
                        f"(broker 1099-B or manual entry)."
                    ),
                    related_account_id=h.account_id,
                    related_ticker=ticker,
                    detail={"quantity": str(h.quantity)},
                )
            )
        return out

    def _missing_paystub_for_inflows(
        self, transactions: Iterable[Transaction]
    ) -> list[InfoRequest]:
        candidates: dict[str, list[Transaction]] = {}
        for t in transactions:
            if not t.is_inflow:
                continue
            name = (t.merchant_name or t.original_description or "").lower()
            if any(k in name for k in ("payroll", "direct dep", "salary", "wages")):
                candidates.setdefault(t.merchant_name or "Payroll", []).append(t)
        existing_paystubs = {p["paid_on"] for p in self.store.list_paystubs()}
        out: list[InfoRequest] = []
        for employer, txs in candidates.items():
            unmatched = [t for t in txs if t.on_date.isoformat() not in existing_paystubs]
            if not unmatched:
                continue
            out.append(
                InfoRequest.new(
                    kind=RequestKind.PAYSTUB,
                    summary=(
                        f"{len(unmatched)} payroll deposits from {employer} have no matching paystub"
                    ),
                    severity=Severity.INFO,
                    suggested_action=(
                        "Upload paystub PDFs or paste gross/net amounts so we can split "
                        "FICA, withholding, 401k, HSA contributions for tax planning."
                    ),
                    detail={
                        "employer": employer,
                        "missing_dates": [t.on_date.isoformat() for t in unmatched[-12:]],
                    },
                )
            )
        return out

    def _uncategorized_or_review(self, transactions: Iterable[Transaction]) -> list[InfoRequest]:
        needs_review = [t for t in transactions if t.needs_review]
        uncategorized = [t for t in transactions if not t.category_id]
        out: list[InfoRequest] = []
        if needs_review:
            out.append(
                InfoRequest.new(
                    kind=RequestKind.CATEGORIZATION,
                    summary=f"{len(needs_review)} transactions flagged for review by Monarch",
                    severity=Severity.INFO,
                    suggested_action="Open Monarch web → Transactions → 'Needs review'.",
                    detail={"count": len(needs_review)},
                )
            )
        if uncategorized:
            recent = [t for t in uncategorized if (date.today() - t.on_date).days <= 60]
            if recent:
                out.append(
                    InfoRequest.new(
                        kind=RequestKind.CATEGORIZATION,
                        summary=f"{len(recent)} recent transactions are uncategorized",
                        severity=Severity.INFO,
                        suggested_action=(
                            "Categorize so cashflow + budget pacing alerts behave correctly."
                        ),
                        detail={"count": len(recent)},
                    )
                )
        return out

    def _stale_holdings(self, holdings: Iterable[Holding]) -> list[InfoRequest]:
        cutoff = date.today() - timedelta(days=10)
        stale = []
        for h in holdings:
            if h.last_priced_at and h.last_priced_at.date() < cutoff:
                stale.append(h)
        if not stale:
            return []
        return [
            InfoRequest.new(
                kind=RequestKind.ACCOUNT_HISTORY,
                summary=f"{len(stale)} holdings haven't been priced in over 10 days",
                severity=Severity.WARN,
                suggested_action="Force a Monarch refresh, or wire a market-data provider for nightly fills.",
                detail={"tickers": sorted({h.ticker for h in stale if h.ticker})[:25]},
            )
        ]

    def _missing_account_metadata(self, accounts: Iterable[Account]) -> list[InfoRequest]:
        manual_no_balance = [
            a for a in accounts if a.is_manual and (a.current_balance is None or a.current_balance == 0)
        ]
        out: list[InfoRequest] = []
        for a in manual_no_balance:
            out.append(
                InfoRequest.new(
                    kind=RequestKind.ACCOUNT_HISTORY,
                    summary=f"Manual account '{a.display_name}' has no balance set",
                    severity=Severity.INFO,
                    suggested_action="Set the current balance so it counts toward net worth correctly.",
                    related_account_id=a.id,
                )
            )
        return out

    def _missing_allocation_targets(
        self, accounts: Iterable[Account], holdings: Iterable[Holding]
    ) -> list[InfoRequest]:
        if not any(a.type == AccountType.BROKERAGE for a in accounts):
            return []
        targets = self.store.get_allocation_targets()
        if targets:
            return []
        return [
            InfoRequest.new(
                kind=RequestKind.ALLOCATION_TARGET,
                summary="No target asset allocation set",
                severity=Severity.INFO,
                suggested_action=(
                    "Define target % per asset bucket (US stock / intl / bonds / cash / "
                    "alts) so drift alerts can fire."
                ),
            )
        ]

    def _recurring_anomalies(self, recurring: Iterable[RecurringStream]) -> list[InfoRequest]:
        out: list[InfoRequest] = []
        no_freq = [r for r in recurring if r.frequency.value == "unknown"]
        if no_freq:
            out.append(
                InfoRequest.new(
                    kind=RequestKind.RECURRING_REVIEW,
                    summary=f"{len(no_freq)} recurring streams have an unknown cadence",
                    severity=Severity.INFO,
                    suggested_action="Confirm their frequency in Monarch so forecast math is right.",
                )
            )
        return out

    def _tax_doc_check(
        self, transactions: Iterable[Transaction], accounts: Iterable[Account]
    ) -> list[InfoRequest]:
        last_year = date.today().year - 1
        existing = {d["doc_type"] for d in self.store.list_documents(last_year)}
        out: list[InfoRequest] = []

        any_brokerage = any(a.type == AccountType.BROKERAGE for a in accounts)
        if any_brokerage and not any(d.startswith("1099") for d in existing):
            out.append(
                InfoRequest.new(
                    kind=RequestKind.TAX_DOCUMENT,
                    summary=f"No 1099 forms recorded for tax year {last_year}",
                    severity=Severity.WARN,
                    suggested_action="Download from each brokerage and add via documents store.",
                )
            )
        any_savings = any(
            a for a in accounts if (a.subtype.value or "").lower() in {"savings", "money_market", "cd"}
        )
        if any_savings and "1099-INT" not in existing:
            out.append(
                InfoRequest.new(
                    kind=RequestKind.TAX_DOCUMENT,
                    summary=f"No 1099-INT recorded for {last_year}",
                    severity=Severity.INFO,
                    suggested_action="Pull from each interest-paying account.",
                )
            )
        return out
