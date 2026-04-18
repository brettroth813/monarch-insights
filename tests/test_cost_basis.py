"""Cost-basis ledger logic — FIFO/LIFO/HIFO."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from monarch_insights.supplements.cost_basis import (
    CostBasisLedger,
    CostBasisLot,
    DisposalMethod,
)
from monarch_insights.supplements.store import SupplementStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield SupplementStore(path=Path(tmp) / "supp.db")


def _seed_lots(store: SupplementStore):
    base = date.today() - timedelta(days=400)
    for i, (qty, price) in enumerate([(10, 100), (10, 150), (10, 200)]):
        store.add_lot(
            {
                "id": f"lot{i}",
                "account_id": "B1",
                "ticker": "AAPL",
                "quantity": qty,
                "acquired_on": (base + timedelta(days=i * 100)).isoformat(),
                "cost_per_share": price,
                "fees": 0,
            }
        )


def test_fifo_realizes_oldest_first(store):
    _seed_lots(store)
    ledger = CostBasisLedger.from_store(store, "B1", "AAPL")
    results = ledger.simulate_disposal(
        Decimal(15), Decimal(250), method=DisposalMethod.FIFO
    )
    assert results[0].cost_basis == Decimal(1000)  # 10 @ 100
    assert results[1].cost_basis == Decimal(750)   # 5 @ 150


def test_hifo_picks_highest_cost(store):
    _seed_lots(store)
    ledger = CostBasisLedger.from_store(store, "B1", "AAPL")
    results = ledger.simulate_disposal(
        Decimal(5), Decimal(250), method=DisposalMethod.HIFO
    )
    assert results[0].cost_basis == Decimal(1000)  # 5 @ 200


def test_disposal_too_large_raises(store):
    _seed_lots(store)
    ledger = CostBasisLedger.from_store(store, "B1", "AAPL")
    with pytest.raises(ValueError):
        ledger.simulate_disposal(Decimal(100), Decimal(250))
