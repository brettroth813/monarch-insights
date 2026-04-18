"""Recurring / subscription intelligence — duplicate detection, price creep, idle subs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import RecurringStream, Transaction


@dataclass
class SubscriptionAlert:
    kind: str
    summary: str
    severity: str  # info | warn
    detail: dict


@dataclass
class SubscriptionDuplicate:
    merchant_name: str
    streams: list[str]
    total_monthly: Decimal


KNOWN_SUBSCRIPTION_KEYWORDS = {
    "netflix", "hulu", "spotify", "apple music", "apple tv", "youtube",
    "amazon prime", "disney", "hbo", "max", "paramount", "peacock", "audible",
    "patreon", "substack", "github", "openai", "anthropic", "icloud",
    "dropbox", "google one", "1password", "lastpass", "linkedin",
    "nyt", "wsj", "washington post", "the atlantic",
}


class RecurringInsights:
    @staticmethod
    def find_duplicates(streams: Iterable[RecurringStream]) -> list[SubscriptionDuplicate]:
        groups: dict[str, list[RecurringStream]] = defaultdict(list)
        for s in streams:
            if s.is_income:
                continue
            normalized = (s.name or "").strip().lower()
            normalized = "".join(ch for ch in normalized if ch.isalnum() or ch == " ").strip()
            if not normalized:
                continue
            groups[normalized].append(s)
        out: list[SubscriptionDuplicate] = []
        for name, items in groups.items():
            if len(items) < 2:
                continue
            total = sum(
                ((s.average_amount or s.next_amount or Decimal(0)) for s in items),
                Decimal(0),
            )
            out.append(
                SubscriptionDuplicate(
                    merchant_name=items[0].name or name.title(),
                    streams=[s.id for s in items],
                    total_monthly=total,
                )
            )
        return out

    @staticmethod
    def detect_price_creep(
        transactions: Iterable[Transaction],
        lookback_months: int = 12,
        threshold_pct: float = 0.10,
    ) -> list[SubscriptionAlert]:
        cutoff = date.today() - timedelta(days=lookback_months * 30)
        groups: dict[str, list[Transaction]] = defaultdict(list)
        for t in transactions:
            if not t.is_outflow or t.is_hidden_from_reports or t.on_date < cutoff:
                continue
            if not t.is_recurring and not _looks_like_sub(t):
                continue
            groups[(t.merchant_name or "").strip().lower()].append(t)
        out: list[SubscriptionAlert] = []
        for name, txs in groups.items():
            if not name or len(txs) < 4:
                continue
            txs_sorted = sorted(txs, key=lambda x: x.on_date)
            first_amt = abs(txs_sorted[0].amount)
            last_amt = abs(txs_sorted[-1].amount)
            if first_amt <= 0:
                continue
            change = (last_amt - first_amt) / first_amt
            if change >= threshold_pct:
                out.append(
                    SubscriptionAlert(
                        kind="price_creep",
                        summary=(
                            f"{name.title()} went from ${first_amt:.2f} → ${last_amt:.2f} "
                            f"({change:.0%}) over the last {lookback_months} months"
                        ),
                        severity="warn" if change >= 0.20 else "info",
                        detail={
                            "merchant": name,
                            "first_amount": float(first_amt),
                            "last_amount": float(last_amt),
                            "change_pct": float(change),
                        },
                    )
                )
        return out

    @staticmethod
    def detect_idle_subscriptions(streams: Iterable[RecurringStream]) -> list[SubscriptionAlert]:
        out: list[SubscriptionAlert] = []
        cutoff = date.today() - timedelta(days=120)
        for s in streams:
            if s.is_income or not s.is_active:
                continue
            if s.last_date and s.last_date < cutoff:
                out.append(
                    SubscriptionAlert(
                        kind="idle_subscription",
                        summary=(
                            f"{s.name}: last seen {s.last_date.isoformat()} but still flagged active"
                        ),
                        severity="info",
                        detail={"stream_id": s.id, "last_date": s.last_date.isoformat()},
                    )
                )
        return out


def _looks_like_sub(t: Transaction) -> bool:
    name = (t.merchant_name or t.original_description or "").lower()
    return any(k in name for k in KNOWN_SUBSCRIPTION_KEYWORDS)
