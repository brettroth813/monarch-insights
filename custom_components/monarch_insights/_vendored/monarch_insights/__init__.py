"""Monarch Insights — personal finance analytics library that augments Monarch Money."""

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.exceptions import (
    MonarchAuthError,
    MonarchError,
    MonarchMFARequired,
    MonarchRateLimited,
)

__all__ = [
    "MonarchClient",
    "MonarchError",
    "MonarchAuthError",
    "MonarchMFARequired",
    "MonarchRateLimited",
]

__version__ = "0.1.0"
