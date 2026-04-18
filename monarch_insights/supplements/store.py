"""SQLite-backed store for user-supplied financial supplements.

Schema is one table per concept rather than a generic key-value, so it stays inspectable
from `sqlite3` and `dbeaver` and so the gap detector can write SQL directly.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path.home() / ".local" / "share" / "monarch-insights" / "supplements.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cost_basis_lots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    acquired_on TEXT NOT NULL,
    cost_per_share REAL NOT NULL,
    fees REAL DEFAULT 0,
    source TEXT,
    notes TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lots_acct_ticker ON cost_basis_lots(account_id, ticker);

CREATE TABLE IF NOT EXISTS lot_disposals (
    id TEXT PRIMARY KEY,
    lot_id TEXT NOT NULL REFERENCES cost_basis_lots(id) ON DELETE CASCADE,
    quantity REAL NOT NULL,
    disposed_on TEXT NOT NULL,
    proceeds REAL NOT NULL,
    fees REAL DEFAULT 0,
    transaction_id TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_disposals_lot ON lot_disposals(lot_id);

CREATE TABLE IF NOT EXISTS paystubs (
    id TEXT PRIMARY KEY,
    employer TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    paid_on TEXT NOT NULL,
    gross_pay REAL NOT NULL,
    net_pay REAL NOT NULL,
    detail_json TEXT,
    document_id TEXT,
    transaction_id TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paystubs_paid_on ON paystubs(paid_on);

CREATE TABLE IF NOT EXISTS paystub_line_items (
    id TEXT PRIMARY KEY,
    paystub_id TEXT NOT NULL REFERENCES paystubs(id) ON DELETE CASCADE,
    category TEXT NOT NULL,  -- earnings|tax|deduction|benefit|employer
    label TEXT NOT NULL,
    amount REAL NOT NULL,
    ytd_amount REAL,
    pretax INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_paystub_items_pid ON paystub_line_items(paystub_id);

CREATE TABLE IF NOT EXISTS income_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- w2|1099|k1|rsu|interest|dividend|rental|other
    employer_or_payer TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS income_events (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES income_sources(id) ON DELETE CASCADE,
    on_date TEXT NOT NULL,
    gross_amount REAL NOT NULL,
    taxable_amount REAL,
    withholding_amount REAL DEFAULT 0,
    detail_json TEXT,
    transaction_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_income_events_src ON income_events(source_id, on_date);

CREATE TABLE IF NOT EXISTS rsu_grants (
    id TEXT PRIMARY KEY,
    employer TEXT NOT NULL,
    grant_date TEXT NOT NULL,
    shares INTEGER NOT NULL,
    vest_schedule_json TEXT NOT NULL,  -- list of {date, shares}
    fmv_at_grant REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS allocation_targets (
    id TEXT PRIMARY KEY,
    bucket TEXT NOT NULL,
    target_pct REAL NOT NULL,
    drift_threshold_pct REAL DEFAULT 5.0,
    notes TEXT,
    UNIQUE(bucket)
);

CREATE TABLE IF NOT EXISTS financial_plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    detail_json TEXT NOT NULL,  -- retirement, FIRE, home purchase, college, etc
    is_active INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,  -- 1099-DIV|1099-INT|1099-B|W-2|K-1|brokerage_statement|paystub|receipt|other
    tax_year INTEGER,
    institution TEXT,
    storage_kind TEXT NOT NULL,  -- local|drive|gmail
    storage_ref TEXT NOT NULL,
    sha256 TEXT,
    notes TEXT,
    metadata_json TEXT,
    added_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_year ON documents(tax_year);

CREATE TABLE IF NOT EXISTS info_requests (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,         -- cost_basis|paystub|rsu_grant|account_history|tax_doc|target|other
    summary TEXT NOT NULL,
    detail_json TEXT,
    status TEXT NOT NULL,       -- open|in_progress|resolved|dismissed
    severity TEXT NOT NULL,     -- info|warn|critical
    suggested_action TEXT,
    related_account_id TEXT,
    related_ticker TEXT,
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_info_requests_status ON info_requests(status);
CREATE INDEX IF NOT EXISTS idx_info_requests_kind ON info_requests(kind);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    related_id TEXT,
    related_kind TEXT,
    created_at INTEGER NOT NULL
);
"""


class SupplementStore:
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

    # ---------------------------------------------- generic helpers

    @staticmethod
    def _now() -> int:
        return int(time.time())

    def upsert(self, table: str, row: dict[str, Any], key: str = "id") -> None:
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT({key}) DO UPDATE SET {updates}"
        )
        with self.connect() as conn:
            conn.execute(sql, [row[c] for c in cols])

    # ---------------------------------------------- cost basis

    def add_lot(self, lot: dict[str, Any]) -> None:
        now = self._now()
        row = {
            "id": lot["id"],
            "account_id": lot["account_id"],
            "ticker": lot["ticker"],
            "quantity": float(lot["quantity"]),
            "acquired_on": lot["acquired_on"],
            "cost_per_share": float(lot["cost_per_share"]),
            "fees": float(lot.get("fees", 0)),
            "source": lot.get("source", "manual"),
            "notes": lot.get("notes"),
            "created_at": lot.get("created_at", now),
            "updated_at": now,
        }
        self.upsert("cost_basis_lots", row)

    def lots_for(self, account_id: str, ticker: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cost_basis_lots WHERE account_id=? AND ticker=? ORDER BY acquired_on",
                (account_id, ticker),
            ).fetchall()
        return [dict(r) for r in rows]

    def all_lots(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM cost_basis_lots ORDER BY acquired_on").fetchall()
        return [dict(r) for r in rows]

    def add_disposal(self, disposal: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO lot_disposals (id, lot_id, quantity, disposed_on, proceeds, fees, transaction_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    disposal["id"],
                    disposal["lot_id"],
                    float(disposal["quantity"]),
                    disposal["disposed_on"],
                    float(disposal["proceeds"]),
                    float(disposal.get("fees", 0)),
                    disposal.get("transaction_id"),
                    disposal.get("notes"),
                ),
            )

    # ---------------------------------------------- paystubs

    def add_paystub(self, paystub: dict[str, Any]) -> None:
        row = {
            "id": paystub["id"],
            "employer": paystub["employer"],
            "period_start": paystub["period_start"],
            "period_end": paystub["period_end"],
            "paid_on": paystub["paid_on"],
            "gross_pay": float(paystub["gross_pay"]),
            "net_pay": float(paystub["net_pay"]),
            "detail_json": json.dumps(paystub.get("detail", {})),
            "document_id": paystub.get("document_id"),
            "transaction_id": paystub.get("transaction_id"),
            "created_at": paystub.get("created_at", self._now()),
        }
        self.upsert("paystubs", row)
        for li in paystub.get("line_items") or []:
            self.upsert(
                "paystub_line_items",
                {
                    "id": li["id"],
                    "paystub_id": paystub["id"],
                    "category": li["category"],
                    "label": li["label"],
                    "amount": float(li["amount"]),
                    "ytd_amount": float(li["ytd_amount"]) if li.get("ytd_amount") is not None else None,
                    "pretax": int(bool(li.get("pretax"))),
                },
            )

    def list_paystubs(self, year: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if year:
                rows = conn.execute(
                    "SELECT * FROM paystubs WHERE paid_on LIKE ? ORDER BY paid_on DESC",
                    (f"{year}-%",),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM paystubs ORDER BY paid_on DESC").fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------- info requests (gap detector output)

    def add_info_request(self, req: dict[str, Any]) -> None:
        row = {
            "id": req["id"],
            "kind": req["kind"],
            "summary": req["summary"],
            "detail_json": json.dumps(req.get("detail", {})),
            "status": req.get("status", "open"),
            "severity": req.get("severity", "info"),
            "suggested_action": req.get("suggested_action"),
            "related_account_id": req.get("related_account_id"),
            "related_ticker": req.get("related_ticker"),
            "created_at": req.get("created_at", self._now()),
            "resolved_at": req.get("resolved_at"),
        }
        self.upsert("info_requests", row)

    def open_info_requests(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM info_requests WHERE status IN ('open','in_progress') "
                "ORDER BY severity DESC, created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve_info_request(self, req_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE info_requests SET status='resolved', resolved_at=? WHERE id=?",
                (self._now(), req_id),
            )

    # ---------------------------------------------- documents

    def add_document(self, doc: dict[str, Any]) -> None:
        row = {
            "id": doc["id"],
            "title": doc["title"],
            "doc_type": doc["doc_type"],
            "tax_year": doc.get("tax_year"),
            "institution": doc.get("institution"),
            "storage_kind": doc["storage_kind"],
            "storage_ref": doc["storage_ref"],
            "sha256": doc.get("sha256"),
            "notes": doc.get("notes"),
            "metadata_json": json.dumps(doc.get("metadata", {})),
            "added_at": doc.get("added_at", self._now()),
        }
        self.upsert("documents", row)

    def list_documents(self, tax_year: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if tax_year:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE tax_year=? ORDER BY added_at DESC", (tax_year,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM documents ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------- targets & plans

    def set_allocation_target(self, bucket: str, target_pct: float, drift_threshold: float = 5.0) -> None:
        self.upsert(
            "allocation_targets",
            {
                "id": bucket,
                "bucket": bucket,
                "target_pct": target_pct,
                "drift_threshold_pct": drift_threshold,
                "notes": None,
            },
            key="bucket",
        )

    def get_allocation_targets(self) -> dict[str, dict[str, float]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM allocation_targets").fetchall()
        return {r["bucket"]: {"target_pct": r["target_pct"], "drift_threshold_pct": r["drift_threshold_pct"]} for r in rows}

    def set_plan(self, plan: dict[str, Any]) -> None:
        row = {
            "id": plan["id"],
            "name": plan["name"],
            "detail_json": json.dumps(plan.get("detail", {})),
            "is_active": int(plan.get("is_active", 1)),
            "created_at": plan.get("created_at", self._now()),
        }
        self.upsert("financial_plans", row)

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM financial_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["detail"] = json.loads(out.pop("detail_json") or "{}")
        return out

    # ---------------------------------------------- RSU grants

    def add_rsu_grant(self, grant: dict[str, Any]) -> None:
        row = {
            "id": grant["id"],
            "employer": grant["employer"],
            "grant_date": grant["grant_date"],
            "shares": int(grant["shares"]),
            "vest_schedule_json": json.dumps(grant["vest_schedule"]),
            "fmv_at_grant": float(grant["fmv_at_grant"]) if grant.get("fmv_at_grant") is not None else None,
            "notes": grant.get("notes"),
        }
        self.upsert("rsu_grants", row)

    def list_rsu_grants(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM rsu_grants ORDER BY grant_date").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["vest_schedule"] = json.loads(d.pop("vest_schedule_json"))
            out.append(d)
        return out

    # ---------------------------------------------- income sources/events

    def add_income_source(self, src: dict[str, Any]) -> None:
        self.upsert(
            "income_sources",
            {
                "id": src["id"],
                "name": src["name"],
                "source_type": src["source_type"],
                "employer_or_payer": src.get("employer_or_payer"),
                "notes": src.get("notes"),
                "is_active": int(src.get("is_active", 1)),
            },
        )

    def add_income_event(self, event: dict[str, Any]) -> None:
        self.upsert(
            "income_events",
            {
                "id": event["id"],
                "source_id": event["source_id"],
                "on_date": event["on_date"],
                "gross_amount": float(event["gross_amount"]),
                "taxable_amount": float(event["taxable_amount"]) if event.get("taxable_amount") is not None else None,
                "withholding_amount": float(event.get("withholding_amount", 0)),
                "detail_json": json.dumps(event.get("detail", {})),
                "transaction_id": event.get("transaction_id"),
            },
        )

    def list_income_events(self, year: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if year:
                rows = conn.execute(
                    "SELECT * FROM income_events WHERE on_date LIKE ? ORDER BY on_date",
                    (f"{year}-%",),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM income_events ORDER BY on_date").fetchall()
        return [dict(r) for r in rows]
