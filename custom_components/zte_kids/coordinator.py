"""Data update coordinator for ZTE Kids watches."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ZteKidsAuthError, ZteKidsClient, ZteKidsError
from .const import CONF_ACCESS_TOKEN, CONF_DEVICES, CONF_OPENID, DOMAIN, HISTORY_UPDATE_SECONDS, MIN_REFRESH_SECONDS

_LOGGER = logging.getLogger(__name__)


class ZteKidsCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll stored history, and request a fresh fix only when asked."""

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=HISTORY_UPDATE_SECONDS),
        )
        self._entry_data = entry_data
        self._last_wake: dict[str, float] = {}
        self.client = ZteKidsClient(async_get_clientsession(hass))

    @property
    def devices(self) -> list[dict[str, str]]:
        return list(self._entry_data.get(CONF_DEVICES) or [])

    def update_entry_data(self, entry_data: dict[str, Any]) -> None:
        self._entry_data = entry_data

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            return await self._fetch(wake=False)
        except ZteKidsAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ZteKidsError as err:
            raise UpdateFailed(str(err)) from err

    async def async_request_fresh_fix(self, imeis: list[str] | None = None) -> dict[str, str]:
        """Ask the watches for a new fix, keeping at least a minute between requests."""
        now = datetime.now().timestamp()
        wanted = imeis or [device["imei"] for device in self.devices]
        skipped: dict[str, str] = {}
        due: list[str] = []
        for imei in wanted:
            previous = self._last_wake.get(imei, 0)
            wait = MIN_REFRESH_SECONDS - (now - previous)
            if wait > 0:
                skipped[imei] = f"Wait {int(wait)}s before asking this watch again."
            else:
                due.append(imei)
                self._last_wake[imei] = now
        if due:
            try:
                data = await self._fetch(wake=True, imeis=due)
            except ZteKidsError as err:
                for imei in due:
                    self._last_wake.pop(imei, None)
                raise
            self.async_set_updated_data(data)
        return skipped

    async def _fetch(self, *, wake: bool, imeis: list[str] | None = None) -> dict[str, dict[str, Any]]:
        openid = self._entry_data[CONF_OPENID]
        token = self._entry_data[CONF_ACCESS_TOKEN]
        current = dict(self.data or {})
        now = dt_util.now()
        day = now.date().isoformat()
        offset = int(now.utcoffset().total_seconds() // 3600) if now.utcoffset() else 0
        zone = self.hass.config.time_zone or "UTC"
        selected = imeis or [device["imei"] for device in self.devices]
        names = {device["imei"]: device.get("name") or device["imei"] for device in self.devices}

        for imei in selected:
            point = None
            if wake:
                point = await self.client.request_location(imei, openid, token)
            if point is None:
                point = await self.client.query_location_history(
                    imei,
                    day=day,
                    time_zone=offset,
                    timezone_str=zone,
                )
            if point is None:
                continue
            previous = current.get(imei, {})
            current[imei] = {
                **previous,
                **point,
                "imei": imei,
                "name": names.get(imei, previous.get("name", imei)),
            }
        return current
