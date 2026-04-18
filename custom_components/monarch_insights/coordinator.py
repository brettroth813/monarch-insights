"""DataUpdateCoordinator that pulls from Monarch and runs the insight pipeline."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth
from monarch_insights.gaps.detector import GapDetector
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.storage.cache import MonarchCache
from monarch_insights.supplements.store import SupplementStore

from .const import (
    CONF_REFRESH_INTERVAL_MIN,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class MonarchInsightsCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_REFRESH_INTERVAL_MIN, DEFAULT_REFRESH_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self.entry = entry
        self.cache = MonarchCache()
        self.store = SupplementStore()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            auth = MonarchAuth()
            auth.load()
            client = MonarchClient(auth)
            await client.start()
            try:
                accounts = await client.get_accounts()
                holdings = await client.get_holdings()
                txs = []
                async for t in client.iter_transactions(start_date=date.today() - timedelta(days=180)):
                    txs.append(t)
                recurring = await client.get_recurring()
            finally:
                await client.close()

            networth = NetWorthInsights.snapshot(accounts)
            monthly = CashflowInsights.monthly(txs)
            insights = InvestmentInsights()
            stats = insights.stats(holdings)
            gap_report = GapDetector(self.store).run(accounts, holdings, txs, recurring, persist=False)

            return {
                "accounts": accounts,
                "holdings": holdings,
                "transactions": txs,
                "recurring": recurring,
                "networth": networth,
                "monthly_cashflow": monthly,
                "portfolio_stats": stats,
                "gap_requests": [r.to_storage_dict() for r in gap_report.requests],
            }
        except Exception as exc:
            raise UpdateFailed(f"Monarch refresh failed: {exc}") from exc
