"""Capital gains report + tax-loss harvesting candidate identifier."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Holding
from monarch_insights.supplements.cost_basis import CostBasisLedger, DisposalResult, detect_wash_sale_window
from monarch_insights.supplements.store import SupplementStore


@dataclass
class RealizedGainEntry:
    ticker: str
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    realized_gain: Decimal
    long_term: bool
    disposed_on: date
    acquired_on: date
    wash_sale_flag: bool = False


@dataclass
class CapitalGainsReport:
    year: int
    short_term_total: Decimal = Decimal(0)
    long_term_total: Decimal = Decimal(0)
    entries: list[RealizedGainEntry] = field(default_factory=list)
    wash_sale_count: int = 0

    @property
    def net_total(self) -> Decimal:
        return self.short_term_total + self.long_term_total


def report_for(
    store: SupplementStore,
    year: int,
    disposals: Iterable[DisposalResult],
) -> CapitalGainsReport:
    report = CapitalGainsReport(year=year)
    ledger_cache: dict[tuple[str, str], CostBasisLedger] = {}
    for d in disposals:
        if d.disposed_on.year != year:
            continue
        ticker = "UNKNOWN"
        # Walk lots to find ticker for this lot id
        for row in store.all_lots():
            if row["id"] == d.lot_id:
                ticker = row["ticker"]
                account_id = row["account_id"]
                key = (account_id, ticker)
                if key not in ledger_cache:
                    ledger_cache[key] = CostBasisLedger.from_store(store, account_id, ticker)
                wash_lots = detect_wash_sale_window(d, ledger_cache[key])
                wash_flag = bool(wash_lots)
                break
        else:
            wash_flag = False
        entry = RealizedGainEntry(
            ticker=ticker,
            quantity=d.quantity,
            proceeds=d.proceeds,
            cost_basis=d.cost_basis,
            realized_gain=d.realized_gain,
            long_term=d.long_term,
            disposed_on=d.disposed_on,
            acquired_on=d.acquired_on,
            wash_sale_flag=wash_flag,
        )
        report.entries.append(entry)
        if d.long_term:
            report.long_term_total += d.realized_gain
        else:
            report.short_term_total += d.realized_gain
        if wash_flag:
            report.wash_sale_count += 1
    return report


def harvest_candidates(
    holdings: Iterable[Holding],
    *,
    min_loss: Decimal = Decimal(500),
    cost_basis_lookup=None,
) -> list[dict]:
    """Find holdings whose unrealized loss is large enough to be worth harvesting."""
    out = []
    for h in holdings:
        cost = h.cost_basis
        if cost is None and cost_basis_lookup:
            cost = cost_basis_lookup(h.account_id, (h.ticker or "").upper())
        if cost is None:
            continue
        mv = h.best_value
        if mv is None:
            continue
        loss = cost - mv
        if loss >= min_loss:
            out.append(
                {
                    "ticker": h.ticker,
                    "account_id": h.account_id,
                    "quantity": float(h.quantity),
                    "cost_basis": float(cost),
                    "market_value": float(mv),
                    "unrealized_loss": float(loss),
                    "loss_pct": float(loss / cost) if cost else None,
                }
            )
    out.sort(key=lambda r: r["unrealized_loss"], reverse=True)
    return out
