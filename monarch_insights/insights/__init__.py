"""Insight modules: read-only analytics over Monarch + supplements."""

from monarch_insights.insights.anomalies import AnomalyDetector, SpendingAnomaly
from monarch_insights.insights.cashflow import CashflowInsights, MonthlyCashflow
from monarch_insights.insights.investments import (
    AllocationDrift,
    HoldingPerformance,
    InvestmentInsights,
    PortfolioStats,
)
from monarch_insights.insights.networth import NetWorthInsights, NetWorthBreakdown
from monarch_insights.insights.recurring import (
    RecurringInsights,
    SubscriptionAlert,
    SubscriptionDuplicate,
)
from monarch_insights.insights.spending import SpendingInsights, BudgetPace, MerchantSpend

__all__ = [
    "AllocationDrift",
    "AnomalyDetector",
    "BudgetPace",
    "CashflowInsights",
    "HoldingPerformance",
    "InvestmentInsights",
    "MerchantSpend",
    "MonthlyCashflow",
    "NetWorthBreakdown",
    "NetWorthInsights",
    "PortfolioStats",
    "RecurringInsights",
    "SpendingAnomaly",
    "SpendingInsights",
    "SubscriptionAlert",
    "SubscriptionDuplicate",
]
