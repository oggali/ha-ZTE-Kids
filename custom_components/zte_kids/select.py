"""Location mode selector for a ZTE Kids watch."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZteKidsConfigEntry
from .api import ZteKidsError
from .const import CONFIG_LOCATION_MODE
from .entity import ZteKidsEntity

LOCATION_MODES = ("1", "2", "3")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZteKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ZteKidsLocationModeSelect(coordinator, device) for device in coordinator.devices)


class ZteKidsLocationModeSelect(ZteKidsEntity, SelectEntity):
    """The watch's three location modes."""

    _attr_translation_key = "location_mode"
    _attr_options = list(LOCATION_MODES)

    def __init__(self, coordinator, device: dict[str, str]) -> None:
        super().__init__(coordinator, device, "location_mode")

    @property
    def current_option(self) -> str | None:
        mode = self._watch.get("location_mode")
        if mode is None:
            return None
        option = str(int(mode))
        if option not in LOCATION_MODES:
            return None
        return option

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.async_save_config(
                self._imei,
                config_type=CONFIG_LOCATION_MODE,
                mode=int(option),
                state_key="location_mode",
                state_value=int(option),
            )
        except ZteKidsError as err:
            raise HomeAssistantError(str(err)) from err
