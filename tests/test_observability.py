"""Logging + event log tests.

Covers:

* JSON formatter shape, including ``extra`` flattening and reserved-field protection.
* ``configure_logging`` idempotency — multiple calls don't stack handlers.
* EventLog round-trip: record → recent, with filtering by source/kind/severity.
* EventLog purge by retention.
* Decimal / datetime / Pydantic coercion through both layers.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest

from monarch_insights.observability import EventLog, JsonFormatter, configure_logging, get_logger
from monarch_insights.observability.event_log import EventRecord


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


def _record(level: int, msg: str, extra: dict | None = None) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=42,
        msg=msg,
        args=None,
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def test_json_formatter_basic_shape():
    line = JsonFormatter().format(_record(logging.INFO, "hello"))
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["app"] == "monarch-insights"
    assert payload["line"] == 42
    assert "ts" in payload


def test_json_formatter_passes_extra_through():
    line = JsonFormatter().format(
        _record(logging.INFO, "synced", extra={"accounts": 12, "took_ms": 854})
    )
    payload = json.loads(line)
    assert payload["accounts"] == 12
    assert payload["took_ms"] == 854


def test_json_formatter_protects_reserved_fields():
    # ``message`` is reserved; the caller's extra should be ignored, not crash.
    line = JsonFormatter().format(
        _record(logging.INFO, "real", extra={"message": "spoofed"})
    )
    payload = json.loads(line)
    assert payload["message"] == "real"


def test_json_formatter_coerces_decimals_and_models():
    class _Fake:
        def model_dump(self):
            return {"x": 1}

    line = JsonFormatter().format(
        _record(
            logging.INFO,
            "weird",
            extra={"price": Decimal("123.45"), "model": _Fake(), "set": {"b", "a"}},
        )
    )
    payload = json.loads(line)
    assert payload["price"] == 123.45
    assert payload["model"] == {"x": 1}
    assert payload["set"] == ["a", "b"]


def test_configure_logging_is_idempotent(tmp_path):
    configure_logging(level=logging.DEBUG, log_dir=tmp_path, json_to_stdout=True)
    handlers_first = list(logging.getLogger().handlers)
    configure_logging(level=logging.INFO, log_dir=tmp_path, json_to_stdout=True)
    handlers_second = list(logging.getLogger().handlers)
    # Same number of monarch-insights handlers — older ones replaced, not stacked.
    monarch_first = [h for h in handlers_first if getattr(h, "_monarch_insights", False)]
    monarch_second = [h for h in handlers_second if getattr(h, "_monarch_insights", False)]
    assert len(monarch_first) == len(monarch_second)


# ---------------------------------------------------------------------------
# EventLog
# ---------------------------------------------------------------------------


@pytest.fixture
def event_log(tmp_path):
    return EventLog(path=tmp_path / "events.db")


def test_event_log_record_and_read_back(event_log):
    rid = event_log.record(
        "monarch.sync", "completed", {"accounts": 7, "took_ms": 1200}, ref="run-42"
    )
    assert rid > 0
    rows = event_log.recent(source="monarch.sync")
    assert rows
    record = rows[0]
    assert isinstance(record, EventRecord)
    assert record.kind == "completed"
    assert record.detail["accounts"] == 7
    assert record.ref == "run-42"


def test_event_log_filter_by_kind_and_severity(event_log):
    event_log.record("alerts.engine", "alert.fired", {"id": "1"}, severity="warn")
    event_log.record("alerts.engine", "alert.fired", {"id": "2"}, severity="info")
    event_log.record("alerts.engine", "rule.skipped", {"id": "3"}, severity="info")
    warns = event_log.recent(source="alerts.engine", severity="warn")
    assert len(warns) == 1
    fires = event_log.recent(source="alerts.engine", kind="alert.fired")
    assert len(fires) == 2


def test_event_log_count(event_log):
    for _ in range(5):
        event_log.record("market.fetch", "quote", {"symbol": "VTI"})
    assert event_log.count(source="market.fetch") == 5
    assert event_log.count(source="market.fetch", kind="quote") == 5


def test_event_log_purge(event_log):
    old_ts = datetime.now(timezone.utc) - timedelta(days=400)
    event_log.record("test", "old", {"k": 1}, ts=old_ts)
    event_log.record("test", "new", {"k": 2})
    deleted = event_log.purge_older_than(365)
    assert deleted == 1
    assert event_log.count(source="test") == 1


def test_event_log_handles_decimal_in_detail(event_log):
    event_log.record(
        "tax.estimate", "computed", {"federal": Decimal("4321.50"), "rate": Decimal("0.22")}
    )
    rows = event_log.recent(source="tax.estimate")
    assert rows[0].detail["federal"] == "4321.50"  # serialised via default=str
