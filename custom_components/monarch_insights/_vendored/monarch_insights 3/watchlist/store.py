"""SQLite-backed watchlist."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterator

DEFAULT_DB = Path.home() / ".local" / "share" / "monarch-insights" / "watchlist.db"

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    added_at INTEGER NOT NULL,
    target_price REAL,
    target_kind TEXT,            -- buy_below | sell_above | alert_move
    move_threshold_pct REAL,
    notes TEXT,
    tags_json TEXT
);

CREATE TABLE IF NOT EXISTS watchlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    on_date TEXT NOT NULL,
    price REAL NOT NULL,
    score INTEGER,
    action TEXT,
    rationale_json TEXT,
    UNIQUE(symbol, on_date)
);
CREATE INDEX IF NOT EXISTS idx_wl_hist_symbol ON watchlist_history(symbol);
"""


@dataclass
class WatchlistEntry:
    """One watched symbol + the user's intent."""

    symbol: str
    added_at: int = field(default_factory=lambda: int(time.time()))
    target_price: Decimal | None = None
    target_kind: str | None = None  # buy_below | sell_above | alert_move
    move_threshold_pct: Decimal | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)


class WatchlistStore:
    """CRUD + history persistence for the watchlist."""

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

    def add(self, entry: WatchlistEntry) -> None:
        """Upsert a watchlist entry by symbol."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO watchlist (symbol, added_at, target_price, target_kind, move_threshold_pct, notes, tags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    target_price = excluded.target_price,
                    target_kind = excluded.target_kind,
                    move_threshold_pct = excluded.move_threshold_pct,
                    notes = excluded.notes,
                    tags_json = excluded.tags_json
                """,
                (
                    entry.symbol.upper(),
                    entry.added_at,
                    float(entry.target_price) if entry.target_price is not None else None,
                    entry.target_kind,
                    float(entry.move_threshold_pct) if entry.move_threshold_pct is not None else None,
                    entry.notes,
                    json.dumps(entry.tags or []),
                ),
            )

    def remove(self, symbol: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))

    def list(self) -> list[WatchlistEntry]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY symbol").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def record_evaluation(
        self,
        symbol: str,
        on_date: str,
        price: float,
        score: int | None = None,
        action: str | None = None,
        rationale: list[str] | None = None,
    ) -> None:
        """Persist today's signal output for a watched symbol so we can chart it later."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO watchlist_history (symbol, on_date, price, score, action, rationale_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, on_date) DO UPDATE SET
                    price = excluded.price,
                    score = excluded.score,
                    action = excluded.action,
                    rationale_json = excluded.rationale_json
                """,
                (
                    symbol.upper(),
                    on_date,
                    price,
                    score,
                    action,
                    json.dumps(rationale or []),
                ),
            )

    def history(self, symbol: str, *, limit: int = 90) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist_history WHERE symbol=? ORDER BY on_date DESC LIMIT ?",
                (symbol.upper(), limit),
            ).fetchall()
        return [
            {
                "symbol": r["symbol"],
                "date": r["on_date"],
                "price": r["price"],
                "score": r["score"],
                "action": r["action"],
                "rationale": json.loads(r["rationale_json"] or "[]"),
            }
            for r in rows
        ]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> WatchlistEntry:
        return WatchlistEntry(
            symbol=row["symbol"],
            added_at=int(row["added_at"]),
            target_price=Decimal(str(row["target_price"])) if row["target_price"] is not None else None,
            target_kind=row["target_kind"],
            move_threshold_pct=Decimal(str(row["move_threshold_pct"])) if row["move_threshold_pct"] is not None else None,
            notes=row["notes"],
            tags=json.loads(row["tags_json"] or "[]"),
        )
