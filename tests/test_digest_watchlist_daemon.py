"""Coverage for the digest builder, watchlist store, and daemon scheduler."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from monarch_insights.alerts.engine import Alert, Severity
from monarch_insights.daemon.scheduler import DaemonConfig, MonarchDaemon
from monarch_insights.digest.builder import DailyDigest
from monarch_insights.insights.networth import NetWorthBreakdown
from monarch_insights.observability import EventLog
from monarch_insights.watchlist.store import WatchlistEntry, WatchlistStore


# ---------------------------------------------------------------------------
# DailyDigest
# ---------------------------------------------------------------------------


def _alert(kind: str, sev: Severity) -> Alert:
    return Alert.new(kind=kind, title=kind, message="msg", severity=sev)


def test_digest_summary_with_alerts():
    nw = NetWorthBreakdown(on_date=date(2026, 4, 18))
    nw.assets = Decimal(100000)
    nw.liabilities = Decimal(20000)
    digest = DailyDigest.build(
        on_date=date(2026, 4, 18),
        net_worth=nw,
        alerts=[_alert("k1", Severity.WARN), _alert("k2", Severity.INFO)],
        cashflow_runway_months=6.5,
        fire_age_estimate=58,
    )
    md = digest.markdown
    assert "Daily digest" in md
    assert "Net worth: **$80,000**" in md
    assert "FIRE age estimate: 58" in md
    assert digest.warn_count == 1
    assert digest.info_count == 1
    assert "Net worth $80,000" in digest.summary_line


def test_digest_to_alert_severity_escalates():
    crit = DailyDigest.build(on_date=date(2026, 4, 18), alerts=[_alert("k", Severity.CRITICAL)])
    warn = DailyDigest.build(on_date=date(2026, 4, 18), alerts=[_alert("k", Severity.WARN)])
    info = DailyDigest.build(on_date=date(2026, 4, 18))
    assert crit.to_alert().severity == Severity.CRITICAL
    assert warn.to_alert().severity == Severity.WARN
    assert info.to_alert().severity == Severity.INFO


def test_digest_empty_when_nothing_to_say():
    md = DailyDigest.build(on_date=date(2026, 4, 18)).markdown
    assert "_No new findings today._" in md


# ---------------------------------------------------------------------------
# WatchlistStore
# ---------------------------------------------------------------------------


@pytest.fixture
def watchlist(tmp_path):
    return WatchlistStore(path=tmp_path / "wl.db")


def test_watchlist_add_list_remove(watchlist):
    watchlist.add(WatchlistEntry(symbol="nvda", target_price=Decimal("150"), target_kind="buy_below"))
    watchlist.add(WatchlistEntry(symbol="aapl", target_price=Decimal("260"), target_kind="sell_above"))
    entries = watchlist.list()
    assert {e.symbol for e in entries} == {"NVDA", "AAPL"}
    watchlist.remove("NVDA")
    assert {e.symbol for e in watchlist.list()} == {"AAPL"}


def test_watchlist_history_round_trip(watchlist):
    watchlist.add(WatchlistEntry(symbol="VTI", target_price=Decimal("250")))
    watchlist.record_evaluation("VTI", "2026-04-18", 248.10, score=2, action="buy", rationale=["RSI < 30"])
    watchlist.record_evaluation("VTI", "2026-04-19", 250.50, score=0, action="hold", rationale=[])
    rows = watchlist.history("VTI")
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-04-19"  # newest-first


def test_watchlist_upsert_replaces(watchlist):
    watchlist.add(WatchlistEntry(symbol="VTI", target_price=Decimal("240")))
    watchlist.add(WatchlistEntry(symbol="VTI", target_price=Decimal("260"), notes="bumped"))
    entries = watchlist.list()
    assert len(entries) == 1
    assert entries[0].target_price == Decimal("260")
    assert entries[0].notes == "bumped"


# ---------------------------------------------------------------------------
# MonarchDaemon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daemon_runs_registered_job_then_stops(tmp_path):
    events = EventLog(path=tmp_path / "events.db")
    daemon = MonarchDaemon(DaemonConfig(), event_log=events)
    fired = asyncio.Event()

    async def job():
        fired.set()

    daemon.register_interval("ping", job, interval=timedelta(milliseconds=50))

    async def stopper():
        await fired.wait()
        daemon.stop()

    await asyncio.gather(daemon.run_forever(), stopper())
    rows = events.recent(source="daemon.job", kind="completed")
    assert any(r.detail.get("job") == "ping" for r in rows)


@pytest.mark.asyncio
async def test_daemon_records_failures_and_backs_off(tmp_path):
    events = EventLog(path=tmp_path / "events.db")
    daemon = MonarchDaemon(DaemonConfig(), event_log=events)
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("nope")

    daemon.register_interval("flaky", flaky, interval=timedelta(milliseconds=10))

    async def stopper():
        await asyncio.sleep(0.5)
        daemon.stop()

    await asyncio.gather(daemon.run_forever(), stopper())
    failures = events.recent(source="daemon.job", kind="failed")
    assert failures
    # Backoff should keep us from running more than ~5 times in 0.5s.
    assert 1 <= attempts <= 5
