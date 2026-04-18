"""DataUpdateCoordinator for the Monarch Insights integration.

Responsibilities:
  * Restore the Monarch session from the config entry (token stored there by the
    config flow) — we never require an on-disk session for HA runtime.
  * Pull accounts + holdings + 180 days of transactions + recurring streams on each
    refresh tick.
  * Run the insight pipeline (net worth, cashflow, portfolio stats, gap detector).
  * Expose the result via ``coordinator.data`` so sensors can bind to specific fields.

Errors during refresh are wrapped in :class:`UpdateFailed` so HA handles retry + the
integration entry goes into ``setup_retry`` rather than silently going dark.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth, Session
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

TRANSACTION_WINDOW_DAYS = 180


class MonarchInsightsCoordinator(DataUpdateCoordinator):
    """Orchestrates periodic refreshes + insight evaluation for a single HA entry."""

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

    def _build_auth(self) -> MonarchAuth:
        """Reconstitute ``MonarchAuth`` from the config entry's stored token.

        The config flow persisted ``token`` and ``device_uuid`` into ``entry.data``; we
        hand those directly to a fresh :class:`MonarchAuth` instance rather than
        touching the encrypted session file on disk. This keeps HA refreshes working
        even when the user hasn't run the CLI ``auth login`` command on the host.
        """
        auth = MonarchAuth(device_uuid=self.entry.data.get("device_uuid"))
        token = self.entry.data.get("token")
        if not token:
            raise UpdateFailed(
                "Monarch token missing from config entry — remove and re-add the integration."
            )
        auth.session = Session(
            token=token,
            device_uuid=self.entry.data.get("device_uuid") or auth.device_uuid,
            user_email=self.entry.data.get("email"),
        )
        return auth

    async def _async_update_data(self) -> dict[str, Any]:
        """Single tick: pull fresh data, compute insights, return the combined payload."""
        try:
            auth = self._build_auth()
            async with MonarchClient(auth) as client:
                accounts = await client.get_accounts()
                holdings = await client.get_holdings()

                # 180-day transaction window keeps memory bounded. Callers that need
                # more history can extend the cache with a separate, larger sync.
                start_date = date.today() - timedelta(days=TRANSACTION_WINDOW_DAYS)
                txs = [tx async for tx in client.iter_transactions(start_date=start_date)]
                recurring = await client.get_recurring()

            networth = NetWorthInsights.snapshot(accounts)
            monthly = CashflowInsights.monthly(txs)
            invest = InvestmentInsights()
            portfolio_stats = invest.stats(holdings)
            gap_report = GapDetector(self.store).run(
                accounts, holdings, txs, recurring, persist=False
            )

            return {
                "accounts": accounts,
                "holdings": holdings,
                "transactions": txs,
                "recurring": recurring,
                "networth": networth,
                "monthly_cashflow": monthly,
                "portfolio_stats": portfolio_stats,
                "gap_requests": [r.to_storage_dict() for r in gap_report.requests],
            }
        except UpdateFailed:
            raise
        except Exception as exc:
            raise UpdateFailed(f"Monarch refresh failed: {exc}") from exc
