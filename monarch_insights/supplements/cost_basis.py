"""Cost-basis tracking with FIFO/LIFO/HIFO/Specific-ID disposal logic.

Monarch tells you "you own 100 AAPL with $14k market value" — it doesn't track when each
share was purchased or for how much. Without that, you can't compute realized gains, can't
distinguish long-term from short-term, can't surface tax-loss harvesting opportunities,
can't avoid wash sales. This module fills that gap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Iterable

from monarch_insights.supplements.store import SupplementStore


class DisposalMethod(str, Enum):
    FIFO = "fifo"
    LIFO = "lifo"
    HIFO = "hifo"
    SPECIFIC = "specific"


@dataclass
class CostBasisLot:
    """A single acquisition of a security at a single price."""

    id: str
    account_id: str
    ticker: str
    quantity: Decimal
    acquired_on: date
    cost_per_share: Decimal
    fees: Decimal = Decimal(0)
    notes: str | None = None
    source: str = "manual"

    @property
    def cost_basis(self) -> Decimal:
        return (self.quantity * self.cost_per_share) + self.fees

    @property
    def is_long_term_today(self) -> bool:
        return (date.today() - self.acquired_on).days > 365

    def days_to_long_term(self) -> int:
        long_term_date = self.acquired_on + timedelta(days=366)
        delta = (long_term_date - date.today()).days
        return max(delta, 0)

    def to_storage_row(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "ticker": self.ticker,
            "quantity": str(self.quantity),
            "acquired_on": self.acquired_on.isoformat(),
            "cost_per_share": str(self.cost_per_share),
            "fees": str(self.fees),
            "source": self.source,
            "notes": self.notes,
        }


@dataclass
class DisposalResult:
    lot_id: str
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    realized_gain: Decimal
    long_term: bool
    acquired_on: date
    disposed_on: date

    @property
    def holding_period_days(self) -> int:
        return (self.disposed_on - self.acquired_on).days


@dataclass
class CostBasisLedger:
    """In-memory ledger of lots for a single (account, ticker) pair."""

    account_id: str
    ticker: str
    lots: list[CostBasisLot] = field(default_factory=list)

    @classmethod
    def from_store(cls, store: SupplementStore, account_id: str, ticker: str) -> CostBasisLedger:
        lots = []
        for row in store.lots_for(account_id, ticker):
            lots.append(
                CostBasisLot(
                    id=row["id"],
                    account_id=row["account_id"],
                    ticker=row["ticker"],
                    quantity=Decimal(str(row["quantity"])),
                    acquired_on=date.fromisoformat(row["acquired_on"]),
                    cost_per_share=Decimal(str(row["cost_per_share"])),
                    fees=Decimal(str(row.get("fees") or 0)),
                    notes=row.get("notes"),
                    source=row.get("source") or "manual",
                )
            )
        return cls(account_id=account_id, ticker=ticker, lots=lots)

    @property
    def total_quantity(self) -> Decimal:
        return sum((l.quantity for l in self.lots), Decimal(0))

    @property
    def total_cost_basis(self) -> Decimal:
        return sum((l.cost_basis for l in self.lots), Decimal(0))

    @property
    def average_cost(self) -> Decimal | None:
        if self.total_quantity == 0:
            return None
        return self.total_cost_basis / self.total_quantity

    def add_lot(self, lot: CostBasisLot) -> None:
        self.lots.append(lot)
        self.lots.sort(key=lambda l: l.acquired_on)

    def order(self, method: DisposalMethod, specific_lot_ids: Iterable[str] | None = None) -> list[CostBasisLot]:
        if method == DisposalMethod.FIFO:
            return sorted(self.lots, key=lambda l: l.acquired_on)
        if method == DisposalMethod.LIFO:
            return sorted(self.lots, key=lambda l: l.acquired_on, reverse=True)
        if method == DisposalMethod.HIFO:
            return sorted(self.lots, key=lambda l: l.cost_per_share, reverse=True)
        if method == DisposalMethod.SPECIFIC:
            if not specific_lot_ids:
                raise ValueError("Specific-ID requires lot IDs")
            ordered = []
            by_id = {l.id: l for l in self.lots}
            for lid in specific_lot_ids:
                if lid not in by_id:
                    raise KeyError(f"Lot {lid} not in ledger for {self.ticker}")
                ordered.append(by_id[lid])
            return ordered
        raise ValueError(f"Unknown method: {method}")

    def simulate_disposal(
        self,
        quantity: Decimal,
        price_per_share: Decimal,
        disposed_on: date | None = None,
        method: DisposalMethod = DisposalMethod.FIFO,
        specific_lot_ids: Iterable[str] | None = None,
    ) -> list[DisposalResult]:
        """Compute realized gains for a hypothetical or actual sale.

        Does NOT mutate the ledger — call ``apply_disposal`` to record one.
        """
        disposed_on = disposed_on or date.today()
        remaining = quantity
        results: list[DisposalResult] = []
        for lot in self.order(method, specific_lot_ids):
            if remaining <= 0:
                break
            take = min(lot.quantity, remaining)
            if take <= 0:
                continue
            proceeds = take * price_per_share
            basis = take * lot.cost_per_share
            results.append(
                DisposalResult(
                    lot_id=lot.id,
                    quantity=take,
                    proceeds=proceeds,
                    cost_basis=basis,
                    realized_gain=proceeds - basis,
                    long_term=(disposed_on - lot.acquired_on).days > 365,
                    acquired_on=lot.acquired_on,
                    disposed_on=disposed_on,
                )
            )
            remaining -= take
        if remaining > 0:
            raise ValueError(
                f"Insufficient lots to dispose {quantity} {self.ticker} — short by {remaining}"
            )
        return results

    def apply_disposal(
        self,
        store: SupplementStore,
        quantity: Decimal,
        price_per_share: Decimal,
        disposed_on: date,
        method: DisposalMethod = DisposalMethod.FIFO,
        transaction_id: str | None = None,
        specific_lot_ids: Iterable[str] | None = None,
    ) -> list[DisposalResult]:
        results = self.simulate_disposal(
            quantity, price_per_share, disposed_on, method, specific_lot_ids
        )
        for r in results:
            store.add_disposal(
                {
                    "id": str(uuid.uuid4()),
                    "lot_id": r.lot_id,
                    "quantity": float(r.quantity),
                    "disposed_on": r.disposed_on.isoformat(),
                    "proceeds": float(r.proceeds),
                    "fees": 0.0,
                    "transaction_id": transaction_id,
                    "notes": None,
                }
            )
            for lot in self.lots:
                if lot.id == r.lot_id:
                    lot.quantity -= r.quantity
                    if lot.quantity > 0:
                        # write the depleted lot back
                        store.add_lot(
                            {
                                **lot.to_storage_row(),
                                "quantity": float(lot.quantity),
                            }
                        )
                    break
        return results


def detect_wash_sale_window(
    disposal: DisposalResult, ledger: CostBasisLedger
) -> list[CostBasisLot]:
    """Return lots acquired within ±30 days of the disposal that could trigger wash-sale rules.

    Doesn't apply the IRS adjustment — the goal is to *flag* candidates so the user can
    decide. Wash-sale law applies across all of a taxpayer's accounts (incl. spouse's
    IRA), not just one brokerage, so this is a starting filter, not a verdict.
    """
    window_start = disposal.disposed_on - timedelta(days=30)
    window_end = disposal.disposed_on + timedelta(days=30)
    return [
        l
        for l in ledger.lots
        if window_start <= l.acquired_on <= window_end and l.id != disposal.lot_id
    ]
