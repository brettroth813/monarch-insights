"""Integration-ish tests for the MonarchClient using an aiohttp test server.

These don't talk to Monarch; they stand up a local aiohttp app that mimics the GraphQL
endpoint's response shape, so we exercise:

* Auth header construction (``Authorization: Token …``, ``device-uuid`` passed through).
* Retry behaviour on 429 with ``Retry-After``.
* Schema-drift classification on real response bodies.
* Pagination via :meth:`MonarchClient.iter_transactions`.
* 5xx triggers retry + raises ``MonarchError`` when the max is hit.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from aiohttp import web

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth, Session
from monarch_insights.client.exceptions import (
    MonarchError,
    MonarchRateLimited,
    MonarchSchemaDrift,
)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


async def _make_client(server, auth_token: str = "test-token") -> MonarchClient:
    auth = MonarchAuth(base_url=str(server.make_url("")))
    auth.session = Session(token=auth_token, device_uuid="device-1", user_email="test@example.com")
    client = MonarchClient(auth, base_url=str(server.make_url("")), max_retries=3, timeout=5)
    await client.start()
    return client


@pytest.fixture
async def aiohttp_server(aiohttp_server):  # pragma: no cover — fixture alias only
    return aiohttp_server


@pytest.fixture
async def graphql_server(aiohttp_server):
    """Return a server whose handlers can be overridden per-test."""
    state: dict[str, Any] = {"handler": None, "call_count": 0}

    async def _root(request):
        state["call_count"] += 1
        body = await request.json()
        handler = state["handler"]
        if handler is None:
            return web.json_response({"data": {}})
        return await handler(request, body, state)

    app = web.Application()
    app.router.add_post("/graphql", _root)
    server = await aiohttp_server(app)
    server.state = state  # type: ignore[attr-defined]
    return server


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_sends_authorization_and_device_headers(graphql_server):
    captured: dict[str, str] = {}

    async def handler(request, body, state):
        captured.update(dict(request.headers))
        return web.json_response({"data": {"accounts": []}})

    graphql_server.state["handler"] = handler
    client = await _make_client(graphql_server)
    try:
        await client.get_accounts()
    finally:
        await client.close()

    assert captured.get("Authorization") == "Token test-token"
    assert captured.get("device-uuid") == "device-1"


@pytest.mark.asyncio
async def test_client_retries_on_429_then_succeeds(graphql_server):
    async def handler(request, body, state):
        state["call_count"] = state.get("call_count", 0) + 1
        if state["call_count"] < 2:
            return web.Response(status=429, headers={"Retry-After": "0.1"})
        return web.json_response({"data": {"accounts": []}})

    graphql_server.state["handler"] = handler
    client = await _make_client(graphql_server)
    try:
        accounts = await client.get_accounts()
    finally:
        await client.close()
    assert accounts == []


@pytest.mark.asyncio
async def test_client_raises_schema_drift_on_unknown_field(graphql_server):
    async def handler(request, body, state):
        return web.json_response(
            {"errors": [{"message": "Cannot query field 'something' on type 'Foo'"}]}
        )

    graphql_server.state["handler"] = handler
    client = await _make_client(graphql_server)
    try:
        with pytest.raises(MonarchSchemaDrift):
            await client.get_accounts()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_raises_after_exhausting_retries_on_5xx(graphql_server):
    async def handler(request, body, state):
        return web.Response(status=503, text="down")

    graphql_server.state["handler"] = handler
    client = await _make_client(graphql_server)
    try:
        with pytest.raises(MonarchError):
            await client.get_accounts()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_iter_transactions_paginates_until_short_page(graphql_server):
    calls: list[dict] = []

    async def handler(request, body, state):
        calls.append(body)
        offset = body["variables"]["offset"]
        # 150 total transactions, 50 per page.
        remaining = max(0, 150 - offset)
        limit = min(body["variables"]["limit"], remaining)
        results = [
            {
                "id": f"T{offset + i}",
                "date": "2026-04-01",
                "amount": -10,
                "account": {"id": "A1", "displayName": "Chase"},
                "tags": [],
            }
            for i in range(limit)
        ]
        return web.json_response(
            {"data": {"allTransactions": {"totalCount": 150, "results": results}}}
        )

    graphql_server.state["handler"] = handler
    client = await _make_client(graphql_server)
    try:
        collected = []
        async for tx in client.iter_transactions(page_size=50):
            collected.append(tx)
    finally:
        await client.close()
    assert len(collected) == 150
    # 3 full pages + 1 short page that has 0 results -> loop exits after the third page.
    assert len(calls) >= 3
