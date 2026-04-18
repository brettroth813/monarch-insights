"""Robinhood account provider — for positions, orders, and history.

Reuses the same ``robin_stocks`` session that the market-data provider uses.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from monarch_insights.providers.accounts.base import (
    AccountSnapshot,
    StatementReference,
    TradeRecord,
)


def _rh():
    try:
        import robin_stocks.robinhood as rh  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("robin_stocks not installed (use the underscore variant)") from exc
    return rh


class RobinhoodAccountProvider:
    name = "robinhood-account"
    institution = "Robinhood"
    auth_kind = "user_pass_mfa"

    async def list_accounts(self) -> list[AccountSnapshot]:
        def _do() -> list[AccountSnapshot]:
            rh = _rh()
            profile = rh.profiles.load_account_profile() or {}
            portfolio = rh.profiles.load_portfolio_profile() or {}
            equity = portfolio.get("equity") or portfolio.get("market_value") or 0
            return [
                AccountSnapshot(
                    institution=self.institution,
                    external_account_id=profile.get("account_number", "RH"),
                    display_name="Robinhood Brokerage",
                    account_type="brokerage",
                    balance=Decimal(str(equity)),
                    as_of=datetime.now(timezone.utc),
                    currency="USD",
                    extra={"buying_power": profile.get("buying_power")},
                )
            ]

        return await asyncio.to_thread(_do)

    async def list_trades(
        self, account_id: str, start: date | None = None, end: date | None = None
    ) -> list[TradeRecord]:
        def _do() -> list[TradeRecord]:
            rh = _rh()
            orders = rh.orders.get_all_stock_orders() or []
            out: list[TradeRecord] = []
            for o in orders:
                if o.get("state") != "filled":
                    continue
                executed_at = o.get("last_transaction_at") or o.get("updated_at")
                try:
                    on_date = datetime.fromisoformat(executed_at.replace("Z", "+00:00")).date()
                except Exception:
                    continue
                if start and on_date < start:
                    continue
                if end and on_date > end:
                    continue
                instrument_url = o.get("instrument")
                ticker = None
                if instrument_url:
                    instrument = rh.stocks.get_instrument_by_url(instrument_url) or {}
                    ticker = instrument.get("symbol")
                if not ticker:
                    continue
                out.append(
                    TradeRecord(
                        institution=self.institution,
                        external_account_id=account_id,
                        ticker=ticker,
                        quantity=Decimal(str(o.get("cumulative_quantity") or 0)),
                        price_per_share=Decimal(str(o.get("average_price") or 0)),
                        side=o.get("side", "buy"),
                        on_date=on_date,
                        fees=Decimal(str(o.get("fees") or 0)),
                        external_id=o.get("id"),
                    )
                )
            return out

        return await asyncio.to_thread(_do)

    async def list_statements(self, account_id: str, since: date | None = None) -> list[StatementReference]:
        return []
