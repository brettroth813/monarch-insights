"""Forecast / Monte Carlo smoke tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from monarch_insights.forecast.cashflow import CashflowForecaster
from monarch_insights.forecast.networth import NetWorthForecaster
from monarch_insights.forecast.retirement import RetirementSimulator
from monarch_insights.models import RecurringStream


def test_networth_projection_grows():
    proj = NetWorthForecaster.project(
        starting_value=Decimal(100_000),
        monthly_savings=Decimal(2_000),
        expected_annual_real_return=Decimal("0.05"),
        months=120,
    )
    assert proj.points[-1][1] > proj.points[0][1]
    assert proj.points[-1][1] > Decimal(300_000)


def test_cashflow_projection_includes_recurring():
    today = date.today()
    streams = [
        RecurringStream.model_validate(
            {
                "id": "rent",
                "name": "Rent",
                "frequency": "monthly",
                "averageAmount": -2000,
                "nextDate": (today + timedelta(days=5)).isoformat(),
            }
        ),
        RecurringStream.model_validate(
            {
                "id": "salary",
                "name": "Payroll",
                "frequency": "biweekly",
                "averageAmount": 2500,
                "nextDate": today.isoformat(),
            }
        ),
    ]
    forecaster = CashflowForecaster(low_balance_floor=Decimal(500))
    days = forecaster.project(Decimal(3000), streams, horizon_days=45)
    assert days[0].on_date == today
    assert days[-1].ending_balance != days[0].starting_balance


def test_monte_carlo_smoke():
    sim = RetirementSimulator(seed=42)
    result = sim.simulate(
        starting_balance=200_000,
        annual_savings=20_000,
        years_to_retirement=20,
        annual_spend_in_retirement=50_000,
        years_in_retirement=30,
        iterations=100,
    )
    assert 0 <= result.success_rate <= 1
    assert result.iterations == 100
    assert len(result.median_path) == 51
