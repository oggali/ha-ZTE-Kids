"""Online state for a ZTE Kids watch."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZteKidsConfigEntry
from .entity import ZteKidsEntity


# Stored on/off flags. The parent app writes these with setting types that are not
# visible as a single number, so they stay read-only here.
_FLAG_SENSORS = (
    ("long_life_mode", "long_life_mode"),
    ("battery_switch", "low_battery_alert"),
    ("call_whitelist", "call_whitelist"),
    ("position_reports", "position_reports"),
    ("sms_filter", "sms_filter"),
    ("auto_answer", "auto_answer"),
    ("scheduled_power_off", "scheduled_power_off"),
    ("app_install", "app_install"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZteKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for device in coordinator.devices:
        entities.append(ZteKidsOnlineSensor(coordinator, device))
        entities.extend(ZteKidsFlagSensor(coordinator, device, key, translation) for key, translation in _FLAG_SENSORS)
    async_add_entities(entities)


class ZteKidsOnlineSensor(ZteKidsEntity, BinarySensorEntity):
    """Whether the watch is connected to the parent service."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(self, coordinator, device: dict[str, str]) -> None:
        super().__init__(coordinator, device, "online")

    @property
    def is_on(self) -> bool | None:
        online = self._watch.get("online")
        if online is None:
            return None
        return bool(online)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        watch = self._watch
        return {"model": watch.get("model"), "phone": watch.get("phone")}


class ZteKidsFlagSensor(ZteKidsEntity, BinarySensorEntity):
    """A stored on/off flag that this integration does not change."""

    def __init__(self, coordinator, device: dict[str, str], key: str, translation_key: str) -> None:
        super().__init__(coordinator, device, key)
        self._attr_translation_key = translation_key

    @property
    def is_on(self) -> bool | None:
        value = self._watch.get(self._key)
        if value is None:
            return None
        return bool(value)
