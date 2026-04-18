"""Email→cost-basis pipeline coverage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from monarch_insights.observability import EventLog
from monarch_insights.providers.accounts.email_pipeline import (
    ingest_trade_signals,
    parse_trade,
)
from monarch_insights.providers.accounts.email_provider import EmailSignal
from monarch_insights.supplements.store import SupplementStore


def _signal(**kwargs) -> EmailSignal:
    base = dict(
        institution="Schwab",
        kind="trade",
        received_at=datetime(2026, 4, 17, 14, 0, tzinfo=timezone.utc),
        subject="Trade confirmation",
        sender="alerts@schwab.com",
        body="",
        message_id="MSG-1",
    )
    base.update(kwargs)
    return EmailSignal(**base)


def test_parse_schwab_buy():
    signal = _signal(body="You bought 25 shares of AAPL at $187.45 today.")
    parsed = parse_trade(signal)
    assert parsed["side"] == "buy"
    assert parsed["ticker"] == "AAPL"
    assert float(parsed["qty"]) == 25
    assert float(parsed["price"]) == 187.45


def test_parse_robinhood_fill():
    signal = _signal(
        institution="Robinhood",
        sender="notifications@robinhood.com",
        subject="Order filled",
        body="Order filled: 5 NVDA @ $480.21",
    )
    parsed = parse_trade(signal)
    assert parsed["ticker"] == "NVDA"
    assert float(parsed["qty"]) == 5


def test_parse_returns_none_on_garbage():
    assert parse_trade(_signal(body="Your statement is ready")) is None


@pytest.fixture
def store(tmp_path):
    return SupplementStore(path=tmp_path / "supp.db")


def test_ingest_writes_lot_for_buy(store, tmp_path):
    events = EventLog(path=tmp_path / "events.db")
    signals = [_signal(body="You bought 10 shares of VTI at $230.50")]
    result = ingest_trade_signals(
        signals,
        store=store,
        account_resolver={"Schwab": "ACT_schwab_brokerage"}.get,
        event_log=events,
    )
    assert len(result.lots_added) == 1
    lots = store.lots_for("ACT_schwab_brokerage", "VTI")
    assert lots and lots[0]["quantity"] == 10
    assert events.count(source="email.trade", kind="lot.added") == 1


def test_ingest_files_info_request_for_sell(store):
    signals = [_signal(body="You sold 5 shares of NVDA at $475.00")]
    result = ingest_trade_signals(
        signals,
        store=store,
        account_resolver={"Schwab": "ACT_schwab_brokerage"}.get,
    )
    assert not result.lots_added
    assert result.info_requests
    assert result.info_requests[0].kind.value == "cost_basis"


def test_ingest_creates_info_request_when_account_unmapped(store):
    # Body must be parseable so the pipeline reaches the account-resolver step;
    # then with no mapping we expect an ``account_history`` info request.
    signals = [_signal(institution="Mystery Bank", body="You bought 1 shares of ZZZZ at $1.00")]
    result = ingest_trade_signals(
        signals,
        store=store,
        account_resolver={}.get,  # no mapping
    )
    assert not result.lots_added
    assert any(r.kind.value == "account_history" for r in result.info_requests)


def test_ingest_logs_unparsed_emails(store, tmp_path):
    events = EventLog(path=tmp_path / "events.db")
    signals = [_signal(body="hello world", subject="Account update")]
    result = ingest_trade_signals(
        signals,
        store=store,
        account_resolver={"Schwab": "ACT_schwab_brokerage"}.get,
        event_log=events,
    )
    assert events.count(source="email.trade", kind="unparsed") == 1
    assert result.info_requests
