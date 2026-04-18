"""Guards the SupplementStore.upsert allowlist — disallowed table or column should raise."""

from __future__ import annotations

import pytest

from monarch_insights.supplements.store import SupplementStore


@pytest.fixture
def store(tmp_path):
    return SupplementStore(path=tmp_path / "supp.db")


def test_upsert_rejects_unknown_table(store):
    with pytest.raises(ValueError, match="upsert not allowed for table"):
        store.upsert("evil_table", {"id": "1", "bucket": "x", "target_pct": 50, "drift_threshold_pct": 5, "notes": None})


def test_upsert_rejects_unknown_column(store):
    with pytest.raises(ValueError, match="disallowed columns"):
        store.upsert(
            "allocation_targets",
            {"id": "us_stock", "bucket": "us_stock", "target_pct": 60, "drift_threshold_pct": 5, "notes": None, "evil": "'; DROP TABLE x; --"},
            key="bucket",
        )


def test_upsert_rejects_unknown_conflict_key(store):
    with pytest.raises(ValueError, match="conflict key"):
        store.upsert(
            "allocation_targets",
            {"id": "us_stock", "bucket": "us_stock", "target_pct": 60, "drift_threshold_pct": 5, "notes": None},
            key="evil_key",
        )


def test_upsert_allowed_path_still_works(store):
    # Sanity — the legitimate caller path is unaffected.
    store.set_allocation_target("us_stock", 60.0, 5.0)
    targets = store.get_allocation_targets()
    assert "us_stock" in targets
    assert targets["us_stock"]["target_pct"] == 60.0
