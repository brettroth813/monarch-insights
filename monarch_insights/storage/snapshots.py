"""Local time-series snapshot store.

Even with Monarch's own snapshot endpoints, we keep our own daily roll-up so insights
can compare *our derived numbers* (e.g. after manually-entered cost basis) against
prior days. This is also where computed metrics live: net worth, allocation %s, FIRE
projections, drift scores.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path.home() / ".local" / "share" / "monarch-insights" / "snapshots.db"

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    on_date TEXT PRIMARY KEY,
    assets REAL NOT NULL,
    liabilities REAL NOT NULL,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS allocation_snapshots (
    on_date TEXT NOT NULL,
    bucket TEXT NOT NULL,
    value REAL NOT NULL,
    target_pct REAL,
    PRIMARY KEY (on_date, bucket)
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    on_date TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    detail_json TEXT,
    PRIMARY KEY (on_date, metric)
);

CREATE TABLE IF NOT EXISTS account_balance_snapshots (
    on_date TEXT NOT NULL,
    account_id TEXT NOT NULL,
    balance REAL NOT NULL,
    PRIMARY KEY (on_date, account_id)
);

CREATE TABLE IF NOT EXISTS holding_value_snapshots (
    on_date TEXT NOT NULL,
    account_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    market_value REAL,
    cost_basis REAL,
    PRIMARY KEY (on_date, account_id, ticker)
);
"""


class SnapshotStore:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ net worth

    def record_net_worth(
        self,
        on_date: date,
        assets: float,
        liabilities: float,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO net_worth_snapshots (on_date, assets, liabilities, detail_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(on_date) DO UPDATE SET
                    assets=excluded.assets,
                    liabilities=excluded.liabilities,
                    detail_json=excluded.detail_json
                """,
                (on_date.isoformat(), assets, liabilities, json.dumps(detail or {})),
            )

    def net_worth_history(self, since: date | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM net_worth_snapshots WHERE on_date >= ? ORDER BY on_date",
                    (since.isoformat(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM net_worth_snapshots ORDER BY on_date"
                ).fetchall()
        return [
            {
                "date": r["on_date"],
                "assets": r["assets"],
                "liabilities": r["liabilities"],
                "net_worth": r["assets"] - r["liabilities"],
                "detail": json.loads(r["detail_json"] or "{}"),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ generic metrics

    def record_metric(
        self,
        on_date: date,
        metric: str,
        value: float,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO metric_snapshots (on_date, metric, value, detail_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(on_date, metric) DO UPDATE SET
                    value=excluded.value,
                    detail_json=excluded.detail_json
                """,
                (on_date.isoformat(), metric, value, json.dumps(detail or {})),
            )

    def metric_history(self, metric: str, since: date | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM metric_snapshots WHERE metric=? AND on_date >= ? ORDER BY on_date",
                    (metric, since.isoformat()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM metric_snapshots WHERE metric=? ORDER BY on_date",
                    (metric,),
                ).fetchall()
        return [
            {"date": r["on_date"], "value": r["value"], "detail": json.loads(r["detail_json"] or "{}")}
            for r in rows
        ]

    # ------------------------------------------------------------------ allocation

    def record_allocation(
        self,
        on_date: date,
        buckets: dict[str, float],
        targets: dict[str, float] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO allocation_snapshots (on_date, bucket, value, target_pct)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(on_date, bucket) DO UPDATE SET
                    value=excluded.value,
                    target_pct=excluded.target_pct
                """,
                [
                    (on_date.isoformat(), bucket, value, (targets or {}).get(bucket))
                    for bucket, value in buckets.items()
                ],
            )

    # ------------------------------------------------------------------ holdings

    def record_holding_values(
        self,
        on_date: date,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            return
        params = [
            (
                on_date.isoformat(),
                r["account_id"],
                r["ticker"] or "UNKNOWN",
                float(r.get("quantity", 0)),
                float(r["market_value"]) if r.get("market_value") is not None else None,
                float(r["cost_basis"]) if r.get("cost_basis") is not None else None,
            )
            for r in rows
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO holding_value_snapshots (on_date, account_id, ticker, quantity, market_value, cost_basis)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(on_date, account_id, ticker) DO UPDATE SET
                    quantity=excluded.quantity,
                    market_value=excluded.market_value,
                    cost_basis=excluded.cost_basis
                """,
                params,
            )
