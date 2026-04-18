"""Gap-detector emits the right info requests."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from monarch_insights.gaps.detector import GapDetector
from monarch_insights.models import (
    Account,
    AccountType,
    Holding,
    Transaction,
)
from monarch_insights.supplements.store import SupplementStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield SupplementStore(path=Path(tmp) / "supp.db")


def test_missing_cost_basis_emitted(store):
    accounts = [
        Account.model_validate(
            {"id": "B1", "displayName": "Schwab", "type": "brokerage", "currentBalance": 100000}
        )
    ]
    holdings = [
        Holding.model_validate(
            {"id": "h1", "accountId": "B1", "ticker": "AAPL", "quantity": 10, "value": 2000}
        )
    ]
    report = GapDetector(store).run(accounts, holdings, [], persist=False)
    assert any(r.kind.value == "cost_basis" for r in report.requests)


def test_no_target_allocation_emits_request(store):
    accounts = [
        Account.model_validate(
            {"id": "B1", "displayName": "Schwab", "type": "brokerage", "currentBalance": 100000}
        )
    ]
    report = GapDetector(store).run(accounts, [], [], persist=False)
    assert any(r.kind.value == "allocation_target" for r in report.requests)
