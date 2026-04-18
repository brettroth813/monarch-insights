"""Observability primitives: structured logging + persistent event log.

Two things live here:

* :class:`JsonFormatter` and :func:`configure_logging` — wires Python's stdlib ``logging``
  to emit machine-readable JSON to stdout *and* a rotating file under
  ``~/.local/share/monarch-insights/logs/``. Brett is a data hoarder and wants to be
  able to mine these later, so the default retention is intentionally generous.

* :class:`EventLog` — a SQLite-backed audit log keyed by ``(source, kind, ts)`` so any
  module can record "this happened" with arbitrary structured detail. The CLI reads from
  here when you ask "what's been going on?", and HA can render it as a sensor history.

Use these from any module instead of ``print``:

    from monarch_insights.observability import get_logger, EventLog

    log = get_logger(__name__)
    log.info("synced.accounts", extra={"count": len(accounts), "took_ms": elapsed})

    events = EventLog()
    events.record("monarch.sync", "completed", {"accounts": len(accounts)})

The :class:`JsonFormatter` flattens ``logging.Record`` plus any ``extra`` dict into a
single JSON object per line, so downstream tools (jq, Grafana Loki, log-collection
add-ons in HA) can parse each line independently.
"""

from monarch_insights.observability.event_log import EventLog, EventRecord
from monarch_insights.observability.logging import (
    DEFAULT_LOG_DIR,
    JsonFormatter,
    configure_logging,
    get_logger,
)

__all__ = [
    "DEFAULT_LOG_DIR",
    "EventLog",
    "EventRecord",
    "JsonFormatter",
    "configure_logging",
    "get_logger",
]
