"""Coverage for the extended gap-detector rules."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from monarch_insights.gaps.extra_rules import (
    detect_concentration_risk,
    detect_dormant_accounts,
    detect_duplicate_accounts,
    detect_mortgage_escrow,
    detect_unreviewed_refunds,
)
from monarch_insights.models import Account, Holding, Transaction


def _acct(id_: str, name: str, institution: str = "Bank") -> Account:
    return Account.model_validate(
        {
            "id": id_,
            "displayName": name,
            "type": "depository",
            "currentBalance": 100,
            "isAsset": True,
            "includeInNetWorth": True,
            "institution": {"id": institution, "name": institution},
        }
    )


def _tx(account_id: str, amount: float, on_date: date, merchant: str = "Whole Foods") -> Transaction:
    return Transaction.model_validate(
        {
            "id": f"T-{on_date.isoformat()}-{account_id}-{merchant}",
            "date": on_date.isoformat(),
            "amount": amount,
            "accountId": account_id,
            "merchantName": merchant,
            "tags": [],
        }
    )


def test_dormant_accounts_flagged():
    accounts = [_acct("A1", "Active"), _acct("A2", "Idle")]
    txs = [_tx("A1", -50, date.today())]
    out = detect_dormant_accounts(accounts, txs, inactive_days=30)
    assert any(r.related_account_id == "A2" for r in out)
    assert all(r.related_account_id != "A1" for r in out)


def test_duplicate_accounts_flagged():
    accounts = [
        _acct("A1", "Checking", institution="Chase"),
        _acct("A2", "checking", institution="Chase"),
    ]
    out = detect_duplicate_accounts(accounts)
    assert out
    assert out[0].kind.value == "account_history"


def test_mortgage_escrow_only_when_both_present():
    today = date.today()
    txs_one = [_tx("A1", -2000, today, merchant="Chase Mortgage")]
    assert detect_mortgage_escrow(txs_one) == []
    txs_both = [
        _tx("A1", -2000, today, merchant="Chase Mortgage"),
        _tx("A1", -1500, today, merchant="Property Tax County"),
    ]
    assert detect_mortgage_escrow(txs_both)


def test_concentration_risk_flags_large_position():
    holdings = [
        Holding.model_validate(
            {"id": "H1", "accountId": "B1", "ticker": "NVDA", "quantity": 100, "value": 80000}
        ),
        Holding.model_validate(
            {"id": "H2", "accountId": "B1", "ticker": "VTI", "quantity": 50, "value": 20000}
        ),
    ]
    out = detect_concentration_risk(holdings, threshold_pct=Decimal("15"))
    assert any(r.related_ticker == "NVDA" for r in out)


def test_unreviewed_refunds_flagged():
    today = date.today()
    txs = [
        Transaction.model_validate(
            {
                "id": "T-r1",
                "date": today.isoformat(),
                "amount": 25.00,
                "accountId": "A1",
                "merchantName": "Amazon Refund",
                "tags": [],
            }
        ),
        Transaction.model_validate(
            {
                "id": "T-r2",
                "date": today.isoformat(),
                "amount": 100.00,
                "accountId": "A1",
                "merchantName": "Payroll",
                "categoryId": "CAT_income",
                "tags": [],
            }
        ),
    ]
    out = detect_unreviewed_refunds(txs)
    assert out
    assert "refunds" in out[0].summary.lower()
