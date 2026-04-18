"""Additional gap-detector rules layered on top of :class:`GapDetector`.

These are intentionally separated so the core detector stays small and easy to read,
while specialised checks (dormant accounts, duplicate accounts, mortgage escrow, FX
freshness) live alongside their explanatory docstrings.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.gaps.requests import InfoRequest, RequestKind, Severity
from monarch_insights.models import Account, Holding, Transaction


def detect_dormant_accounts(
    accounts: Iterable[Account],
    transactions: Iterable[Transaction],
    *,
    inactive_days: int = 180,
) -> list[InfoRequest]:
    """Surface accounts that haven't had a transaction in ``inactive_days``.

    A dormant credit card or HYSA could be quietly accruing fees, missing rate
    promotions, or representing a closed account that Monarch hasn't reflected yet.
    """
    cutoff = date.today() - timedelta(days=inactive_days)
    last_seen: dict[str, date] = defaultdict(lambda: date(1970, 1, 1))
    for tx in transactions:
        if tx.account_id and tx.on_date > last_seen[tx.account_id]:
            last_seen[tx.account_id] = tx.on_date

    out: list[InfoRequest] = []
    for account in accounts:
        if account.is_hidden or not account.include_in_net_worth:
            continue
        if account.is_manual:
            # Manual balances aren't expected to have transactions.
            continue
        if last_seen[account.id] >= cutoff:
            continue
        out.append(
            InfoRequest.new(
                kind=RequestKind.ACCOUNT_HISTORY,
                summary=(
                    f"{account.display_name} has had no transactions in {inactive_days}+ days — "
                    "verify the account is still active and syncing."
                ),
                severity=Severity.INFO,
                suggested_action=(
                    "Confirm the account is intentional. If closed, hide it in Monarch."
                ),
                related_account_id=account.id,
                detail={"last_transaction": last_seen[account.id].isoformat()},
            )
        )
    return out


def detect_duplicate_accounts(accounts: Iterable[Account]) -> list[InfoRequest]:
    """Spot accounts with suspiciously similar display names within the same institution."""
    grouped: dict[str, list[Account]] = defaultdict(list)
    for a in accounts:
        if a.is_hidden:
            continue
        institution = a.institution.name if a.institution else "Manual"
        key = f"{institution}|{(a.display_name or '').strip().lower()}"
        grouped[key].append(a)
    out: list[InfoRequest] = []
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        out.append(
            InfoRequest.new(
                kind=RequestKind.ACCOUNT_HISTORY,
                summary=(
                    f"{len(items)} accounts share the name '{items[0].display_name}'"
                    f" at {items[0].institution.name if items[0].institution else 'Manual'}"
                ),
                severity=Severity.INFO,
                suggested_action="Rename one for clarity, or hide the duplicate.",
                detail={"account_ids": [a.id for a in items]},
            )
        )
    return out


def detect_mortgage_escrow(transactions: Iterable[Transaction]) -> list[InfoRequest]:
    """If we see mortgage payments + property tax separately, the escrow may be double-counted."""
    has_mortgage = False
    has_property_tax = False
    for tx in transactions:
        name = (tx.merchant_name or tx.original_description or "").lower()
        if "mortgage" in name and tx.is_outflow:
            has_mortgage = True
        if "property tax" in name and tx.is_outflow:
            has_property_tax = True
        if has_mortgage and has_property_tax:
            break
    if not (has_mortgage and has_property_tax):
        return []
    return [
        InfoRequest.new(
            kind=RequestKind.CATEGORIZATION,
            summary=(
                "Detected separate mortgage *and* property-tax outflows — "
                "if your lender escrows taxes, this could be double-counting."
            ),
            severity=Severity.WARN,
            suggested_action=(
                "Confirm whether the property-tax payment is reimbursed to escrow. If so, "
                "exclude one from reports to avoid inflating expenses."
            ),
        )
    ]


def detect_concentration_risk(
    holdings: Iterable[Holding],
    *,
    threshold_pct: Decimal = Decimal("15"),
) -> list[InfoRequest]:
    """When a single ticker exceeds ``threshold_pct`` of portfolio value, flag it."""
    holdings = list(holdings)
    total_value = sum((h.best_value or Decimal(0) for h in holdings), Decimal(0))
    if total_value == 0:
        return []
    by_ticker: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for h in holdings:
        if h.best_value is None:
            continue
        by_ticker[(h.ticker or "UNKNOWN").upper()] += h.best_value
    out: list[InfoRequest] = []
    for ticker, value in by_ticker.items():
        pct = (value / total_value) * Decimal(100)
        if pct >= threshold_pct:
            out.append(
                InfoRequest.new(
                    kind=RequestKind.GOAL_DETAIL,
                    summary=(
                        f"{ticker} represents {float(pct):.1f}% of your portfolio — "
                        "consider whether the concentration is intentional."
                    ),
                    severity=Severity.INFO,
                    suggested_action=(
                        f"If you want to diversify, sell ~${float(value - total_value * threshold_pct/Decimal(100)):,.0f} "
                        f"and rebalance into your target allocation."
                    ),
                    related_ticker=ticker,
                    detail={"value": float(value), "pct": float(pct)},
                )
            )
    return out


def detect_unreviewed_refunds(transactions: Iterable[Transaction]) -> list[InfoRequest]:
    """Inflows that look like refunds but aren't categorized — they distort income reports."""
    refunds_no_cat = []
    for tx in transactions:
        if not tx.is_inflow or tx.is_hidden_from_reports:
            continue
        if tx.category_id:
            continue
        name = (tx.merchant_name or tx.original_description or "").lower()
        if any(k in name for k in ("refund", "return", "reimbursement", "credit")):
            refunds_no_cat.append(tx)
    if not refunds_no_cat:
        return []
    return [
        InfoRequest.new(
            kind=RequestKind.CATEGORIZATION,
            summary=(
                f"{len(refunds_no_cat)} inflows look like refunds but aren't categorized — "
                "they're inflating reported income."
            ),
            severity=Severity.INFO,
            suggested_action=(
                "Categorize them as 'Refund' or attach to the original spending category "
                "so cashflow stays accurate."
            ),
            detail={"transaction_ids": [t.id for t in refunds_no_cat[-10:]]},
        )
    ]
