"""Optional FastAPI surface — exposes everything Monarch Insights computes over HTTP.

HA can pull from this via REST sensor or template sensors. Run with::

    uvicorn monarch_insights.ha.api:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth
from monarch_insights.gaps.detector import GapDetector
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.insights.spending import SpendingInsights
from monarch_insights.storage.cache import MonarchCache
from monarch_insights.supplements.store import SupplementStore


def _decimalize(obj: Any) -> Any:
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimalize(x) for x in obj]
    if hasattr(obj, "model_dump"):
        return _decimalize(obj.model_dump())
    if hasattr(obj, "__dict__"):
        return _decimalize(obj.__dict__)
    return obj


def create_app() -> "FastAPI":
    if FastAPI is None:
        raise RuntimeError("fastapi not installed; pip install monarch_insights[api]")

    app = FastAPI(title="Monarch Insights")
    cache = MonarchCache()
    store = SupplementStore()

    async def _client() -> MonarchClient:
        client = MonarchClient(MonarchAuth())
        await client.start()
        return client

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/accounts")
    async def get_accounts():
        client = await _client()
        try:
            accounts = await client.get_accounts()
            return JSONResponse(_decimalize([a.model_dump() for a in accounts]))
        finally:
            await client.close()

    @app.get("/networth")
    async def networth():
        client = await _client()
        try:
            accounts = await client.get_accounts()
            breakdown = NetWorthInsights.snapshot(accounts)
            return JSONResponse(_decimalize(breakdown))
        finally:
            await client.close()

    @app.get("/cashflow")
    async def cashflow(months: int = 12):
        client = await _client()
        try:
            txs = []
            async for t in client.iter_transactions(start_date=date.today() - timedelta(days=months * 32)):
                txs.append(t)
            monthly = CashflowInsights.monthly(txs, months=months)
            return JSONResponse(_decimalize([m.__dict__ for m in monthly]))
        finally:
            await client.close()

    @app.get("/spending/top")
    async def spending_top(limit: int = 10, days: int = 30):
        client = await _client()
        try:
            txs = []
            async for t in client.iter_transactions(start_date=date.today() - timedelta(days=days)):
                txs.append(t)
            return JSONResponse(
                _decimalize([
                    c.__dict__ for c in SpendingInsights.top_categories(txs, limit=limit)
                ])
            )
        finally:
            await client.close()

    @app.get("/investments")
    async def investments():
        client = await _client()
        try:
            holdings = await client.get_holdings()
            insights = InvestmentInsights()
            stats = insights.stats(holdings)
            return JSONResponse(_decimalize(stats.__dict__))
        finally:
            await client.close()

    @app.get("/gaps")
    async def gaps():
        client = await _client()
        try:
            accounts = await client.get_accounts()
            holdings = await client.get_holdings()
            txs = []
            async for t in client.iter_transactions(start_date=date.today() - timedelta(days=180)):
                txs.append(t)
            recurring = await client.get_recurring()
            report = GapDetector(store).run(accounts, holdings, txs, recurring, persist=False)
            return JSONResponse(
                _decimalize({"requests": [r.to_storage_dict() for r in report.requests]})
            )
        finally:
            await client.close()

    return app


app = create_app() if FastAPI is not None else None
