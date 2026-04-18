"""Persistent event log — every meaningful "thing happened" gets a row.

Why a separate log alongside the rotating file logger?

* The file logger is good for free-text streaming and grepping; queries like "what
  Monarch syncs ran in March" are awkward.
* The event log is structured (source, kind, ref, detail JSON) and lives in SQLite, so
  the CLI / HA / a future dashboard can query by time + source + kind cheaply.
* It also doubles as an audit trail for things we don't want to silently lose: alerts
  fired, signals acted on, gaps resolved, manual lots entered, OAuth tokens rotated.

Schema is intentionally lean: ``id`` (autoinc), ``ts`` (unix int), ``source``,
``kind``, ``ref`` (free-form id), ``severity``, ``detail_json``. Indexes on time +
source so queries stay fast even after years of accumulation.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path.home() / ".local" / "share" / "monarch-insights" / "events.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT,
    severity TEXT DEFAULT 'info',
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_ref ON events(ref);
"""


@dataclass(frozen=True)
class EventRecord:
    """A single row read back from the event log."""

    id: int
    ts: datetime
    source: str
    kind: str
    ref: str | None
    severity: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "source": self.source,
            "kind": self.kind,
            "ref": self.ref,
            "severity": self.severity,
            "detail": self.detail,
        }


class EventLog:
    """Append-only structured event log backed by SQLite.

    ``record`` is the only meaningful write API. Reads are typed query helpers that
    return :class:`EventRecord` instances rather than raw rows, so callers don't depend
    on the underlying schema.
    """

    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived sqlite connection. Autocommit so callers don't have to."""
        conn = sqlite3.connect(str(self.path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # -------------------------------------------------------------- writes

    def record(
        self,
        source: str,
        kind: str,
        detail: dict[str, Any] | None = None,
        *,
        ref: str | None = None,
        severity: str = "info",
        ts: datetime | None = None,
    ) -> int:
        """Append one event.

        Args:
            source: Subsystem identifier (``"monarch.sync"``, ``"alerts.engine"``,
                ``"providers.market_data.yfinance"``). Use dotted lower-case so
                filtering with ``source LIKE 'monarch.%'`` works.
            kind: Verb-like noun describing the event (``"started"``, ``"completed"``,
                ``"alert.fired"``, ``"signal.scored"``).
            detail: Arbitrary serialisable dict. Decimal/datetime/Pydantic models are
                coerced via ``str(value)`` if json fails.
            ref: Free-form correlation id (transaction id, alert id, sync run id).
            severity: ``"debug" | "info" | "warn" | "critical"``.
            ts: Override timestamp (used by tests and backfills); defaults to ``now``.

        Returns:
            The autoincrement ``id`` of the inserted row.
        """
        ts_value = int((ts or datetime.now(timezone.utc)).timestamp())
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO events (ts, source, kind, ref, severity, detail_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ts_value,
                    source,
                    kind,
                    ref,
                    severity,
                    json.dumps(detail or {}, default=str),
                ),
            )
            return cursor.lastrowid

    # -------------------------------------------------------------- reads

    def recent(
        self,
        *,
        limit: int = 100,
        source: str | None = None,
        kind: str | None = None,
        severity: str | None = None,
    ) -> list[EventRecord]:
        """Return the most recent events matching the filters.

        Args:
            limit: Maximum number of rows.
            source: Exact match or SQL ``LIKE`` pattern (callers may include ``%``).
            kind: Exact match.
            severity: Exact match (``"info"`` etc.).

        Returns:
            Newest-first list of :class:`EventRecord`.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if source is not None:
            clauses.append("source LIKE ?" if "%" in source else "source = ?")
            params.append(source)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events {where} ORDER BY ts DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count(self, *, source: str | None = None, kind: str | None = None) -> int:
        """Return how many events match the filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM events {where}", params).fetchone()
        return int(row["n"])

    def purge_older_than(self, days: int) -> int:
        """Delete events older than ``days`` and return how many were removed.

        We default to no purging (long retention is desired); call this only when
        explicitly trying to manage disk usage.
        """
        cutoff = int(time.time()) - days * 86400
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            return cursor.rowcount

    # -------------------------------------------------------------- internal

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=int(row["id"]),
            ts=datetime.fromtimestamp(int(row["ts"]), tz=timezone.utc),
            source=row["source"],
            kind=row["kind"],
            ref=row["ref"],
            severity=row["severity"] or "info",
            detail=json.loads(row["detail_json"] or "{}"),
        )
