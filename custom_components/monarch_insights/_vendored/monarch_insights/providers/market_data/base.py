"""Provider interface for market data.

Every provider implements the same protocol so the router can fail over from one to
another (yfinance → Stooq → FMP). When a provider doesn't expose a category (FRED has
no quotes, EDGAR no prices), it raises ``NotImplementedError`` and the router skips it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass
class Quote:
    symbol: str
    price: Decimal
    currency: str = "USD"
    as_of: datetime | None = None
    change: Decimal | None = None
    change_pct: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    fifty_two_week_high: Decimal | None = None
    fifty_two_week_low: Decimal | None = None
    market_cap: Decimal | None = None
    volume: int | None = None
    source: str = ""


@dataclass
class HistoricalBar:
    symbol: str
    on_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    adj_close: Decimal | None = None


@dataclass
class Fundamentals:
    symbol: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: Decimal | None = None
    pe_ratio: Decimal | None = None
    forward_pe: Decimal | None = None
    peg_ratio: Decimal | None = None
    price_to_book: Decimal | None = None
    dividend_yield: Decimal | None = None
    payout_ratio: Decimal | None = None
    beta: Decimal | None = None
    eps_ttm: Decimal | None = None
    revenue_ttm: Decimal | None = None
    profit_margin: Decimal | None = None
    debt_to_equity: Decimal | None = None
    free_cash_flow: Decimal | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    source: str = ""


@dataclass
class OptionContract:
    symbol: str
    strike: Decimal
    expiry: date
    side: str  # "call" | "put"
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    iv: Decimal | None = None
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None
    rho: Decimal | None = None


@dataclass
class OptionChain:
    symbol: str
    expiry: date
    calls: list[OptionContract] = field(default_factory=list)
    puts: list[OptionContract] = field(default_factory=list)


@dataclass
class Dividend:
    symbol: str
    ex_date: date
    pay_date: date | None
    amount: Decimal
    currency: str = "USD"


@dataclass
class Split:
    symbol: str
    on_date: date
    ratio: Decimal  # >1 means a split (2-for-1 = 2.0); <1 a reverse split


@dataclass
class NewsArticle:
    symbol: str
    headline: str
    url: str
    published: datetime
    summary: str | None = None
    source: str | None = None


@dataclass
class AnalystTargets:
    symbol: str
    consensus: str | None = None  # "Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"
    high: Decimal | None = None
    low: Decimal | None = None
    mean: Decimal | None = None
    median: Decimal | None = None
    number_of_analysts: int | None = None
    last_updated: datetime | None = None


@dataclass
class Filing:
    symbol: str
    form_type: str  # "10-K", "10-Q", "8-K", "13F", etc.
    filed_on: date
    accession_number: str
    url: str
    period_of_report: date | None = None
    summary: str | None = None


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    async def quote(self, symbol: str) -> Quote: ...
    async def historical(
        self, symbol: str, start: date, end: date | None = None, interval: str = "1d"
    ) -> list[HistoricalBar]: ...
    async def fundamentals(self, symbol: str) -> Fundamentals: ...
    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain: ...
    async def dividends(self, symbol: str) -> list[Dividend]: ...
    async def splits(self, symbol: str) -> list[Split]: ...
    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]: ...
    async def analyst_targets(self, symbol: str) -> AnalystTargets: ...
    async def filings(
        self, symbol: str, form_type: str | None = None, limit: int = 10
    ) -> list[Filing]: ...
