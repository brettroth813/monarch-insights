"""Robinhood provider — uses ``robin_stocks`` (underscore!) for fundamentals + research.

Robinhood Gold gets you Morningstar/Nasdaq Level II inside the app, but the JSON we can
reach is the standard endpoint set. This is mostly useful for:
  * Pulling your *own* positions with broker-recorded average cost (fills the cost-basis gap).
  * Analyst rating *counts* via ``stocks.get_ratings``.
  * Earnings, dividend, and split history.
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
    Quote,
    Split,
)


def _rh():
    try:
        import robin_stocks.robinhood as rh  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "robin_stocks not installed. `pip install robin_stocks` (NOT robin-stocks)."
        ) from exc
    return rh


def _dec(value: Any) -> Decimal | None:
    if value in (None, "", "None"):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


class RobinhoodProvider:
    """Reads-only convenience wrapper around the existing ``robin_stocks`` session.

    Auth is performed by ``robin_stocks.login(...)`` outside this class so the same
    session can be shared with the account-positions sync. We do not store credentials.
    """

    name = "robinhood"

    def __init__(self) -> None:
        pass

    @staticmethod
    def login(username: str, password: str, mfa_code: str | None = None) -> dict[str, Any]:
        rh = _rh()
        return rh.login(username, password, mfa_code=mfa_code, store_session=True)

    @staticmethod
    def logout() -> None:
        rh = _rh()
        rh.logout()

    async def quote(self, symbol: str) -> Quote:
        def _do() -> Quote:
            rh = _rh()
            data = rh.stocks.get_quotes(symbol)
            row = (data or [None])[0]
            if not row:
                raise RuntimeError(f"No Robinhood quote for {symbol}")
            return Quote(
                symbol=symbol,
                price=_dec(row.get("last_trade_price")) or Decimal(0),
                bid=_dec(row.get("bid_price")),
                ask=_dec(row.get("ask_price")),
                as_of=datetime.utcnow(),
                source=self.name,
            )

        return await asyncio.to_thread(_do)

    async def historical(
        self, symbol: str, start: date, end: date | None = None, interval: str = "1d"
    ) -> list[HistoricalBar]:
        def _do() -> list[HistoricalBar]:
            rh = _rh()
            span = "5year" if (date.today() - start).days > 365 else "year"
            data = rh.stocks.get_stock_historicals(symbol, interval=interval.replace("1d", "day"), span=span)
            out: list[HistoricalBar] = []
            for r in data or []:
                d = datetime.fromisoformat(r["begins_at"].replace("Z", "+00:00")).date()
                if d < start:
                    continue
                if end and d > end:
                    continue
                out.append(
                    HistoricalBar(
                        symbol=symbol,
                        on_date=d,
                        open=_dec(r.get("open_price")) or Decimal(0),
                        high=_dec(r.get("high_price")) or Decimal(0),
                        low=_dec(r.get("low_price")) or Decimal(0),
                        close=_dec(r.get("close_price")) or Decimal(0),
                        volume=int(r.get("volume") or 0),
                    )
                )
            return out

        return await asyncio.to_thread(_do)

    async def fundamentals(self, symbol: str) -> Fundamentals:
        def _do() -> Fundamentals:
            rh = _rh()
            data = (rh.stocks.get_fundamentals(symbol) or [None])[0] or {}
            return Fundamentals(
                symbol=symbol,
                sector=data.get("sector"),
                industry=data.get("industry"),
                pe_ratio=_dec(data.get("pe_ratio")),
                dividend_yield=_dec(data.get("dividend_yield")),
                market_cap=_dec(data.get("market_cap")),
                extra={"raw": data},
                source=self.name,
            )

        return await asyncio.to_thread(_do)

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        def _do() -> OptionChain:
            rh = _rh()
            chain_meta = rh.options.get_chains(symbol) or {}
            expirations = chain_meta.get("expiration_dates") or []
            if not expirations:
                return OptionChain(symbol=symbol, expiry=date.today())
            chosen = expiry.isoformat() if expiry else expirations[0]
            calls = rh.options.find_options_by_expiration(symbol, chosen, optionType="call") or []
            puts = rh.options.find_options_by_expiration(symbol, chosen, optionType="put") or []

            def _row(side: str, item: dict) -> dict:
                from monarch_insights.providers.market_data.base import OptionContract
                return OptionContract(
                    symbol=item.get("symbol", symbol),
                    strike=_dec(item.get("strike_price")) or Decimal(0),
                    expiry=date.fromisoformat(chosen),
                    side=side,
                    bid=_dec(item.get("bid_price")),
                    ask=_dec(item.get("ask_price")),
                    last=_dec(item.get("last_trade_price")),
                    volume=int(item.get("volume") or 0) or None,
                    open_interest=int(item.get("open_interest") or 0) or None,
                    iv=_dec(item.get("implied_volatility")),
                    delta=_dec(item.get("delta")),
                    gamma=_dec(item.get("gamma")),
                    theta=_dec(item.get("theta")),
                    vega=_dec(item.get("vega")),
                    rho=_dec(item.get("rho")),
                )

            return OptionChain(
                symbol=symbol,
                expiry=date.fromisoformat(chosen),
                calls=[_row("call", c) for c in calls],
                puts=[_row("put", p) for p in puts],
            )

        return await asyncio.to_thread(_do)

    async def dividends(self, symbol: str) -> list[Dividend]:
        def _do() -> list[Dividend]:
            rh = _rh()
            instrument_url = rh.stocks.get_instrument_data(symbol)[0]["url"] if rh.stocks.get_instrument_data(symbol) else None
            if not instrument_url:
                return []
            data = rh.stocks.get_events(symbol) or []
            out: list[Dividend] = []
            for e in data:
                if e.get("type") != "dividend":
                    continue
                out.append(
                    Dividend(
                        symbol=symbol,
                        ex_date=date.fromisoformat(e["ex_date"]),
                        pay_date=date.fromisoformat(e["pay_date"]) if e.get("pay_date") else None,
                        amount=_dec(e.get("amount")) or Decimal(0),
                    )
                )
            return out

        return await asyncio.to_thread(_do)

    async def splits(self, symbol: str) -> list[Split]:
        def _do() -> list[Split]:
            rh = _rh()
            data = rh.stocks.get_splits(symbol) or []
            out: list[Split] = []
            for s in data:
                num = _dec(s.get("multiplier"))
                den = _dec(s.get("divisor"))
                ratio = (num / den) if num and den else Decimal(1)
                out.append(Split(symbol=symbol, on_date=date.fromisoformat(s["execution_date"]), ratio=ratio))
            return out

        return await asyncio.to_thread(_do)

    async def news(self, symbol: str, limit: int = 25) -> list[NewsArticle]:
        def _do() -> list[NewsArticle]:
            rh = _rh()
            data = rh.stocks.get_news(symbol) or []
            out: list[NewsArticle] = []
            for n in data[:limit]:
                published = datetime.fromisoformat(n["published_at"].replace("Z", "+00:00"))
                out.append(
                    NewsArticle(
                        symbol=symbol,
                        headline=n.get("title", ""),
                        url=n.get("url", ""),
                        published=published,
                        summary=n.get("summary"),
                        source=n.get("source"),
                    )
                )
            return out

        return await asyncio.to_thread(_do)

    async def analyst_targets(self, symbol: str) -> AnalystTargets:
        def _do() -> AnalystTargets:
            rh = _rh()
            data = rh.stocks.get_ratings(symbol) or {}
            summary = data.get("summary") or {}
            counts = {
                "Strong Buy": int(summary.get("num_buy_ratings") or 0),
                "Hold": int(summary.get("num_hold_ratings") or 0),
                "Sell": int(summary.get("num_sell_ratings") or 0),
            }
            consensus = max(counts, key=counts.get) if any(counts.values()) else None
            return AnalystTargets(
                symbol=symbol,
                consensus=consensus,
                number_of_analysts=sum(counts.values()) or None,
                last_updated=datetime.utcnow(),
            )

        return await asyncio.to_thread(_do)

    async def filings(self, symbol: str, form_type: str | None = None, limit: int = 10) -> list[Filing]:
        raise NotImplementedError

    # ------------------------------------------------------------------ extras

    async def my_positions(self) -> list[dict[str, Any]]:
        """Pull the user's *own* RH positions (with avg cost)."""
        def _do() -> list[dict[str, Any]]:
            rh = _rh()
            holdings = rh.account.build_holdings() or {}
            return [{"ticker": k, **v} for k, v in holdings.items()]

        return await asyncio.to_thread(_do)
