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
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICES,
    CONF_OPENID,
    DOMAIN,
    HISTORY_UPDATE_SECONDS,
    MIN_REFRESH_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class ZteKidsCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll stored history on the update interval.

    A live GPS request goes out only from async_request_fresh_fix, and then
    at most once a minute per watch.
    """

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
                _LOGGER.debug("Skip live fix for %s, %.0fs left in the cooldown", imei, wait)
            else:
                due.append(imei)
                # Reserve the slot before the request so overlapping calls cannot both wake the watch.
                self._last_wake[imei] = now
        if due:
            try:
                data = await self._fetch(wake=True, imeis=due)
            except ZteKidsError as err:
                # The request never landed, so the next call may try again immediately.
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
        _LOGGER.debug(
            "Update wake=%s watches=%s day=%s zone=%s offset=%s",
            wake,
            selected,
            day,
            zone,
            offset,
        )

        for imei in selected:
            point = None
            if wake:
                point = await self.client.request_location(imei, openid, token)
            # Scheduled updates skip the wake call. A wake that returns nothing
            # still falls back to today's stored history.
            if point is None:
                point = await self.client.query_location_history(
                    imei,
                    token,
                    day=day,
                    time_zone=offset,
                    timezone_str=zone,
                )
            previous = current.get(imei, {})
            status: dict[str, Any] = {}
            if not wake:
                status = await self._status(imei, openid, token, day=day, time_zone=offset, timezone_str=zone)
            if point is None and not status and imei not in current:
                _LOGGER.debug("No position stored for %s", imei)
                continue
            current[imei] = {
                **previous,
                **(point or {}),
                **status,
                "imei": imei,
                "name": names.get(imei, previous.get("name", imei)),
            }
        return current

    async def _status(
        self,
        imei: str,
        openid: str,
        token: str,
        *,
        day: str,
        time_zone: int,
        timezone_str: str,
    ) -> dict[str, Any]:
        """Read stored watch state. A failed call keeps the previous value."""
        status: dict[str, Any] = {}
        device = await self._optional(self.client.query_device(imei, openid, token))
        config = await self._optional(self.client.query_system_config(imei, token))
        daily = await self._optional(
            self.client.query_sport(imei, token, day=day, time_zone=time_zone, timezone_str=timezone_str, period="daily")
        )
        week = await self._optional(
            self.client.query_sport(imei, token, day=day, time_zone=time_zone, timezone_str=timezone_str, period="week")
        )
        if device:
            status.update(device)
        if config:
            status.update(config)
        if daily:
            status.update(daily)
        if week:
            status["week_steps"] = week.get("steps")
            status["week_distance"] = week.get("distance")
            status["week_calories"] = week.get("calories")
        lists = {
            "wifi": self.client.query_wifi(imei, token),
            "places": self.client.query_places(imei, token),
            "safe_zones": self.client.query_safe_zones(imei, token),
            "reminders": self.client.query_reminders(imei, token, day=day),
            "contacts": self.client.query_contacts(imei, token),
            "calls": self.client.query_call_log(imei, token),
            "messages": self.client.query_messages(imei, token),
        }
        for key, call in lists.items():
            result = await self._optional(call)
            if result is not None:
                status[key] = result
        return status

    async def async_save_config(
        self,
        imei: str,
        *,
        config_type: int,
        status: int | None = None,
        mode: int | None = None,
        state_key: str | None = None,
        state_value: Any = None,
    ) -> None:
        """Write one setting, then read the stored config again."""
        token = self._entry_data[CONF_ACCESS_TOKEN]
        await self.client.save_system_config(
            imei,
            token,
            config_type=config_type,
            status=status,
            mode=mode,
        )
        if state_key is not None:
            current = dict(self.data or {})
            watch = dict(current.get(imei) or {})
            watch[state_key] = state_value
            current[imei] = watch
            self.async_set_updated_data(current)
        config = await self._optional(self.client.query_system_config(imei, token))
        if config:
            current = dict(self.data or {})
            watch = dict(current.get(imei) or {})
            watch.update(config)
            current[imei] = watch
            self.async_set_updated_data(current)

    async def _optional(self, call: Any) -> Any:
        try:
            return await call
        except ZteKidsAuthError:
            raise
        except ZteKidsError as err:
            _LOGGER.debug("Stored-state call failed: %s", err)
            return None
