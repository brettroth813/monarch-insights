"""Behaviour tests for the major insight modules."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.insights.recurring import RecurringInsights
from monarch_insights.insights.spending import SpendingInsights
from monarch_insights.models import (
    Account,
    AccountType,
    Holding,
    RecurringStream,
    Transaction,
)


def _make_account(id_, type_, balance, liability=False):
    return Account.model_validate(
        {
            "id": id_,
            "displayName": id_,
            "type": type_,
            "currentBalance": balance,
            "isAsset": not liability,
            "includeInNetWorth": True,
        }
    )


def test_networth_breakdown_handles_liabilities():
    accounts = [
        _make_account("checking", "depository", 1000),
        _make_account("brokerage", "brokerage", 50000),
        _make_account("amex", "credit", 500, liability=True),
    ]
    bd = NetWorthInsights.snapshot(accounts)
    assert bd.assets == Decimal(51000)
    assert bd.liabilities == Decimal(500)
    assert bd.net_worth == Decimal(50500)


def test_top_categories_sorted_by_total():
    txs = [
        Transaction.model_validate(
            {"id": str(i), "date": "2026-04-15", "amount": -amt, "accountId": "A",
             "categoryId": cid, "categoryName": name, "tags": []}
        )
        for i, (amt, cid, name) in enumerate(
            [(50, "c1", "Groceries"), (25, "c1", "Groceries"), (200, "c2", "Travel")]
        )
    ]
    top = SpendingInsights.top_categories(txs, limit=5)
    assert top[0].category_name == "Travel"
    assert top[0].total == Decimal(200)
    assert top[1].category_name == "Groceries"
    assert top[1].total == Decimal(75)


def test_cashflow_monthly():
    txs = [
        Transaction.model_validate(
            {"id": "1", "date": "2026-03-01", "amount": 5000, "accountId": "A", "tags": []}
        ),
        Transaction.model_validate(
            {"id": "2", "date": "2026-03-15", "amount": -2500, "accountId": "A", "tags": []}
        ),
    ]
    monthly = CashflowInsights.monthly(txs, months=6)
    assert any(m.month == "2026-03" for m in monthly)
    march = next(m for m in monthly if m.month == "2026-03")
    assert march.income == Decimal(5000)
    assert march.expense == Decimal(2500)
    assert march.savings_rate == Decimal("0.5")


def test_investment_drift():
    holdings = [
        Holding.model_validate(
            {"id": "h1", "accountId": "B1", "ticker": "VTI", "quantity": 100, "value": 25000}
        ),
        Holding.model_validate(
            {"id": "h2", "accountId": "B1", "ticker": "VXUS", "quantity": 200, "value": 5000}
        ),
        Holding.model_validate(
            {"id": "h3", "accountId": "B1", "ticker": "BND", "quantity": 50, "value": 5000}
        ),
    ]
    targets = {
        "us_stock": {"target_pct": 60, "drift_threshold_pct": 5},
        "intl_stock": {"target_pct": 25, "drift_threshold_pct": 5},
        "bond": {"target_pct": 15, "drift_threshold_pct": 5},
    }
    drift = InvestmentInsights().drift(holdings, targets)
    over = [d for d in drift if d.over_threshold]
    assert any(d.bucket == "us_stock" and d.drift_pct > 0 for d in over)


def test_recurring_duplicate_detection():
    streams = [
        RecurringStream.model_validate(
            {"id": "s1", "name": "Netflix", "frequency": "monthly", "averageAmount": 15.99}
        ),
        RecurringStream.model_validate(
            {"id": "s2", "name": "NETFLIX", "frequency": "monthly", "averageAmount": 9.99}
        ),
    ]
    dupes = RecurringInsights.find_duplicates(streams)
    assert dupes
    assert dupes[0].total_monthly == Decimal("25.98")
