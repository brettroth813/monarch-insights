"""Forecasting: cashflow projections, net worth, FIRE Monte Carlo, goals."""

from monarch_insights.forecast.cashflow import CashflowForecaster, ProjectedDay
from monarch_insights.forecast.networth import NetWorthForecaster, NetWorthProjection
from monarch_insights.forecast.retirement import (
    FireOutcome,
    MonteCarloResult,
    RetirementSimulator,
)
from monarch_insights.forecast.goals import GoalForecaster, GoalProjection

__all__ = [
    "CashflowForecaster",
    "FireOutcome",
    "GoalForecaster",
    "GoalProjection",
    "MonteCarloResult",
    "NetWorthForecaster",
    "NetWorthProjection",
    "ProjectedDay",
    "RetirementSimulator",
]
