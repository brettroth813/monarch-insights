"""SEC EDGAR direct provider. Free, no API key, requires polite User-Agent."""

from __future__ import annotations

from datetime import date, datetime
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

BASE = "https://data.sec.gov"


class EdgarProvider:
    name = "edgar"

    def __init__(self, user_agent: str, *, timeout: float = 30.0) -> None:
        if "@" not in user_agent:
            raise ValueError(
                "EDGAR requires a contact email in the User-Agent string per their fair-use policy"
            )
        self.user_agent = user_agent
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._cik_cache: dict[str, str] = {}

    async def _get(self, url: str) -> Any:
        async with aiohttp.ClientSession(timeout=self.timeout) as http:
            async with http.get(url, headers={"User-Agent": self.user_agent}) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def _get_cik(self, symbol: str) -> str | None:
        symbol = symbol.upper()
        if symbol in self._cik_cache:
            return self._cik_cache[symbol]
        url = "https://www.sec.gov/files/company_tickers.json"
        data = await self._get(url)
        for entry in (data or {}).values():
            if entry.get("ticker") == symbol:
                cik = str(entry["cik_str"]).zfill(10)
                self._cik_cache[symbol] = cik
                return cik
        return None

    async def quote(self, symbol: str) -> Quote:
        raise NotImplementedError

    async def historical(self, symbol: str, start: date, end: date | None = None, interval: str = "1d"):
        raise NotImplementedError

    async def fundamentals(self, symbol: str) -> Fundamentals:
        raise NotImplementedError

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        raise NotImplementedError

    async def dividends(self, symbol: str) -> list[Dividend]:
        raise NotImplementedError

    async def splits(self, symbol: str) -> list[Split]:
        raise NotImplementedError

    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]:
        raise NotImplementedError

    async def analyst_targets(self, symbol: str) -> AnalystTargets:
        raise NotImplementedError

    async def filings(self, symbol: str, form_type: str | None = None, limit: int = 10) -> list[Filing]:
        cik = await self._get_cik(symbol)
        if cik is None:
            return []
        data = await self._get(f"{BASE}/submissions/CIK{cik}.json")
        recent = (data.get("filings") or {}).get("recent") or {}
        out: list[Filing] = []
        for i in range(min(len(recent.get("form", [])), 100)):
            form = recent["form"][i]
            if form_type and form != form_type:
                continue
            try:
                filed_on = date.fromisoformat(recent["filingDate"][i])
                period = (
                    date.fromisoformat(recent["reportDate"][i])
                    if recent["reportDate"][i]
                    else None
                )
            except (ValueError, IndexError):
                continue
            accession = recent["accessionNumber"][i].replace("-", "")
            primary = recent["primaryDocument"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{primary}"
            out.append(
                Filing(
                    symbol=symbol,
                    form_type=form,
                    filed_on=filed_on,
                    accession_number=recent["accessionNumber"][i],
                    url=url,
                    period_of_report=period,
                    summary=recent.get("primaryDocDescription", [None] * 100)[i],
                )
            )
            if len(out) >= limit:
                break
        return out
