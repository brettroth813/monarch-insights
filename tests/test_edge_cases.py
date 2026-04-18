"""Edge-case coverage that the happy-path tests don't touch.

Categories:

* Empty / None / missing-field tolerance on Pydantic models.
* Schema-drift behaviour on the API client error classifier.
* Decimal precision — JSON round-trip should not lose cents.
* Time-zone boundaries — cashflow bucketing around UTC midnight.
* Large-dataset sanity — 5000 transactions still renders insights in under a second.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.exceptions import (
    MonarchAuthError,
    MonarchNotFound,
    MonarchRateLimited,
    MonarchSchemaDrift,
)
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.insights.spending import SpendingInsights
from monarch_insights.models import Account, Holding, Transaction


# ---------------------------------------------------------------------------
# Empty / None tolerance
# ---------------------------------------------------------------------------


def test_empty_accounts_list_produces_zero_networth():
    bd = NetWorthInsights.snapshot([])
    assert bd.assets == Decimal(0)
    assert bd.liabilities == Decimal(0)
    assert bd.net_worth == Decimal(0)


def test_empty_transactions_returns_empty_monthly():
    assert CashflowInsights.monthly([]) == []


def test_holding_with_no_cost_basis_reports_none_gain():
    h = Holding.model_validate(
        {"id": "H", "accountId": "A", "ticker": "AAPL", "quantity": 10, "value": 2000}
    )
    assert h.cost_basis is None
    assert h.unrealized_gain is None
    assert h.unrealized_gain_pct is None


def test_account_with_none_balance_has_no_signed_balance():
    a = Account.model_validate(
        {"id": "A", "displayName": "X", "type": "depository", "currentBalance": None}
    )
    assert a.signed_balance is None


def test_transaction_accepts_missing_tags_and_category():
    t = Transaction.model_validate(
        {"id": "T", "date": "2026-04-18", "amount": -10, "accountId": "A"}
    )
    assert t.tag_ids == []
    assert t.category_id is None


# ---------------------------------------------------------------------------
# Schema-drift classification
# ---------------------------------------------------------------------------


def test_classifier_maps_unknown_field_to_schema_drift():
    payload = {"errors": [{"message": "Cannot query field 'foo' on type 'Bar'"}]}
    with pytest.raises(MonarchSchemaDrift) as excinfo:
        MonarchClient._raise_for_errors("GetAccounts", payload)
    assert "GetAccounts" in str(excinfo.value)


def test_classifier_maps_rate_limit():
    payload = {"errors": [{"message": "Rate limit exceeded"}]}
    with pytest.raises(MonarchRateLimited):
        MonarchClient._raise_for_errors("GetAccounts", payload)


def test_classifier_maps_not_found():
    payload = {"errors": [{"message": "Account not found for id"}]}
    with pytest.raises(MonarchNotFound):
        MonarchClient._raise_for_errors("GetAccount", payload)


def test_classifier_maps_unauthorized():
    payload = {"errors": [{"message": "You do not have permission"}]}
    with pytest.raises(MonarchAuthError):
        MonarchClient._raise_for_errors("GetAccounts", payload)


# ---------------------------------------------------------------------------
# Decimal precision
# ---------------------------------------------------------------------------


def test_decimal_round_trip_preserves_cents():
    t = Transaction.model_validate(
        {"id": "T", "date": "2026-04-18", "amount": "-1234.56", "accountId": "A"}
    )
    dumped = t.model_dump()
    assert dumped["amount"] == Decimal("-1234.56")


def test_very_small_amounts_preserved():
    t = Transaction.model_validate(
        {"id": "T", "date": "2026-04-18", "amount": "-0.01", "accountId": "A"}
    )
    assert t.amount == Decimal("-0.01")


# ---------------------------------------------------------------------------
# Time-zone boundaries
# ---------------------------------------------------------------------------


def test_cashflow_bucket_uses_transaction_date_not_current_tz():
    # Two transactions on the boundary of March/April — they should land in the month
    # their ``date`` says, not whichever month the test host thinks it is.
    txs = [
        Transaction.model_validate(
            {"id": "T1", "date": "2026-03-31", "amount": 100, "accountId": "A", "tags": []}
        ),
        Transaction.model_validate(
            {"id": "T2", "date": "2026-04-01", "amount": 200, "accountId": "A", "tags": []}
        ),
    ]
    monthly = CashflowInsights.monthly(txs, months=12)
    march = next((m for m in monthly if m.month == "2026-03"), None)
    april = next((m for m in monthly if m.month == "2026-04"), None)
    assert march is not None and april is not None
    assert march.income == Decimal(100)
    assert april.income == Decimal(200)


# ---------------------------------------------------------------------------
# Large dataset sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [5000])
def test_top_categories_handles_thousands_of_transactions_fast(count):
    txs = []
    today = date.today()
    for i in range(count):
        txs.append(
            Transaction.model_validate(
                {
                    "id": f"T{i}",
                    "date": (today - timedelta(days=i % 365)).isoformat(),
                    "amount": -((i % 50) + 1),
                    "accountId": "A",
                    "categoryId": f"CAT_{i % 10}",
                    "categoryName": f"cat {i % 10}",
                    "tags": [],
                }
            )
        )
    start = time.perf_counter()
    cats = SpendingInsights.top_categories(txs, limit=5)
    elapsed = time.perf_counter() - start
    assert cats
    assert elapsed < 1.0  # should rip through 5k txns in < 1 second


# ---------------------------------------------------------------------------
# JSON payload resiliency
# ---------------------------------------------------------------------------


def test_account_payload_tolerates_extra_fields():
    payload = {
        "id": "A",
        "displayName": "X",
        "type": "depository",
        "currentBalance": 1,
        "futureField": {"monarch": "added"},  # should be ignored, not crash
    }
    a = Account.model_validate(payload)
    assert a.id == "A"


def test_holding_payload_tolerates_nested_account():
    payload = {
        "id": "H",
        "accountId": "A",
        "ticker": "vti",  # lower case, should still parse
        "quantity": "5",  # string, should coerce
        "value": 1200,
    }
    h = Holding.model_validate(payload)
    assert h.quantity == Decimal(5)
