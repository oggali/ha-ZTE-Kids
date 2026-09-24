"""Device tracker for a ZTE Kids watch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ZteKidsConfigEntry
from .const import DOMAIN
from .coordinator import ZteKidsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZteKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ZteKidsTracker(coordinator, device) for device in coordinator.devices)


class ZteKidsTracker(CoordinatorEntity[ZteKidsCoordinator], TrackerEntity):
    """Last known position of one watch."""

    _attr_has_entity_name = True
    _attr_translation_key = "watch"
    _attr_name = None

    def __init__(self, coordinator: ZteKidsCoordinator, device: dict[str, str]) -> None:
        super().__init__(coordinator)
        self._imei = device["imei"]
        self._device_name = device.get("name") or device["imei"]
        self._attr_unique_id = self._imei
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._imei)},
            name=self._device_name,
            manufacturer="ZTE",
            model="Kids watch",
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        point = self._point
        if point is None:
            return None
        return point.get("lat")

    @property
    def longitude(self) -> float | None:
        point = self._point
        if point is None:
            return None
        return point.get("lon")

    @property
    def location_accuracy(self) -> int:
        point = self._point or {}
        radius = point.get("accuracy")
        if radius is None:
            return 0
        return int(radius)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        point = self._point or {}
        return {
            "imei": self._imei,
            "address": point.get("address"),
            "location_type": point.get("loc_type"),
            "gps_timestamp": point.get("timestamp"),
        }

    @property
    def _point(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._imei)

    @callback
    def _handle_coordinator_update(self) -> None:
        point = self._point
        if point and point.get("name"):
            self._device_name = point["name"]
        super()._handle_coordinator_update()
