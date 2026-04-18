"""Market-data provider plugins."""

from monarch_insights.providers.market_data.base import (
    AnalystTargets,
    Filing,
    MarketDataProvider,
    NewsArticle,
    OptionChain,
    Quote,
)
from monarch_insights.providers.market_data.edgar import EdgarProvider
from monarch_insights.providers.market_data.finnhub import FinnhubProvider
from monarch_insights.providers.market_data.fred import FredProvider
from monarch_insights.providers.market_data.router import MarketDataRouter
from monarch_insights.providers.market_data.yfinance import YFinanceProvider

__all__ = [
    "AnalystTargets",
    "EdgarProvider",
    "Filing",
    "FinnhubProvider",
    "FredProvider",
    "MarketDataProvider",
    "MarketDataRouter",
    "NewsArticle",
    "OptionChain",
    "Quote",
    "YFinanceProvider",
]
