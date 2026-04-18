"""Sensor entities exposing Monarch Insights data."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from monarch_insights.ha.sensors import SensorProducer

from .const import DOMAIN
from .coordinator import MonarchInsightsCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MonarchInsightsCoordinator = hass.data[DOMAIN][entry.entry_id]
    producer = SensorProducer()

    entities: list[SensorEntity] = []

    if coordinator.data and (networth := coordinator.data.get("networth")):
        for payload in producer.net_worth(networth):
            entities.append(MonarchSensor(coordinator, payload, "networth"))

    if coordinator.data and (accounts := coordinator.data.get("accounts")):
        for payload in producer.per_account(accounts):
            entities.append(MonarchSensor(coordinator, payload, "account"))

    if coordinator.data and (stats := coordinator.data.get("portfolio_stats")):
        for payload in producer.portfolio_stats(stats):
            entities.append(MonarchSensor(coordinator, payload, "portfolio"))

    if coordinator.data and (gaps := coordinator.data.get("gap_requests")):
        for payload in producer.alerts(gaps):
            entities.append(MonarchSensor(coordinator, payload, "gaps"))

    async_add_entities(entities)


class MonarchSensor(CoordinatorEntity, SensorEntity):
    """One Monarch-derived value surfaced as an HA sensor.

    We copy the payload's ``attributes`` at construction time and then augment
    them on each coordinator tick with ``data_source`` + ``cache_last_import_at``
    so operators can see at a glance whether the figures came from Monarch's
    live API or from a CSV import (and how stale that import is).
    """

    def __init__(self, coordinator, payload, kind: str) -> None:
        super().__init__(coordinator)
        self._payload = payload
        self._kind = kind
        self._attr_name = f"Monarch {payload.name}"
        self._attr_unique_id = payload.unique_id or f"monarch_{kind}_{payload.name.lower().replace(' ', '_')}"
        self._attr_native_unit_of_measurement = payload.unit_of_measurement
        self._attr_icon = payload.icon
        self._attr_device_class = payload.device_class

    @property
    def native_value(self):
        return self._payload.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Merge payload attrs with coordinator-level provenance."""
        base = dict(self._payload.attributes or {})
        data = self.coordinator.data or {}
        base["data_source"] = data.get("data_source")
        base["cache_last_import_at"] = data.get("cache_last_import_at")
        base["last_refresh_at"] = data.get("last_refresh_at")
        return base
