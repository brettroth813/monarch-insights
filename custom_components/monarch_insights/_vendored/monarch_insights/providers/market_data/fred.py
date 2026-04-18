"""FRED — Federal Reserve macro data. Free, near-unlimited."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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

BASE = "https://api.stlouisfed.org/fred"


@dataclass
class FredObservation:
    series_id: str
    on_date: date
    value: Decimal | None


KNOWN_SERIES = {
    "CPI": "CPIAUCSL",
    "CORE_CPI": "CPILFESL",
    "FED_FUNDS": "FEDFUNDS",
    "10Y_TREASURY": "DGS10",
    "30Y_MORTGAGE": "MORTGAGE30US",
    "UNEMPLOYMENT": "UNRATE",
    "REAL_GDP": "GDPC1",
    "M2": "M2SL",
    "VIX": "VIXCLS",
    "SP500": "SP500",
}


class FredProvider:
    name = "fred"

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError("FRED requires a free API key")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        params = dict(params)
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        async with aiohttp.ClientSession(timeout=self.timeout) as http:
            async with http.get(f"{BASE}{path}", params=params) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_series(
        self, series_id: str, start: date | None = None, end: date | None = None
    ) -> list[FredObservation]:
        params: dict[str, Any] = {"series_id": series_id}
        if start:
            params["observation_start"] = start.isoformat()
        if end:
            params["observation_end"] = end.isoformat()
        data = await self._get("/series/observations", params)
        out: list[FredObservation] = []
        for obs in data.get("observations") or []:
            try:
                value = Decimal(obs["value"]) if obs["value"] not in (".", "") else None
            except Exception:
                value = None
            out.append(
                FredObservation(
                    series_id=series_id,
                    on_date=date.fromisoformat(obs["date"]),
                    value=value,
                )
            )
        return out

    async def latest(self, alias_or_series: str) -> FredObservation | None:
        series_id = KNOWN_SERIES.get(alias_or_series.upper(), alias_or_series)
        observations = await self.get_series(series_id)
        for obs in reversed(observations):
            if obs.value is not None:
                return obs
        return None

    # MarketDataProvider stubs — FRED doesn't speak securities.
    async def quote(self, symbol: str) -> Quote: raise NotImplementedError
    async def historical(self, symbol: str, start: date, end: date | None = None, interval: str = "1d"): raise NotImplementedError
    async def fundamentals(self, symbol: str) -> Fundamentals: raise NotImplementedError
    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain: raise NotImplementedError
    async def dividends(self, symbol: str) -> list[Dividend]: raise NotImplementedError
    async def splits(self, symbol: str) -> list[Split]: raise NotImplementedError
    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]: raise NotImplementedError
    async def analyst_targets(self, symbol: str) -> AnalystTargets: raise NotImplementedError
    async def filings(self, symbol: str, form_type: str | None = None, limit: int = 10) -> list[Filing]: raise NotImplementedError
