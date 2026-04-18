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
    def __init__(self, coordinator, payload, kind: str) -> None:
        super().__init__(coordinator)
        self._payload = payload
        self._kind = kind
        self._attr_name = f"Monarch {payload.name}"
        self._attr_unique_id = payload.unique_id or f"monarch_{kind}_{payload.name.lower().replace(' ', '_')}"
        self._attr_native_unit_of_measurement = payload.unit_of_measurement
        self._attr_icon = payload.icon
        self._attr_device_class = payload.device_class
        self._attr_extra_state_attributes = payload.attributes or {}

    @property
    def native_value(self):
        return self._payload.state
