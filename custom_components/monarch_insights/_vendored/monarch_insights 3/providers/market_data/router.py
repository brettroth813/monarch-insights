"""Routes market-data calls across multiple providers with caching and fallback."""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Awaitable, Callable, Sequence, TypeVar

from monarch_insights.observability import get_logger
from monarch_insights.providers.market_data.base import (
    AnalystTargets,
    Dividend,
    Filing,
    Fundamentals,
    HistoricalBar,
    MarketDataProvider,
    NewsArticle,
    OptionChain,
    Quote,
    Split,
)

log = get_logger(__name__)
T = TypeVar("T")


class MarketDataRouter:
    """Tries each provider in order; first non-error result wins.

    Includes a small in-process TTL cache so the same call doesn't hammer providers when
    insight modules ask for the same quote three times in a single render.
    """

    def __init__(
        self,
        providers: Sequence[MarketDataProvider],
        *,
        cache_ttl_seconds: int = 60,
    ) -> None:
        if not providers:
            raise ValueError("MarketDataRouter requires at least one provider")
        self.providers = list(providers)
        self.cache_ttl = cache_ttl_seconds
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ helpers

    async def _try(
        self,
        operation: str,
        cache_key: tuple,
        invoke: Callable[[MarketDataProvider], Awaitable[T]],
    ) -> T:
        async with self._lock:
            cached = self._cache.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]  # type: ignore[return-value]

        last_exc: Exception | None = None
        for provider in self.providers:
            try:
                value = await invoke(provider)
                async with self._lock:
                    self._cache[cache_key] = (time.time() + self.cache_ttl, value)
                return value
            except NotImplementedError:
                continue
            except Exception as exc:  # noqa: BLE001 — we deliberately try the next one
                log.warning("provider %s failed %s: %s", provider.name, operation, exc)
                last_exc = exc
        raise RuntimeError(
            f"All providers failed {operation}: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------ surface

    async def quote(self, symbol: str) -> Quote:
        return await self._try(
            "quote", ("quote", symbol), lambda p: p.quote(symbol)
        )

    async def historical(
        self, symbol: str, start: date, end: date | None = None, interval: str = "1d"
    ) -> list[HistoricalBar]:
        return await self._try(
            "historical",
            ("hist", symbol, start, end, interval),
            lambda p: p.historical(symbol, start, end, interval),
        )

    async def fundamentals(self, symbol: str) -> Fundamentals:
        return await self._try(
            "fundamentals", ("fund", symbol), lambda p: p.fundamentals(symbol)
        )

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        return await self._try(
            "option_chain",
            ("opt", symbol, expiry),
            lambda p: p.option_chain(symbol, expiry),
        )

    async def dividends(self, symbol: str) -> list[Dividend]:
        return await self._try(
            "dividends", ("div", symbol), lambda p: p.dividends(symbol)
        )

    async def splits(self, symbol: str) -> list[Split]:
        return await self._try("splits", ("spl", symbol), lambda p: p.splits(symbol))

    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]:
        return await self._try(
            "news", ("news", symbol, limit), lambda p: p.news(symbol, limit)
        )

    async def analyst_targets(self, symbol: str) -> AnalystTargets:
        return await self._try(
            "targets", ("tgt", symbol), lambda p: p.analyst_targets(symbol)
        )

    async def filings(
        self, symbol: str, form_type: str | None = None, limit: int = 10
    ) -> list[Filing]:
        return await self._try(
            "filings",
            ("fil", symbol, form_type, limit),
            lambda p: p.filings(symbol, form_type, limit),
        )
