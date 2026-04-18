"""DataUpdateCoordinator for the Monarch Insights integration.

Responsibilities:
  * Restore the Monarch session from the config entry (token stored there by the
    config flow) — no on-disk session file required at runtime.
  * Pull accounts + holdings + 180 days of transactions + recurring streams on each
    refresh tick, preferring the live Monarch API when available.
  * Fall back to the on-disk cache populated by ``monarch-insights import monarch-csv``
    when the API is unavailable (no token, WAF block, schema drift, network down).
    This is the primary data path today because Monarch's Cloudflare WAF rejects
    every non-browser HTTP client we've tested against ``/auth/login/``.
  * Run the insight pipeline (net worth, cashflow, portfolio stats, gap detector)
    against whichever dataset we landed on.
  * Expose ``data_source`` alongside the payload so sensors can surface whether
    the figures are live-API or cache-fed, and how fresh the cache is.

Forward compatibility: the API and CSV paths write to the *same* cache tables
(``entities``/``transactions``/``holdings``/``account_balances``), using the same
Pydantic dumps. Once the API path works again, both sources coexist — API rows
take precedence because they're fetched on every tick; CSV rows are held as the
fallback. No data migration needed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
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
from monarch_insights.models import Account, Holding, RecurringStream, Transaction
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

    # ------------------------------------------------------------------ auth

    def _build_auth(self) -> MonarchAuth | None:
        """Reconstitute :class:`MonarchAuth` from the config entry, or ``None``.

        Returns ``None`` when no token is stored — the caller should then use the
        cache-only path instead of attempting live API calls. We don't raise here
        because a tokenless entry is a valid operating mode (CSV-only user).
        """
        token = self.entry.data.get("token")
        if not token:
            return None
        device_uuid = self.entry.data.get("device_uuid")
        auth = MonarchAuth(device_uuid=device_uuid)
        auth.session = Session(
            token=token,
            device_uuid=device_uuid or auth.device_uuid,
            user_email=self.entry.data.get("email"),
        )
        return auth

    # ------------------------------------------------------------------ update

    async def _async_update_data(self) -> dict[str, Any]:
        """Single tick: prefer live API; fall back to cache; compute insights; return."""
        live_error: Exception | None = None
        auth = self._build_auth()

        if auth is not None:
            try:
                return await self._run_insights(*(await self._fetch_live(auth)), "api")
            except Exception as exc:  # noqa: BLE001 — logged, falls back to cache
                live_error = exc
                _LOGGER.warning(
                    "monarch_insights live API refresh failed, falling back to cache: %s",
                    exc,
                )

        cached = self._load_cache_snapshot()
        if cached is None:
            if live_error is not None:
                raise UpdateFailed(f"Live API failed ({live_error}) and cache is empty")
            raise UpdateFailed(
                "No Monarch token configured and no cached data found. "
                "Run `monarch-insights import monarch-csv` with your Monarch export."
            )
        return await self._run_insights(*cached, "cache")

    async def _fetch_live(
        self, auth: MonarchAuth
    ) -> tuple[
        list[Account], list[Holding], list[Transaction], list[RecurringStream]
    ]:
        async with MonarchClient(auth) as client:
            accounts = await client.get_accounts()
            holdings = await client.get_holdings()
            start_date = date.today() - timedelta(days=TRANSACTION_WINDOW_DAYS)
            txs = [tx async for tx in client.iter_transactions(start_date=start_date)]
            recurring = await client.get_recurring()
        return accounts, holdings, txs, recurring

    # ------------------------------------------------------------------ cache path

    def _load_cache_snapshot(
        self,
    ) -> (
        tuple[list[Account], list[Holding], list[Transaction], list[RecurringStream]]
        | None
    ):
        """Materialise model objects from the local SQLite cache.

        Returns ``None`` if the cache has no accounts — nothing to show. Empty
        transaction / holdings lists are fine; the insights layer tolerates them.
        """
        account_rows = self.cache.list_entities("account")
        if not account_rows:
            return None
        accounts = [Account.model_validate(r) for r in account_rows]

        holdings: list[Holding] = []
        try:
            with self.cache.connect() as conn:
                holding_rows = conn.execute(
                    "SELECT payload_json FROM holdings"
                ).fetchall()
            for row in holding_rows:
                try:
                    holdings.append(Holding.model_validate(json.loads(row["payload_json"])))
                except Exception as exc:  # noqa: BLE001 — one bad row shouldn't blow up
                    _LOGGER.debug("skipping malformed holding row: %s", exc)
        except sqlite3.OperationalError:
            pass  # holdings table may not exist yet on a fresh cache

        transactions: list[Transaction] = []
        try:
            with self.cache.connect() as conn:
                cutoff = (date.today() - timedelta(days=TRANSACTION_WINDOW_DAYS)).isoformat()
                tx_rows = conn.execute(
                    "SELECT payload_json FROM transactions WHERE on_date >= ?", (cutoff,)
                ).fetchall()
            for row in tx_rows:
                try:
                    transactions.append(
                        Transaction.model_validate(json.loads(row["payload_json"]))
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug("skipping malformed transaction row: %s", exc)
        except sqlite3.OperationalError:
            pass

        recurring_rows = self.cache.list_entities("recurring")
        recurring = [RecurringStream.model_validate(r) for r in recurring_rows]

        return accounts, holdings, transactions, recurring

    # ------------------------------------------------------------------ insights

    async def _run_insights(
        self,
        accounts: list[Account],
        holdings: list[Holding],
        transactions: list[Transaction],
        recurring: list[RecurringStream],
        source: str,
    ) -> dict[str, Any]:
        """Turn raw model lists into the payload HA sensors consume."""
        networth = NetWorthInsights.snapshot(accounts)
        monthly = CashflowInsights.monthly(transactions)
        invest = InvestmentInsights()
        portfolio_stats = invest.stats(holdings)
        gap_report = GapDetector(self.store).run(
            accounts, holdings, transactions, recurring, persist=False
        )
        return {
            "accounts": accounts,
            "holdings": holdings,
            "transactions": transactions,
            "recurring": recurring,
            "networth": networth,
            "monthly_cashflow": monthly,
            "portfolio_stats": portfolio_stats,
            "gap_requests": [r.to_storage_dict() for r in gap_report.requests],
            "data_source": source,
            "last_refresh_at": datetime.now(timezone.utc).isoformat(),
            "cache_last_import_at": _latest_cache_write_time(self.cache),
        }


def _latest_cache_write_time(cache: MonarchCache) -> str | None:
    """Return the ISO timestamp of the cache's most recent write, for sensor attrs."""
    try:
        with cache.connect() as conn:
            row = conn.execute(
                "SELECT MAX(last_seen_at) AS ts FROM entities"
            ).fetchone()
        ts = row["ts"] if row else None
        if not ts:
            return None
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except sqlite3.OperationalError:
        return None
