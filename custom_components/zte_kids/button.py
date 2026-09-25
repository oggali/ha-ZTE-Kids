"""One-shot commands for a ZTE Kids watch."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZteKidsConfigEntry
from .api import ZteKidsError
from .const import CONFIG_FIND_WATCH
from .entity import ZteKidsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZteKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ZteKidsFindWatchButton(coordinator, device) for device in coordinator.devices)


class ZteKidsFindWatchButton(ZteKidsEntity, ButtonEntity):
    """Ask the watch to ring so it can be found."""

    _attr_translation_key = "find_watch"

    def __init__(self, coordinator, device: dict[str, str]) -> None:
        super().__init__(coordinator, device, "find_watch")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_save_config(self._imei, config_type=CONFIG_FIND_WATCH)
        except ZteKidsError as err:
            raise HomeAssistantError(str(err)) from err
