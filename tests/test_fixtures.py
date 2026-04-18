"""Smoke-test the fixtures so demo + downstream tests stay reliable."""

from __future__ import annotations

from decimal import Decimal

from monarch_insights.models import Account, Holding, RecurringStream, Transaction

from tests.fixtures import (
    build_accounts,
    build_budgets,
    build_goals,
    build_holdings,
    build_recurring,
    build_transactions,
)


def test_accounts_well_formed():
    accounts = build_accounts()
    assert len(accounts) == 10
    assert all(isinstance(a, Account) for a in accounts)
    # Mix of assets + liabilities expected
    assert any(a.is_liability for a in accounts)
    assert any(not a.is_liability for a in accounts)


def test_holdings_have_known_tickers():
    tickers = {h.ticker for h in build_holdings()}
    assert {"VTI", "VXUS", "BND", "AAPL", "VOO", "NVDA"} <= tickers


def test_transactions_volume_and_signs():
    txs = build_transactions(days=90)
    assert len(txs) > 100
    inflows = [t for t in txs if t.is_inflow]
    outflows = [t for t in txs if t.is_outflow]
    assert inflows and outflows


def test_recurring_streams_parse():
    streams = build_recurring()
    assert all(isinstance(s, RecurringStream) for s in streams)
    income = [s for s in streams if s.is_income]
    assert income


def test_budgets_and_goals():
    budgets = build_budgets()
    assert len(budgets) == 1
    assert len(budgets[0].items) >= 3
    goals = build_goals()
    assert len(goals) == 2
