"""On-disk cache for Monarch GraphQL responses.

Why cache:
* Insight modules want to run hourly without re-paginating 18 months of transactions.
* HA sensors poll fast — we don't want to stress the upstream.
* When Monarch is down (it happens), we still want to render dashboards.

Schema is intentionally simple: one ``payloads`` table keyed by
``(operation, variables_hash)``, plus an ``entities`` table of typed records that the
insight layer can query directly via SQL when raw payloads aren't enough.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

DEFAULT_DB = Path.home() / ".local" / "share" / "monarch-insights" / "cache.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    variables_hash TEXT NOT NULL,
    variables_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    UNIQUE(operation, variables_hash) ON CONFLICT REPLACE
);
CREATE INDEX IF NOT EXISTS idx_payloads_op ON payloads(operation);
CREATE INDEX IF NOT EXISTS idx_payloads_fetched ON payloads(fetched_at);

CREATE TABLE IF NOT EXISTS entities (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    last_seen_at INTEGER NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS account_balances (
    account_id TEXT NOT NULL,
    on_date TEXT NOT NULL,
    balance REAL NOT NULL,
    PRIMARY KEY (account_id, on_date)
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    on_date TEXT NOT NULL,
    amount REAL NOT NULL,
    account_id TEXT,
    category_id TEXT,
    merchant_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(on_date);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_merchant ON transactions(merchant_id);

CREATE TABLE IF NOT EXISTS holdings (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    ticker TEXT,
    quantity REAL NOT NULL,
    cost_basis REAL,
    market_value REAL,
    payload_json TEXT NOT NULL,
    last_seen_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holdings_acct ON holdings(account_id);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings(ticker);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    detail_json TEXT
);
"""


@dataclass
class CachedPayload:
    operation: str
    variables: dict[str, Any]
    response: dict[str, Any]
    fetched_at: datetime


def _hash_vars(variables: dict[str, Any] | None) -> str:
    norm = json.dumps(variables or {}, sort_keys=True, default=str)
    return hashlib.sha256(norm.encode()).hexdigest()


class MonarchCache:
    """Thin SQLite wrapper. Sync (not async) — SQLite ops are fast and called sparingly."""

    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
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

    # ------------------------------------------------------------------ payloads

    def store_payload(
        self,
        operation: str,
        variables: dict[str, Any] | None,
        response: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO payloads (operation, variables_hash, variables_json, response_json, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    operation,
                    _hash_vars(variables),
                    json.dumps(variables or {}, sort_keys=True, default=str),
                    json.dumps(response, default=str),
                    int(time.time()),
                ),
            )

    def get_payload(
        self, operation: str, variables: dict[str, Any] | None = None
    ) -> CachedPayload | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payloads WHERE operation=? AND variables_hash=?",
                (operation, _hash_vars(variables)),
            ).fetchone()
        if not row:
            return None
        return CachedPayload(
            operation=row["operation"],
            variables=json.loads(row["variables_json"]),
            response=json.loads(row["response_json"]),
            fetched_at=datetime.fromtimestamp(row["fetched_at"], tz=timezone.utc),
        )

    def latest_payload(self, operation: str) -> CachedPayload | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payloads WHERE operation=? ORDER BY fetched_at DESC LIMIT 1",
                (operation,),
            ).fetchone()
        if not row:
            return None
        return CachedPayload(
            operation=row["operation"],
            variables=json.loads(row["variables_json"]),
            response=json.loads(row["response_json"]),
            fetched_at=datetime.fromtimestamp(row["fetched_at"], tz=timezone.utc),
        )

    # ------------------------------------------------------------------ entities

    def upsert_entity(self, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO entities (entity_type, entity_id, payload_json, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    last_seen_at=excluded.last_seen_at
                """,
                (entity_type, entity_id, json.dumps(payload, default=str), int(time.time())),
            )

    def upsert_many(self, entity_type: str, items: Iterable[tuple[str, dict[str, Any]]]) -> None:
        items = list(items)
        if not items:
            return
        now = int(time.time())
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO entities (entity_type, entity_id, payload_json, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    last_seen_at=excluded.last_seen_at
                """,
                [
                    (entity_type, eid, json.dumps(payload, default=str), now)
                    for eid, payload in items
                ],
            )

    def list_entities(self, entity_type: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM entities WHERE entity_type=?",
                (entity_type,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    # ------------------------------------------------------------------ transactions table (denormalised)

    def upsert_transactions(self, txs: Iterable[dict[str, Any]]) -> None:
        rows = []
        for t in txs:
            rows.append(
                (
                    t["id"],
                    t.get("date") or t.get("on_date"),
                    float(t.get("amount", 0)),
                    t.get("accountId") or t.get("account_id"),
                    t.get("categoryId") or t.get("category_id"),
                    t.get("merchantId") or t.get("merchant_id"),
                    json.dumps(t, default=str),
                )
            )
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO transactions (id, on_date, amount, account_id, category_id, merchant_id, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    on_date=excluded.on_date,
                    amount=excluded.amount,
                    account_id=excluded.account_id,
                    category_id=excluded.category_id,
                    merchant_id=excluded.merchant_id,
                    payload_json=excluded.payload_json
                """,
                rows,
            )

    # ------------------------------------------------------------------ holdings

    def upsert_holdings(self, holdings: Iterable[dict[str, Any]]) -> None:
        now = int(time.time())
        rows = []
        for h in holdings:
            rows.append(
                (
                    h["id"],
                    h.get("accountId") or h.get("account_id"),
                    h.get("ticker"),
                    float(h.get("quantity", 0)),
                    float(h["cost_basis"]) if h.get("cost_basis") is not None else None,
                    float(h["market_value"]) if h.get("market_value") is not None else None,
                    json.dumps(h, default=str),
                    now,
                )
            )
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO holdings (id, account_id, ticker, quantity, cost_basis, market_value, payload_json, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    account_id=excluded.account_id,
                    ticker=excluded.ticker,
                    quantity=excluded.quantity,
                    cost_basis=excluded.cost_basis,
                    market_value=excluded.market_value,
                    payload_json=excluded.payload_json,
                    last_seen_at=excluded.last_seen_at
                """,
                rows,
            )

    # ------------------------------------------------------------------ sync runs

    def record_sync_start(self, operation: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO sync_runs (operation, started_at, status) VALUES (?, ?, 'running')",
                (operation, int(time.time())),
            )
            return cur.lastrowid

    def record_sync_finish(
        self, run_id: int, status: str = "ok", error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sync_runs SET finished_at=?, status=?, error=?, detail_json=? WHERE id=?",
                (
                    int(time.time()),
                    status,
                    error,
                    json.dumps(detail or {}, default=str),
                    run_id,
                ),
            )
