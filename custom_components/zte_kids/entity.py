"""Shared device info for ZTE Kids entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZteKidsCoordinator


def watch_device_info(imei: str, name: str, model: str | None = None) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, imei)},
        name=name,
        manufacturer="ZTE",
        model=model or "Kids watch",
    )


class ZteKidsEntity(CoordinatorEntity[ZteKidsCoordinator]):
    """One watch, named from the device plus a translation key."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZteKidsCoordinator, device: dict[str, str], key: str) -> None:
        super().__init__(coordinator)
        self._imei = device["imei"]
        self._key = key
        self._attr_unique_id = f"{self._imei}_{key}"
        self._attr_device_info = watch_device_info(self._imei, device.get("name") or self._imei)

    @property
    def _watch(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get(self._imei) or {}

    def _handle_coordinator_update(self) -> None:
        watch = self._watch
        name = watch.get("name") or self._imei
        self._attr_device_info = watch_device_info(self._imei, name, watch.get("model"))
        super()._handle_coordinator_update()
