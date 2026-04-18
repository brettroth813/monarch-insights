"""Helpers around HA push-notifications for finance events."""

from __future__ import annotations

from monarch_insights.alerts.dispatchers import HassNotifyDispatcher
from monarch_insights.alerts.engine import Alert


class HassNotifier:
    """Routes alerts to mobile / persistent / both based on severity."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        mobile_service: str = "notify.persistent_notification",
        critical_service: str | None = None,
    ) -> None:
        self.persistent = HassNotifyDispatcher(base_url, token, "notify.persistent_notification")
        self.mobile = HassNotifyDispatcher(base_url, token, mobile_service)
        self.critical = (
            HassNotifyDispatcher(base_url, token, critical_service) if critical_service else None
        )

    async def send(self, alert: Alert) -> None:
        await self.persistent.send(alert)
        if alert.severity.value in ("warn", "critical"):
            await self.mobile.send(alert)
        if alert.severity.value == "critical" and self.critical:
            await self.critical.send(alert)
