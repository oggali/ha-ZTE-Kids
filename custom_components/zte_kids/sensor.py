"""Sensors for stored ZTE Kids watch state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZteKidsConfigEntry
from .entity import ZteKidsEntity

_STEPS = "steps"
_KCAL = "kcal"
_BPM = "bpm"


@dataclass(frozen=True, slots=True)
class ZteKidsSensorDescription:
    """One sensor exposed for every watch."""

    key: str
    translation_key: str
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    value: Callable[[dict[str, Any]], Any] | None = None
    attributes: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _count(key: str) -> Callable[[dict[str, Any]], int | None]:
    def read(watch: dict[str, Any]) -> int | None:
        items = watch.get(key)
        if items is None:
            return None
        return len(items)

    return read


def _list_attr(key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def read(watch: dict[str, Any]) -> dict[str, Any]:
        return {key: watch.get(key) or []}

    return read


SENSORS: tuple[ZteKidsSensorDescription, ...] = (
    ZteKidsSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes=lambda watch: {
            "updated": watch.get("battery_updated"),
            "low_battery_alert": watch.get("battery_switch"),
            "long_life_mode": watch.get("long_life_mode"),
            "location_mode": watch.get("location_mode"),
        },
    ),
    ZteKidsSensorDescription(
        key="steps",
        translation_key="steps",
        unit=_STEPS,
        state_class=SensorStateClass.MEASUREMENT,
        attributes=lambda watch: {
            "goal": watch.get("step_goal"),
            "week_steps": watch.get("week_steps"),
            "week_distance": watch.get("week_distance"),
            "week_calories": watch.get("week_calories"),
        },
    ),
    ZteKidsSensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ZteKidsSensorDescription(
        key="calories",
        translation_key="calories",
        unit=_KCAL,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ZteKidsSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        unit=_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        attributes=lambda watch: {"updated": watch.get("heart_rate_at")},
    ),
    ZteKidsSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        attributes=lambda watch: {"updated": watch.get("temperature_at")},
    ),
    ZteKidsSensorDescription(
        key="wifi",
        translation_key="wifi",
        value=_count("wifi"),
        attributes=_list_attr("wifi"),
    ),
    ZteKidsSensorDescription(
        key="safe_zones",
        translation_key="safe_zones",
        value=_count("safe_zones"),
        attributes=_list_attr("safe_zones"),
    ),
    ZteKidsSensorDescription(
        key="places",
        translation_key="places",
        value=_count("places"),
        attributes=_list_attr("places"),
    ),
    ZteKidsSensorDescription(
        key="reminders",
        translation_key="reminders",
        value=_count("reminders"),
        attributes=_list_attr("reminders"),
    ),
    ZteKidsSensorDescription(
        key="sos",
        translation_key="sos",
        value=_count("sos"),
        attributes=_list_attr("sos"),
    ),
    ZteKidsSensorDescription(
        key="contacts",
        translation_key="contacts",
        value=_count("contacts"),
        attributes=_list_attr("contacts"),
    ),
    ZteKidsSensorDescription(
        key="calls",
        translation_key="calls",
        value=_count("calls"),
        attributes=_list_attr("calls"),
    ),
    ZteKidsSensorDescription(
        key="messages",
        translation_key="messages",
        value=_count("messages"),
        attributes=_list_attr("messages"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZteKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZteKidsSensor(coordinator, device, description)
        for device in coordinator.devices
        for description in SENSORS
    )


class ZteKidsSensor(ZteKidsEntity, SensorEntity):
    """One stored value from the parent API."""

    def __init__(self, coordinator, device: dict[str, str], description: ZteKidsSensorDescription) -> None:
        super().__init__(coordinator, device, description.key)
        self._description = description
        self._attr_translation_key = description.translation_key
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.unit
        self._attr_state_class = description.state_class

    @property
    def native_value(self) -> Any:
        watch = self._watch
        description = self._description
        if description.value is not None:
            return description.value(watch)
        value = watch.get(description.key)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        description = self._description
        if description.attributes is None:
            return {}
        return description.attributes(self._watch)
