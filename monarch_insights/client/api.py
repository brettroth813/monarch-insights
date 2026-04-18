"""Thin async GraphQL client over Monarch Money.

We deliberately avoid coupling to ``gql`` here — Monarch's API is a single endpoint with
JSON-encoded operations, so a direct ``aiohttp.post`` keeps the dependency surface small
and the retry logic easy to inspect.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from typing import Any, Mapping

import aiohttp
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from monarch_insights.client import queries as Q
from monarch_insights.client.auth import DEFAULT_BASE_URL, DEFAULT_HEADERS, MonarchAuth
from monarch_insights.client.exceptions import (
    MonarchAuthError,
    MonarchError,
    MonarchNotFound,
    MonarchRateLimited,
    MonarchSchemaDrift,
    MonarchTimeout,
)
from monarch_insights.models import (
    Account,
    Budget,
    Category,
    CategoryGroup,
    Goal,
    Holding,
    RecurringStream,
    Tag,
    Transaction,
)
from monarch_insights.observability import EventLog, get_logger

log = get_logger(__name__)


class MonarchClient:
    """High-level client. Owns a single ``aiohttp.ClientSession`` once started."""

    def __init__(
        self,
        auth: MonarchAuth | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.auth = auth or MonarchAuth(base_url=base_url)
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._http: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------ lifecycle

    async def __aenter__(self) -> MonarchClient:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._http is None:
            self._http = aiohttp.ClientSession(timeout=self.timeout)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.close()
            self._http = None

    # ------------------------------------------------------------------ low-level

    def _headers(self) -> dict[str, str]:
        if self.auth.session is None:
            self.auth.load()
        if self.auth.session is None:
            raise MonarchAuthError("No active session — call MonarchAuth.login() first")
        h = dict(DEFAULT_HEADERS)
        h["Authorization"] = f"Token {self.auth.session.token}"
        h["device-uuid"] = self.auth.session.device_uuid
        return h

    async def execute(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        *,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Run a GraphQL operation with retry + classification of common error shapes.

        Retries kick in for :class:`MonarchRateLimited` and :class:`MonarchTimeout` only.
        Every attempt is timed and logged; the final success or failure is recorded in
        the event log so the CLI can show "last successful sync for ``GetAccounts``".
        """
        if self._http is None:
            await self.start()
        op_name = operation_name or "<anonymous>"
        body = {
            "query": query,
            "variables": dict(variables or {}),
        }
        if operation_name:
            body["operationName"] = operation_name

        start = time.perf_counter()
        attempt_count = 0
        last_error: Exception | None = None

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception_type((MonarchRateLimited, MonarchTimeout)),
            reraise=True,
        ):
            with attempt:
                attempt_count += 1
                try:
                    result = await self._execute_once(body)
                except Exception as exc:  # noqa: BLE001 — logged + re-raised by tenacity
                    last_error = exc
                    log.warning(
                        "client.execute.attempt_failed",
                        extra={
                            "operation": op_name,
                            "attempt": attempt_count,
                            "error": repr(exc),
                        },
                    )
                    raise
                elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
                log.info(
                    "client.execute.ok",
                    extra={
                        "operation": op_name,
                        "attempts": attempt_count,
                        "elapsed_ms": elapsed_ms,
                    },
                )
                return result

        # tenacity exhausted; ``last_error`` is the final exception we saw.
        log.error(
            "client.execute.exhausted",
            extra={
                "operation": op_name,
                "attempts": attempt_count,
                "error": repr(last_error),
            },
        )
        raise MonarchError("execute() exhausted retries without raising")

    async def _execute_once(self, body: dict[str, Any]) -> dict[str, Any]:
        assert self._http is not None
        url = f"{self.base_url}/graphql"
        try:
            async with self._http.post(url, json=body, headers=self._headers()) as resp:
                text = await resp.text()
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1") or 1)
                    raise MonarchRateLimited(retry_after=retry_after)
                if resp.status in (401, 403):
                    raise MonarchAuthError(
                        f"GraphQL auth failed: {resp.status}", payload=text
                    )
                if resp.status >= 500:
                    raise MonarchError(
                        f"Monarch server error: {resp.status}", payload=text
                    )
                payload = await resp.json(content_type=None)
        except asyncio.TimeoutError as exc:
            raise MonarchTimeout("GraphQL request timed out") from exc

        if "errors" in payload and payload["errors"]:
            self._raise_for_errors(body.get("operationName") or "<anonymous>", payload)
        return payload.get("data") or {}

    @staticmethod
    def _raise_for_errors(op: str, payload: dict[str, Any]) -> None:
        errors = payload.get("errors") or []
        first = errors[0] if errors else {}
        msg = (first.get("message") or "Unknown GraphQL error").lower()
        if "rate" in msg and "limit" in msg:
            raise MonarchRateLimited(payload=errors)
        if "not found" in msg:
            raise MonarchNotFound(first.get("message") or "Resource not found", payload=errors)
        if "unauth" in msg or "permission" in msg:
            raise MonarchAuthError(first.get("message") or "Unauthorized", payload=errors)
        if "unknown field" in msg or "cannot query field" in msg:
            raise MonarchSchemaDrift(op, first.get("message") or "Schema drift", payload=errors)
        raise MonarchError(f"GraphQL error in {op}: {first.get('message')}", payload=errors)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _coerce_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = data.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict) and "results" in value:
            return value["results"]
        if isinstance(value, dict) and "edges" in value:
            return [edge["node"] for edge in value["edges"]]
        raise MonarchSchemaDrift("<coerce_list>", f"Unexpected shape for {key}: {type(value)}")

    @staticmethod
    def _flatten_account_payload(raw: dict[str, Any]) -> dict[str, Any]:
        """Account payloads use nested ``type`` and ``subtype`` objects; flatten for our model."""
        out = dict(raw)
        if isinstance(raw.get("type"), dict):
            out["type"] = raw["type"].get("name") or raw["type"].get("group")
        if isinstance(raw.get("subtype"), dict):
            out["subtype"] = raw["subtype"].get("name") or "other"
        return out

    # ------------------------------------------------------------------ accounts

    async def get_me(self) -> dict[str, Any]:
        data = await self.execute(Q.ME, operation_name="Common_GetMe")
        return data.get("me") or {}

    async def get_subscription(self) -> dict[str, Any]:
        data = await self.execute(Q.GET_SUBSCRIPTION, operation_name="GetSubscriptionDetails")
        return data.get("subscription") or {}

    async def get_accounts(self) -> list[Account]:
        data = await self.execute(Q.GET_ACCOUNTS, operation_name="GetAccounts")
        raw = self._coerce_list(data, "accounts")
        return [Account.model_validate(self._flatten_account_payload(r)) for r in raw]

    async def get_account_history(
        self, account_id: str, start_date: date | None = None
    ) -> list[dict[str, Any]]:
        data = await self.execute(
            Q.GET_ACCOUNT_HISTORY,
            {"id": account_id, "startDate": start_date.isoformat() if start_date else None},
            operation_name="AccountDetails_getAccount",
        )
        account = data.get("account") or {}
        return account.get("historicalBalances") or []

    async def get_recent_balances(self, start_date: date) -> dict[str, list[Any]]:
        data = await self.execute(
            Q.GET_RECENT_BALANCES,
            {"startDate": start_date.isoformat()},
            operation_name="GetAccountRecentBalances",
        )
        out: dict[str, list[Any]] = {}
        for acct in data.get("accounts") or []:
            out[acct["id"]] = acct.get("recentBalances") or []
        return out

    async def get_aggregate_snapshots(
        self,
        start_date: date,
        end_date: date | None = None,
        account_type: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"startDate": start_date.isoformat()}
        if end_date:
            filters["endDate"] = end_date.isoformat()
        if account_type:
            filters["accountType"] = account_type
        data = await self.execute(
            Q.GET_AGGREGATE_SNAPSHOTS,
            {"filters": filters},
            operation_name="GetAggregateSnapshots",
        )
        return data.get("aggregateSnapshots") or []

    # ------------------------------------------------------------------ transactions

    async def get_transactions(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        category_ids: list[str] | None = None,
        account_ids: list[str] | None = None,
        merchant_ids: list[str] | None = None,
        tag_ids: list[str] | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Transaction]:
        filters: dict[str, Any] = {}
        if start_date:
            filters["startDate"] = start_date.isoformat()
        if end_date:
            filters["endDate"] = end_date.isoformat()
        if category_ids:
            filters["categories"] = category_ids
        if account_ids:
            filters["accounts"] = account_ids
        if merchant_ids:
            filters["merchants"] = merchant_ids
        if tag_ids:
            filters["tags"] = tag_ids
        if search:
            filters["search"] = search

        data = await self.execute(
            Q.GET_TRANSACTIONS,
            {
                "filters": filters,
                "limit": limit,
                "offset": offset,
                "orderBy": "DATE_DESC",
            },
            operation_name="GetTransactionsList",
        )
        results = (data.get("allTransactions") or {}).get("results") or []
        return [Transaction.model_validate(self._flatten_transaction(t)) for t in results]

    async def iter_transactions(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        page_size: int = 200,
        **filters: Any,
    ):
        """Async generator that paginates ``allTransactions`` without loading everything."""
        offset = 0
        while True:
            page = await self.get_transactions(
                start_date=start_date,
                end_date=end_date,
                limit=page_size,
                offset=offset,
                **filters,
            )
            if not page:
                return
            for tx in page:
                yield tx
            if len(page) < page_size:
                return
            offset += page_size

    @staticmethod
    def _flatten_transaction(raw: dict[str, Any]) -> dict[str, Any]:
        out = dict(raw)
        if account := raw.get("account"):
            out["accountId"] = account.get("id")
            out["accountDisplayName"] = account.get("displayName")
        if cat := raw.get("category"):
            out["categoryId"] = cat.get("id")
            out["categoryName"] = cat.get("name")
            if grp := cat.get("group"):
                out["categoryGroupId"] = grp.get("id")
        if mer := raw.get("merchant"):
            out["merchantId"] = mer.get("id")
            out["merchantName"] = mer.get("name")
        tags = raw.get("tags") or []
        out["tagIds"] = [t.get("id") for t in tags if t.get("id")]
        out["tagNames"] = [t.get("name") for t in tags if t.get("name")]
        return out

    # ------------------------------------------------------------------ categories & tags

    async def get_categories(self) -> list[Category]:
        data = await self.execute(Q.GET_CATEGORIES, operation_name="GetCategories")
        out: list[Category] = []
        for raw in data.get("categories") or []:
            grp = raw.get("group") or {}
            out.append(
                Category.model_validate(
                    {
                        **raw,
                        "groupId": grp.get("id"),
                        "groupName": grp.get("name"),
                        "groupType": grp.get("type"),
                    }
                )
            )
        return out

    async def get_category_groups(self) -> list[CategoryGroup]:
        data = await self.execute(Q.GET_CATEGORY_GROUPS, operation_name="ManageGetCategoryGroups")
        return [CategoryGroup.model_validate(g) for g in data.get("categoryGroups") or []]

    async def get_tags(self) -> list[Tag]:
        data = await self.execute(Q.GET_TAGS, operation_name="GetHouseholdTransactionTags")
        return [Tag.model_validate(t) for t in data.get("householdTransactionTags") or []]

    # ------------------------------------------------------------------ holdings

    async def get_holdings(self, account_ids: list[str] | None = None) -> list[Holding]:
        data = await self.execute(
            Q.GET_HOLDINGS,
            {"accountIds": account_ids},
            operation_name="Web_GetHoldings",
        )
        portfolio = data.get("portfolio") or {}
        edges = (portfolio.get("aggregateHoldings") or {}).get("edges") or []
        out: list[Holding] = []
        for edge in edges:
            node = edge.get("node") or {}
            security = node.get("security") or {}
            for h in node.get("holdings") or []:
                acct = h.get("account") or {}
                out.append(
                    Holding.model_validate(
                        {
                            **h,
                            "accountId": acct.get("id"),
                            "ticker": h.get("ticker") or security.get("ticker"),
                            "name": h.get("name") or security.get("name"),
                            "securityId": security.get("id"),
                            "marketValue": h.get("value"),
                        }
                    )
                )
        return out

    # ------------------------------------------------------------------ cashflow & budgets

    async def get_cashflow(
        self,
        start_date: date,
        end_date: date,
        account_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        if account_ids:
            filters["accounts"] = account_ids
        return await self.execute(
            Q.GET_CASHFLOW, {"filters": filters}, operation_name="Web_GetCashFlowPage"
        )

    async def get_budgets(
        self,
        start_date: date,
        end_date: date,
    ) -> list[Budget]:
        data = await self.execute(
            Q.GET_BUDGETS,
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "useLegacyGoals": False,
            },
            operation_name="Common_GetJointPlanningData",
        )
        budget_data = data.get("budgetData") or {}
        return self._normalize_budgets(start_date, end_date, budget_data)

    @staticmethod
    def _normalize_budgets(
        start: date, end: date, raw: dict[str, Any]
    ) -> list[Budget]:
        """Roll up Monarch's per-month-per-category structure into one Budget per month."""
        items_by_month: dict[str, list[dict[str, Any]]] = {}
        for entry in raw.get("monthlyAmountsByCategory") or []:
            cat = entry.get("category") or {}
            grp = cat.get("group") or {}
            for ma in entry.get("monthlyAmounts") or []:
                month = ma.get("month")
                if not month:
                    continue
                items_by_month.setdefault(month, []).append(
                    {
                        "id": f"{cat.get('id')}-{month}",
                        "categoryId": cat.get("id"),
                        "categoryName": cat.get("name"),
                        "groupId": grp.get("id"),
                        "groupName": grp.get("name"),
                        "plannedCashFlowAmount": ma.get("plannedCashFlowAmount"),
                        "actualAmount": ma.get("actualAmount"),
                        "remainingAmount": ma.get("remainingAmount"),
                        "rolloverAmount": ma.get("previousMonthRolloverAmount"),
                    }
                )

        totals_by_month = {t["month"]: t for t in raw.get("totalsByMonth") or []}

        budgets: list[Budget] = []
        for month, items in sorted(items_by_month.items()):
            t = totals_by_month.get(month, {})
            budgets.append(
                Budget.model_validate(
                    {
                        "startDate": month,
                        "endDate": month,  # Monarch returns first-of-month identifiers
                        "items": items,
                        "totalPlannedIncome": (t.get("totalIncome") or {}).get("plannedAmount") or 0,
                        "totalActualIncome": (t.get("totalIncome") or {}).get("actualAmount") or 0,
                        "totalPlannedExpense": (t.get("totalExpenses") or {}).get("plannedAmount") or 0,
                        "totalActualExpense": (t.get("totalExpenses") or {}).get("actualAmount") or 0,
                    }
                )
            )
        return budgets

    # ------------------------------------------------------------------ recurring & goals

    async def get_recurring(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[RecurringStream]:
        start = start_date or date.today()
        end = end_date or (start + timedelta(days=60))
        data = await self.execute(
            Q.GET_RECURRING,
            {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "filters": {},
            },
            operation_name="Web_GetUpcomingRecurringTransactionItems",
        )
        out: dict[str, dict[str, Any]] = {}
        for item in data.get("recurringTransactionItems") or []:
            stream = item.get("stream") or {}
            sid = stream.get("id")
            if not sid:
                continue
            existing = out.setdefault(
                sid,
                {
                    "id": sid,
                    "name": stream.get("name") or (stream.get("merchant") or {}).get("name"),
                    "merchantId": (stream.get("merchant") or {}).get("id"),
                    "frequency": (stream.get("frequency") or "unknown").lower(),
                    "averageAmount": stream.get("amount"),
                    "isActive": True,
                    "isIncome": float(stream.get("amount") or 0) > 0,
                },
            )
            if item.get("date") and not item.get("isPast"):
                if existing.get("nextDate") in (None, "") or item["date"] < existing["nextDate"]:
                    existing["nextDate"] = item["date"]
                    existing["nextAmount"] = item.get("amount")
            if item.get("date") and item.get("isPast"):
                existing["lastDate"] = item["date"]
            if cat := item.get("category"):
                existing["categoryId"] = cat.get("id")
                existing["categoryName"] = cat.get("name")
            if acct := item.get("account"):
                existing["accountId"] = acct.get("id")
                existing["accountName"] = acct.get("displayName")
        return [RecurringStream.model_validate(v) for v in out.values()]

    async def get_goals(self) -> list[Goal]:
        data = await self.execute(Q.GET_GOALS, operation_name="Web_GetGoals")
        out: list[Goal] = []
        for g in data.get("goalsV2") or []:
            allocations = g.get("accountAllocations") or []
            out.append(
                Goal.model_validate(
                    {
                        **g,
                        "isComplete": g.get("isCompleted", False),
                        "linkedAccountIds": [
                            (a.get("account") or {}).get("id")
                            for a in allocations
                            if (a.get("account") or {}).get("id")
                        ],
                    }
                )
            )
        return out

    # ------------------------------------------------------------------ institutions

    async def get_institutions(self) -> list[dict[str, Any]]:
        data = await self.execute(Q.GET_INSTITUTIONS, operation_name="Web_GetInstitutionSettings")
        return data.get("credentials") or []
