"""Switches that change a stored watch setting."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZteKidsConfigEntry
from .api import ZteKidsError
from .const import CONFIG_DO_NOT_DISTURB, CONFIG_SPORTS
from .entity import ZteKidsEntity


@dataclass(frozen=True, slots=True)
class ZteKidsSwitchDescription:
    """One on/off setting saved with a config type."""

    key: str
    translation_key: str
    config_type: int


SWITCHES = (
    ZteKidsSwitchDescription("sports", "sports", CONFIG_SPORTS),
    ZteKidsSwitchDescription("do_not_disturb", "do_not_disturb", CONFIG_DO_NOT_DISTURB),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZteKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZteKidsSwitch(coordinator, device, description)
        for device in coordinator.devices
        for description in SWITCHES
    )


class ZteKidsSwitch(ZteKidsEntity, SwitchEntity):
    """Turn one stored watch setting on or off."""

    def __init__(self, coordinator, device: dict[str, str], description: ZteKidsSwitchDescription) -> None:
        super().__init__(coordinator, device, description.key)
        self._description = description
        self._attr_translation_key = description.translation_key

    @property
    def is_on(self) -> bool | None:
        value = self._watch.get(self._description.key)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        try:
            await self.coordinator.async_save_config(
                self._imei,
                config_type=self._description.config_type,
                status=1 if enabled else 0,
                state_key=self._description.key,
                state_value=enabled,
            )
        except ZteKidsError as err:
            raise HomeAssistantError(str(err)) from err
