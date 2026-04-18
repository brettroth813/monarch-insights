"""Anomaly detection — surprising spending, gray charges, balance dips."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, stdev
from typing import Iterable

from monarch_insights.models import Transaction


@dataclass
class SpendingAnomaly:
    kind: str
    summary: str
    transaction_id: str | None
    merchant_name: str | None
    amount: Decimal
    expected_range: tuple[Decimal, Decimal] | None = None
    z_score: float | None = None
    on_date: date | None = None


class AnomalyDetector:
    def __init__(self, *, z_threshold: float = 3.0, lookback_days: int = 180) -> None:
        self.z_threshold = z_threshold
        self.lookback_days = lookback_days

    def per_merchant_outliers(self, transactions: Iterable[Transaction]) -> list[SpendingAnomaly]:
        cutoff = date.today() - timedelta(days=self.lookback_days)
        groups: dict[str, list[Transaction]] = defaultdict(list)
        for t in transactions:
            if not t.is_outflow or t.is_hidden_from_reports or t.on_date < cutoff:
                continue
            key = t.merchant_name or t.original_description or "(unknown)"
            groups[key].append(t)
        out: list[SpendingAnomaly] = []
        for merchant, txs in groups.items():
            if len(txs) < 5:
                continue
            amounts = [float(abs(t.amount)) for t in txs]
            mu = mean(amounts)
            sigma = stdev(amounts) if len(amounts) > 1 else 0
            if sigma == 0:
                continue
            for t in txs:
                z = (float(abs(t.amount)) - mu) / sigma
                if z >= self.z_threshold:
                    out.append(
                        SpendingAnomaly(
                            kind="merchant_outlier",
                            summary=f"{merchant} charge of ${abs(t.amount):.2f} is {z:.1f}σ above usual",
                            transaction_id=t.id,
                            merchant_name=merchant,
                            amount=abs(t.amount),
                            expected_range=(Decimal(str(mu - 2 * sigma)), Decimal(str(mu + 2 * sigma))),
                            z_score=z,
                            on_date=t.on_date,
                        )
                    )
        return out

    def gray_charge_candidates(self, transactions: Iterable[Transaction]) -> list[SpendingAnomaly]:
        """Tiny recurring charges that often slip past the user (free trial converts, etc.)."""
        out: list[SpendingAnomaly] = []
        for t in transactions:
            if not t.is_outflow or t.is_hidden_from_reports:
                continue
            amount = abs(t.amount)
            if Decimal("0.99") <= amount <= Decimal("9.99") and t.is_recurring:
                out.append(
                    SpendingAnomaly(
                        kind="gray_charge",
                        summary=f"Small recurring charge ${amount:.2f} at {t.merchant_name}",
                        transaction_id=t.id,
                        merchant_name=t.merchant_name,
                        amount=amount,
                        on_date=t.on_date,
                    )
                )
        return out

    def category_spike(self, transactions: Iterable[Transaction], months: int = 3) -> list[SpendingAnomaly]:
        cutoff_recent = date.today() - timedelta(days=30)
        cutoff_baseline = date.today() - timedelta(days=months * 30)
        recent: dict[str | None, Decimal] = defaultdict(lambda: Decimal(0))
        baseline: dict[str | None, Decimal] = defaultdict(lambda: Decimal(0))
        names: dict[str | None, str] = {}
        for t in transactions:
            if not t.is_outflow or t.is_hidden_from_reports:
                continue
            names[t.category_id] = t.category_name or "(uncategorized)"
            if t.on_date >= cutoff_recent:
                recent[t.category_id] += abs(t.amount)
            elif t.on_date >= cutoff_baseline:
                baseline[t.category_id] += abs(t.amount)
        out: list[SpendingAnomaly] = []
        for cid, recent_total in recent.items():
            base = baseline.get(cid, Decimal(0)) / max(months - 1, 1)
            if base == 0:
                continue
            ratio = recent_total / base
            if ratio >= Decimal("1.5"):
                out.append(
                    SpendingAnomaly(
                        kind="category_spike",
                        summary=(
                            f"{names[cid]} spending is {ratio:.1f}× the trailing baseline "
                            f"(${recent_total:.0f} vs ${base:.0f}/mo)"
                        ),
                        transaction_id=None,
                        merchant_name=None,
                        amount=recent_total,
                    )
                )
        return out
