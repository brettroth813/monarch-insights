"""yfinance-backed provider — best free coverage for quotes, fundamentals, options.

We import lazily so the rest of the library works without yfinance installed.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from monarch_insights.providers.market_data.base import (
    AnalystTargets,
    Dividend,
    Filing,
    Fundamentals,
    HistoricalBar,
    NewsArticle,
    OptionChain,
    OptionContract,
    Quote,
    Split,
)


def _yf():  # local import so missing optional dep doesn't crash imports
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yfinance not installed. `pip install yfinance curl_cffi`"
        ) from exc
    return yf


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


class YFinanceProvider:
    name = "yfinance"

    def __init__(self, *, session=None) -> None:
        self._session = session

    def _ticker(self, symbol: str):
        yf = _yf()
        return yf.Ticker(symbol, session=self._session) if self._session else yf.Ticker(symbol)

    async def quote(self, symbol: str) -> Quote:
        def _do() -> Quote:
            t = self._ticker(symbol)
            info = t.fast_info
            history = t.history(period="2d", auto_adjust=False)
            last = history["Close"].iloc[-1] if len(history) else None
            prev = history["Close"].iloc[-2] if len(history) > 1 else None
            change = (last - prev) if last is not None and prev is not None else None
            change_pct = (change / prev) if change is not None and prev else None
            return Quote(
                symbol=symbol,
                price=_dec(last) or _dec(getattr(info, "last_price", None)) or Decimal(0),
                currency=getattr(info, "currency", "USD") or "USD",
                as_of=datetime.utcnow(),
                change=_dec(change),
                change_pct=_dec(change_pct),
                day_high=_dec(getattr(info, "day_high", None)),
                day_low=_dec(getattr(info, "day_low", None)),
                fifty_two_week_high=_dec(getattr(info, "year_high", None)),
                fifty_two_week_low=_dec(getattr(info, "year_low", None)),
                market_cap=_dec(getattr(info, "market_cap", None)),
                volume=int(getattr(info, "last_volume", 0) or 0) or None,
                source=self.name,
            )

        return await asyncio.to_thread(_do)

    async def historical(
        self, symbol: str, start: date, end: date | None = None, interval: str = "1d"
    ) -> list[HistoricalBar]:
        def _do() -> list[HistoricalBar]:
            t = self._ticker(symbol)
            df = t.history(
                start=start.isoformat(),
                end=(end or date.today()).isoformat(),
                interval=interval,
                auto_adjust=False,
            )
            bars: list[HistoricalBar] = []
            for ts, row in df.iterrows():
                bars.append(
                    HistoricalBar(
                        symbol=symbol,
                        on_date=ts.date(),
                        open=_dec(row.get("Open")) or Decimal(0),
                        high=_dec(row.get("High")) or Decimal(0),
                        low=_dec(row.get("Low")) or Decimal(0),
                        close=_dec(row.get("Close")) or Decimal(0),
                        volume=int(row.get("Volume") or 0),
                        adj_close=_dec(row.get("Adj Close")),
                    )
                )
            return bars

        return await asyncio.to_thread(_do)

    async def fundamentals(self, symbol: str) -> Fundamentals:
        def _do() -> Fundamentals:
            t = self._ticker(symbol)
            info = getattr(t, "info", {}) or {}
            return Fundamentals(
                symbol=symbol,
                name=info.get("longName") or info.get("shortName"),
                sector=info.get("sector"),
                industry=info.get("industry"),
                market_cap=_dec(info.get("marketCap")),
                pe_ratio=_dec(info.get("trailingPE")),
                forward_pe=_dec(info.get("forwardPE")),
                peg_ratio=_dec(info.get("pegRatio")),
                price_to_book=_dec(info.get("priceToBook")),
                dividend_yield=_dec(info.get("dividendYield")),
                payout_ratio=_dec(info.get("payoutRatio")),
                beta=_dec(info.get("beta")),
                eps_ttm=_dec(info.get("trailingEps")),
                revenue_ttm=_dec(info.get("totalRevenue")),
                profit_margin=_dec(info.get("profitMargins")),
                debt_to_equity=_dec(info.get("debtToEquity")),
                free_cash_flow=_dec(info.get("freeCashflow")),
                extra={
                    "currency": info.get("currency"),
                    "country": info.get("country"),
                    "website": info.get("website"),
                },
                source=self.name,
            )

        return await asyncio.to_thread(_do)

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        def _do() -> OptionChain:
            t = self._ticker(symbol)
            expirations = list(t.options or [])
            if not expirations:
                return OptionChain(symbol=symbol, expiry=date.today())
            if expiry is None:
                use = expirations[0]
            else:
                target = expiry.isoformat()
                use = next((e for e in expirations if e == target), expirations[0])
            chain = t.option_chain(use)
            chosen = date.fromisoformat(use)

            def _row(side: str, row) -> OptionContract:
                return OptionContract(
                    symbol=row.get("contractSymbol") or symbol,
                    strike=_dec(row.get("strike")) or Decimal(0),
                    expiry=chosen,
                    side=side,
                    bid=_dec(row.get("bid")),
                    ask=_dec(row.get("ask")),
                    last=_dec(row.get("lastPrice")),
                    volume=int(row.get("volume") or 0) or None,
                    open_interest=int(row.get("openInterest") or 0) or None,
                    iv=_dec(row.get("impliedVolatility")),
                )

            calls = [_row("call", r) for _, r in chain.calls.iterrows()]
            puts = [_row("put", r) for _, r in chain.puts.iterrows()]
            return OptionChain(symbol=symbol, expiry=chosen, calls=calls, puts=puts)

        return await asyncio.to_thread(_do)

    async def dividends(self, symbol: str) -> list[Dividend]:
        def _do() -> list[Dividend]:
            t = self._ticker(symbol)
            series = t.dividends
            out: list[Dividend] = []
            for ts, amount in series.items():
                out.append(
                    Dividend(
                        symbol=symbol,
                        ex_date=ts.date(),
                        pay_date=None,
                        amount=_dec(amount) or Decimal(0),
                    )
                )
            return out

        return await asyncio.to_thread(_do)

    async def splits(self, symbol: str) -> list[Split]:
        def _do() -> list[Split]:
            t = self._ticker(symbol)
            series = t.splits
            out: list[Split] = []
            for ts, ratio in series.items():
                out.append(Split(symbol=symbol, on_date=ts.date(), ratio=_dec(ratio) or Decimal(1)))
            return out

        return await asyncio.to_thread(_do)

    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]:
        def _do() -> list[NewsArticle]:
            t = self._ticker(symbol)
            news = t.news or []
            out: list[NewsArticle] = []
            for item in news[:limit]:
                content = item.get("content") or item
                ts = content.get("pubDate") or content.get("providerPublishTime")
                published = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if isinstance(ts, str)
                    else datetime.utcfromtimestamp(ts)
                    if isinstance(ts, (int, float))
                    else datetime.utcnow()
                )
                out.append(
                    NewsArticle(
                        symbol=symbol,
                        headline=content.get("title", ""),
                        url=(content.get("clickThroughUrl") or {}).get("url")
                        or content.get("link", ""),
                        published=published,
                        summary=content.get("summary"),
                        source=(content.get("provider") or {}).get("displayName"),
                    )
                )
            return out

        return await asyncio.to_thread(_do)

    async def analyst_targets(self, symbol: str) -> AnalystTargets:
        def _do() -> AnalystTargets:
            t = self._ticker(symbol)
            info = getattr(t, "info", {}) or {}
            return AnalystTargets(
                symbol=symbol,
                consensus=info.get("recommendationKey"),
                high=_dec(info.get("targetHighPrice")),
                low=_dec(info.get("targetLowPrice")),
                mean=_dec(info.get("targetMeanPrice")),
                median=_dec(info.get("targetMedianPrice")),
                number_of_analysts=int(info.get("numberOfAnalystOpinions") or 0) or None,
                last_updated=datetime.utcnow(),
            )

        return await asyncio.to_thread(_do)

    async def filings(self, symbol: str, form_type: str | None = None, limit: int = 10) -> list[Filing]:
        # yfinance doesn't expose filings; let the router fall through to EDGAR.
        raise NotImplementedError
