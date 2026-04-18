"""Supplementary data store: things Monarch doesn't have but insights need.

Cost basis lots, paystub line items, RSU/RSU-equivalent vest schedules, manual income
(K-1, side business, child support), document references, target asset allocations,
financial goals overrides, custom tax-relevant tags.
"""

from monarch_insights.supplements.store import SupplementStore
from monarch_insights.supplements.cost_basis import CostBasisLot, CostBasisLedger
from monarch_insights.supplements.paystubs import Paystub, PaystubLineItem
from monarch_insights.supplements.income import IncomeSource, IncomeEvent
from monarch_insights.supplements.documents import Document
from monarch_insights.supplements.targets import AllocationTarget, FinancialPlan

__all__ = [
    "AllocationTarget",
    "CostBasisLedger",
    "CostBasisLot",
    "Document",
    "FinancialPlan",
    "IncomeEvent",
    "IncomeSource",
    "Paystub",
    "PaystubLineItem",
    "SupplementStore",
]
