"""Account-specific direct integrations.

Where Monarch's aggregator is thin or stale, we go direct. Currently scaffolds:
  * Schwab (official Charles Schwab API — needs developer registration)
  * Robinhood (via robin_stocks)
  * Plaid passthrough (for Chase / Marcus / Amex / Citi / Barclays / Bilt — non-direct)
  * Email-derived (for institutions with no API)
  * Toyota Financial Services (web-scrape stub — read-only)
"""

from monarch_insights.providers.accounts.base import (
    AccountProvider,
    AccountSnapshot,
    StatementReference,
    TradeRecord,
)
from monarch_insights.providers.accounts.directory import build_default_directory

__all__ = [
    "AccountProvider",
    "AccountSnapshot",
    "StatementReference",
    "TradeRecord",
    "build_default_directory",
]
