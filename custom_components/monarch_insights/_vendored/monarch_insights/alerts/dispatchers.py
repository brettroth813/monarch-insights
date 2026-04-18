"""Alert dispatchers — where do alerts go?

Each dispatcher implements the :class:`AlertDispatcher` protocol. Dispatchers are
deliberately independent so that a failure in one (HA REST down, SQLite locked) does
not block the others; the engine logs and continues. Callers pick their fan-out list
based on deployment context (daemon uses log+store+HA; tests use log only).
"""

from __future__ import annotations

import json
from typing import Protocol

import aiohttp

from monarch_insights.alerts.engine import Alert
from monarch_insights.observability import get_logger
from monarch_insights.storage.cache import MonarchCache

log = get_logger(__name__)


class AlertDispatcher(Protocol):
    async def send(self, alert: Alert) -> None: ...


class LogDispatcher:
    """Logs to stdout — handy for development."""

    async def send(self, alert: Alert) -> None:
        log.info(
            "[%s] %s — %s | %s",
            alert.severity.value.upper(),
            alert.kind,
            alert.title,
            alert.message,
        )


class StoreDispatcher:
    """Persists alerts to the local cache so HA can query history."""

    def __init__(self, cache: MonarchCache) -> None:
        self.cache = cache

    async def send(self, alert: Alert) -> None:
        self.cache.upsert_entity(
            entity_type="alert",
            entity_id=alert.id,
            payload={
                "kind": alert.kind,
                "title": alert.title,
                "message": alert.message,
                "severity": alert.severity.value,
                "detail": alert.detail,
                "suggested_action": alert.suggested_action,
                "created_at": alert.created_at.isoformat(),
            },
        )


class HassNotifyDispatcher:
    """Posts to Home Assistant's ``notify`` REST service.

    Compatible with ``mobile_app_<device>``, ``persistent_notification``, slack/email
    integrations registered in HA. The HA REST API expects a long-lived token in
    ``Authorization``.
    """

    def __init__(self, base_url: str, token: str, service: str = "notify.persistent_notification") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.service = service  # e.g. "notify.mobile_app_brett_iphone"

    async def send(self, alert: Alert) -> None:
        domain, _, name = self.service.partition(".")
        url = f"{self.base_url}/api/services/{domain}/{name}"
        body = {
            "title": alert.title,
            "message": alert.message,
            "data": {
                "tag": alert.kind,
                "group": "monarch-insights",
                "severity": alert.severity.value,
                "detail": alert.detail,
                "suggested_action": alert.suggested_action,
            },
        }
        async with aiohttp.ClientSession() as http:
            async with http.post(
                url,
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                data=json.dumps(body),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"HA notify failed: {resp.status} {text}")
