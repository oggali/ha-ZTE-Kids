"""ZTE Kids parent-app integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .api import ZteKidsError
from .const import DOMAIN, PLATFORMS, SERVICE_REFRESH_LOCATION
from .coordinator import ZteKidsCoordinator

type ZteKidsConfigEntry = ConfigEntry[ZteKidsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZteKidsConfigEntry) -> bool:
    coordinator = ZteKidsCoordinator(hass, dict(entry.data))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # One domain service for every config entry. The last unload removes it.
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_LOCATION):

        async def _async_refresh(call: ServiceCall) -> None:
            imeis = _imeis_from_call(hass, call)
            messages: list[str] = []
            refreshed = False
            for item in hass.config_entries.async_entries(DOMAIN):
                item_coordinator: ZteKidsCoordinator = item.runtime_data
                selected = [imei for imei in imeis if any(device["imei"] == imei for device in item_coordinator.devices)]
                if imeis and not selected:
                    continue
                try:
                    skipped = await item_coordinator.async_request_fresh_fix(selected or None)
                except ZteKidsError as err:
                    raise HomeAssistantError(str(err)) from err
                refreshed = True
                messages.extend(skipped.values())
            if not refreshed:
                raise HomeAssistantError("No ZTE Kids watch matched this target.")
            # A partial refresh still succeeds. Fail only when every targeted watch was inside the cooldown.
            if messages and imeis and len(messages) == len(imeis):
                raise HomeAssistantError(messages[0])

        hass.services.async_register(DOMAIN, SERVICE_REFRESH_LOCATION, _async_refresh)

    await hass.config_entries.async_forward_entry_setups(entry, [Platform(platform) for platform in PLATFORMS])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZteKidsConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, [Platform(platform) for platform in PLATFORMS])
    if unload_ok and not any(
        item.entry_id != entry.entry_id and item.domain == DOMAIN for item in hass.config_entries.async_entries(DOMAIN)
    ):
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH_LOCATION)
    return unload_ok


def _imeis_from_call(hass: HomeAssistant, call: ServiceCall) -> list[str]:
    """Map device-registry targets to watch IMEIs.

    An empty list means the caller did not target a device, so every watch is in scope.
    """
    device_ids = call.data.get("device_id")
    if not device_ids:
        return []
    if isinstance(device_ids, str):
        device_ids = [device_ids]
    registry = dr.async_get(hass)
    imeis: list[str] = []
    for device_id in device_ids:
        device = registry.async_get(device_id)
        if device is None:
            continue
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                imeis.append(identifier[1])
    return imeis
