"""Finnhub free-tier provider — strongest analyst targets / consensus on the free plan."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import aiohttp

from monarch_insights.providers.market_data.base import (
    AnalystTargets,
    Dividend,
    Filing,
    Fundamentals,
    HistoricalBar,
    NewsArticle,
    OptionChain,
    Quote,
    Split,
)

BASE = "https://finnhub.io/api/v1"


class FinnhubProvider:
    name = "finnhub"

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError("Finnhub requires an API key (free tier ok)")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{BASE}{path}"
        params = dict(params or {})
        params["token"] = self.api_key
        async with aiohttp.ClientSession(timeout=self.timeout) as http:
            async with http.get(url, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def quote(self, symbol: str) -> Quote:
        data = await self._get("/quote", {"symbol": symbol})
        if not data or data.get("c") in (None, 0):
            raise RuntimeError(f"Finnhub returned no quote for {symbol}")
        return Quote(
            symbol=symbol,
            price=Decimal(str(data["c"])),
            change=Decimal(str(data.get("d") or 0)) if data.get("d") is not None else None,
            change_pct=(Decimal(str(data["dp"])) / Decimal(100)) if data.get("dp") is not None else None,
            day_high=Decimal(str(data["h"])) if data.get("h") else None,
            day_low=Decimal(str(data["l"])) if data.get("l") else None,
            as_of=(
                datetime.fromtimestamp(int(data.get("t") or 0), tz=timezone.utc)
                if data.get("t")
                else datetime.now(timezone.utc)
            ),
            source=self.name,
        )

    async def historical(
        self, symbol: str, start: date, end: date | None = None, interval: str = "1d"
    ) -> list[HistoricalBar]:
        # Free tier removed candles in 2024; raise so router falls through.
        raise NotImplementedError("Finnhub free tier no longer offers historical candles")

    async def fundamentals(self, symbol: str) -> Fundamentals:
        data = await self._get("/stock/metric", {"symbol": symbol, "metric": "all"})
        m = (data or {}).get("metric") or {}
        return Fundamentals(
            symbol=symbol,
            pe_ratio=_to_dec(m.get("peNormalizedAnnual") or m.get("peTTM")),
            forward_pe=_to_dec(m.get("peTTM")),
            price_to_book=_to_dec(m.get("pbAnnual")),
            dividend_yield=_to_dec(m.get("dividendYieldIndicatedAnnual")),
            beta=_to_dec(m.get("beta")),
            eps_ttm=_to_dec(m.get("epsTTM")),
            profit_margin=_to_dec(m.get("netProfitMarginAnnual")),
            debt_to_equity=_to_dec(m.get("totalDebtToEquityAnnual")),
            extra={"raw": m},
            source=self.name,
        )

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        raise NotImplementedError

    async def dividends(self, symbol: str) -> list[Dividend]:
        raise NotImplementedError

    async def splits(self, symbol: str) -> list[Split]:
        raise NotImplementedError

    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]:
        today = date.today()
        from_d = (today.replace(day=1)).isoformat()
        data = await self._get(
            "/company-news", {"symbol": symbol, "from": from_d, "to": today.isoformat()}
        )
        out: list[NewsArticle] = []
        for item in (data or [])[:limit]:
            out.append(
                NewsArticle(
                    symbol=symbol,
                    headline=item.get("headline", ""),
                    url=item.get("url", ""),
                    published=datetime.fromtimestamp(item.get("datetime") or 0, tz=timezone.utc),
                    summary=item.get("summary"),
                    source=item.get("source"),
                )
            )
        return out

    async def analyst_targets(self, symbol: str) -> AnalystTargets:
        target = await self._get("/stock/price-target", {"symbol": symbol})
        recs = await self._get("/stock/recommendation", {"symbol": symbol})
        latest = (recs or [{}])[0] if isinstance(recs, list) and recs else {}
        consensus = None
        if latest:
            counts = {
                "Strong Buy": int(latest.get("strongBuy") or 0),
                "Buy": int(latest.get("buy") or 0),
                "Hold": int(latest.get("hold") or 0),
                "Sell": int(latest.get("sell") or 0),
                "Strong Sell": int(latest.get("strongSell") or 0),
            }
            consensus = max(counts, key=counts.get) if any(counts.values()) else None
        return AnalystTargets(
            symbol=symbol,
            consensus=consensus,
            high=_to_dec(target.get("targetHigh")),
            low=_to_dec(target.get("targetLow")),
            mean=_to_dec(target.get("targetMean")),
            median=_to_dec(target.get("targetMedian")),
            number_of_analysts=int(target.get("numberOfAnalysts") or 0) or None,
            last_updated=datetime.now(timezone.utc),
        )

    async def filings(self, symbol: str, form_type: str | None = None, limit: int = 10) -> list[Filing]:
        data = await self._get("/stock/filings", {"symbol": symbol})
        out: list[Filing] = []
        for item in (data or [])[:limit]:
            if form_type and item.get("form") != form_type:
                continue
            try:
                filed_on = datetime.fromisoformat(item.get("filedDate", "")).date()
            except ValueError:
                continue
            out.append(
                Filing(
                    symbol=symbol,
                    form_type=item.get("form", ""),
                    filed_on=filed_on,
                    accession_number=item.get("accessNumber", ""),
                    url=item.get("reportUrl", ""),
                    period_of_report=None,
                )
            )
        return out


def _to_dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
