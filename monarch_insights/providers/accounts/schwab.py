"""Charles Schwab provider — uses Schwab's official Trader API (post-TDA migration).

Auth is OAuth 2.0 with refresh-token rotation. The user must register an app at
developer.schwab.com and approve the consumer-facing OAuth flow once. We store the
refresh token alongside the Monarch session.

This is a scaffold: real network calls are stubbed because the Schwab API requires a
manual developer-account approval and a live OAuth dance. The shape and method names
match the documented endpoints so it's swap-in-able once tokens exist.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from monarch_insights.providers.accounts.base import (
    AccountSnapshot,
    StatementReference,
    TradeRecord,
)

log = logging.getLogger(__name__)
BASE = "https://api.schwabapi.com/trader/v1"


class SchwabProvider:
    name = "schwab"
    institution = "Charles Schwab"
    auth_kind = "oauth"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = access_token

    async def authenticate(self) -> None:
        """Exchange the refresh token for a fresh access token. STUBBED."""
        if not self.refresh_token:
            raise RuntimeError(
                "Schwab requires a refresh token from the OAuth bootstrap step. "
                "Run `monarch-insights schwab bootstrap` first."
            )
        # Real impl: POST https://api.schwabapi.com/v1/oauth/token
        log.info("schwab: would refresh access token")

    async def list_accounts(self) -> list[AccountSnapshot]:
        await self.authenticate()
        # Real impl: GET {BASE}/accounts/accountNumbers, then GET {BASE}/accounts
        return self._stub_accounts()

    async def list_trades(
        self, account_id: str, start: date | None = None, end: date | None = None
    ) -> list[TradeRecord]:
        await self.authenticate()
        # Real impl: GET {BASE}/accounts/{accountHash}/transactions?types=TRADE
        return []

    async def list_statements(
        self, account_id: str, since: date | None = None
    ) -> list[StatementReference]:
        # Schwab's statement endpoints are gated; usually we let the user point Monarch
        # at the same Schwab brokerage and download statements through their portal.
        return []

    # ------------------------------------------------------------------ stubs

    def _stub_accounts(self) -> list[AccountSnapshot]:
        return [
            AccountSnapshot(
                institution=self.institution,
                external_account_id="STUB-SCHWAB",
                display_name="Schwab (stub)",
                account_type="brokerage",
                balance=Decimal(0),
                as_of=datetime.utcnow(),
                currency="USD",
                extra={"stub": True},
            )
        ]
