"""Tax-prep utilities. Designed for personal-use sanity checks, not as a tax filer."""

from monarch_insights.tax.brackets import TaxBracket, FilingStatus, federal_brackets, marginal_rate
from monarch_insights.tax.estimated import EstimatedTaxTracker, QuarterlyDue
from monarch_insights.tax.income import (
    IncomeAggregator,
    IncomeReport,
    InvestmentIncomeBreakdown,
)
from monarch_insights.tax.deductions import DeductionFinder, DeductionCandidate
from monarch_insights.tax.capital_gains import CapitalGainsReport, RealizedGainEntry, harvest_candidates
from monarch_insights.tax.reports import TaxPacket, build_packet

__all__ = [
    "CapitalGainsReport",
    "DeductionCandidate",
    "DeductionFinder",
    "EstimatedTaxTracker",
    "FilingStatus",
    "IncomeAggregator",
    "IncomeReport",
    "InvestmentIncomeBreakdown",
    "QuarterlyDue",
    "RealizedGainEntry",
    "TaxBracket",
    "TaxPacket",
    "build_packet",
    "federal_brackets",
    "harvest_candidates",
    "marginal_rate",
]
