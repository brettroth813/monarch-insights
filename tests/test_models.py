"""Smoke tests for the model layer — make sure aliases + types coerce correctly."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from monarch_insights.models import (
    Account,
    AccountType,
    Holding,
    Transaction,
)


def test_account_aliases_and_signed_balance():
    raw = {
        "id": "A1",
        "displayName": "Chase Checking",
        "type": "depository",
        "subtype": "checking",
        "currentBalance": "1234.56",
        "isAsset": True,
        "includeInNetWorth": True,
        "currency": "USD",
    }
    a = Account.model_validate(raw)
    assert a.display_name == "Chase Checking"
    assert a.type == AccountType.DEPOSITORY
    assert a.current_balance == Decimal("1234.56")
    assert a.signed_balance == Decimal("1234.56")
    assert a.is_liability is False


def test_account_unknown_type_falls_back():
    raw = {"id": "A2", "displayName": "Weird", "type": "alien_holding"}
    a = Account.model_validate(raw)
    assert a.type == AccountType.OTHER


def test_transaction_signs_and_helpers():
    t = Transaction.model_validate(
        {
            "id": "T1",
            "date": "2026-04-15",
            "amount": -42.5,
            "accountId": "A1",
            "tags": [],
        }
    )
    assert t.is_outflow
    assert not t.is_inflow
    assert t.absolute_amount == Decimal("42.5")
    assert t.on_date == date(2026, 4, 15)


def test_holding_unrealized_math():
    h = Holding.model_validate(
        {
            "id": "H1",
            "accountId": "B1",
            "ticker": "AAPL",
            "quantity": 100,
            "costBasis": 14000,
            "value": 19000,
        }
    )
    assert h.best_value == Decimal(19000)
    assert h.unrealized_gain == Decimal(5000)
    assert h.unrealized_gain_pct == Decimal(5000) / Decimal(14000)
