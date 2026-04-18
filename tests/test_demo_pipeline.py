"""Exercises the demo pipeline end-to-end against fixtures.

This test is deliberately permissive — it confirms the wiring works (no exceptions,
sensible counts) without locking in exact numeric outputs that fixture changes would
break.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from monarch_insights.alerts.dispatchers import LogDispatcher, StoreDispatcher
from monarch_insights.alerts.engine import AlertContext, AlertEngine
from monarch_insights.alerts.rules import default_rules
from monarch_insights.forecast.cashflow import CashflowForecaster
from monarch_insights.forecast.goals import GoalForecaster
from monarch_insights.forecast.retirement import RetirementSimulator
from monarch_insights.gaps.detector import GapDetector
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.insights.spending import SpendingInsights
from monarch_insights.storage.cache import MonarchCache
from monarch_insights.supplements.store import SupplementStore
from monarch_insights.tax.brackets import FilingStatus, federal_tax
from monarch_insights.tax.deductions import DeductionFinder
from monarch_insights.tax.income import IncomeAggregator

from tests.fixtures import (
    build_accounts,
    build_budgets,
    build_goals,
    build_holdings,
    build_recurring,
    build_transactions,
)


@pytest.fixture(scope="module")
def dataset():
    return {
        "accounts": build_accounts(),
        "holdings": build_holdings(),
        "transactions": build_transactions(days=90),  # 90 days keeps test under 5s
        "recurring": build_recurring(),
        "budgets": build_budgets(),
        "goals": build_goals(),
    }


def test_networth_pipeline(dataset):
    bd = NetWorthInsights.snapshot(dataset["accounts"])
    assert bd.assets > 0
    assert bd.liabilities > 0
    assert bd.net_worth == bd.assets - bd.liabilities


def test_cashflow_pipeline(dataset):
    monthly = CashflowInsights.monthly(dataset["transactions"], months=3)
    assert monthly
    avg = CashflowInsights.average_monthly_spend(monthly)
    assert avg > 0
    bd = NetWorthInsights.snapshot(dataset["accounts"])
    runway = NetWorthInsights.emergency_fund_runway(bd, avg)
    assert runway["available"] is True
    assert runway["months_of_runway"] > 0


def test_balance_forecast_runs(dataset):
    primary = next(a for a in dataset["accounts"] if a.id == "ACT_checking_primary")
    forecaster = CashflowForecaster(low_balance_floor=Decimal(2000))
    days = forecaster.project(primary.current_balance or Decimal(0), dataset["recurring"], horizon_days=30)
    assert len(days) == 31
    assert all(d.starting_balance is not None for d in days)


def test_spending_and_budget_pace(dataset):
    cats = SpendingInsights.top_categories(dataset["transactions"], limit=5)
    assert cats
    pace = SpendingInsights.budget_pace(dataset["budgets"][0])
    assert pace
    assert all(p.status in {"over_pace", "behind_pace", "on_pace", "ahead_of_pace", "no_budget"} for p in pace)


def test_investment_pipeline(dataset):
    insights = InvestmentInsights()
    stats = insights.stats(dataset["holdings"])
    assert stats.total_value > 0
    drift = insights.drift(
        dataset["holdings"],
        {
            "us_stock": {"target_pct": 60, "drift_threshold_pct": 5},
            "intl_stock": {"target_pct": 25, "drift_threshold_pct": 5},
            "bond": {"target_pct": 15, "drift_threshold_pct": 5},
        },
    )
    assert drift
    drag = insights.expense_ratio_drag(dataset["holdings"])
    assert drag["annual_cost"] >= 0


def test_gap_detector_emits_known_requests(dataset):
    with tempfile.TemporaryDirectory() as tmp:
        store = SupplementStore(path=Path(tmp) / "supp.db")
        report = GapDetector(store).run(
            dataset["accounts"],
            dataset["holdings"],
            dataset["transactions"],
            dataset["recurring"],
            persist=False,
        )
        kinds = {r.kind.value for r in report.requests}
        # NVDA holding has no cost basis, brokerage exists, no targets set.
        assert "cost_basis" in kinds
        assert "allocation_target" in kinds


def test_alert_engine_runs_without_error(dataset):
    with tempfile.TemporaryDirectory() as tmp:
        cache = MonarchCache(path=Path(tmp) / "cache.db")
        primary = next(a for a in dataset["accounts"] if a.id == "ACT_checking_primary")
        ctx = AlertContext(
            accounts=dataset["accounts"],
            transactions=dataset["transactions"],
            holdings=dataset["holdings"],
            recurring=dataset["recurring"],
            budgets=dataset["budgets"],
            goals=dataset["goals"],
            targets={
                "us_stock": {"target_pct": 60, "drift_threshold_pct": 5},
                "intl_stock": {"target_pct": 25, "drift_threshold_pct": 5},
                "bond": {"target_pct": 15, "drift_threshold_pct": 5},
            },
            extras={
                "checking_balance": float(primary.current_balance or 0),
                "low_balance_floor": 2000,
                "concentration_threshold_pct": 10,
                "quotes": {"NVDA": {"change_pct": 0.07}},
                "price_move_threshold_pct": 5,
            },
        )
        engine = AlertEngine(default_rules())
        alerts = engine.evaluate(ctx)
        assert alerts  # We seeded enough fixture noise to produce at least a few alerts.
        asyncio.run(engine.dispatch(alerts, [LogDispatcher(), StoreDispatcher(cache)]))


def test_tax_pipeline(dataset):
    agg = IncomeAggregator()
    report = agg.aggregate(year=date.today().year, transactions=dataset["transactions"])
    deductions = DeductionFinder().scan(dataset["transactions"], year=date.today().year)
    assert report.gross_income >= 0
    tax = federal_tax(report.gross_income, FilingStatus.SINGLE)
    assert tax >= 0


def test_retirement_simulator_smoke():
    sim = RetirementSimulator(seed=1)
    result = sim.simulate(
        starting_balance=200_000,
        annual_savings=20_000,
        years_to_retirement=15,
        annual_spend_in_retirement=60_000,
        years_in_retirement=25,
        iterations=50,
    )
    assert 0 <= result.success_rate <= 1
    assert result.iterations == 50


def test_goal_forecaster(dataset):
    projections = GoalForecaster.project(dataset["goals"])
    assert len(projections) == len(dataset["goals"])
    for p in projections:
        if p.monthly_contribution and p.monthly_contribution > 0:
            assert p.months_to_target is not None
