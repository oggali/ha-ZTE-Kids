"""Config flow for ZTE Kids."""

from __future__ import annotations

from typing import Any

# voluptuous ships with Home Assistant, so it is not a manifest requirement.
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZteKidsAuthError, ZteKidsClient, ZteKidsCodeRequired, ZteKidsError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CODE,
    CONF_DEVICES,
    CONF_EMAIL,
    CONF_OPENID,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_USER_NAME,
    DOMAIN,
)


class ZteKidsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in with the same email and password the ZTE Kids app uses."""

    VERSION = 1

    def __init__(self) -> None:
        self._account = ""
        self._password = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._account = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]
            try:
                return await self._async_login()
            except ZteKidsCodeRequired:
                return await self.async_step_code()
            except ZteKidsAuthError:
                errors["base"] = "invalid_auth"
            except ZteKidsError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=self._account): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Second step when the server asks for a text-message code."""
        errors: dict[str, str] = {}
        client = ZteKidsClient(async_get_clientsession(self.hass))
        if user_input is None:
            try:
                await client.send_captcha(self._account)
            except ZteKidsError:
                errors["base"] = "cannot_connect"
        else:
            try:
                return await self._async_login(user_input[CONF_CODE].strip())
            except ZteKidsAuthError:
                errors["base"] = "invalid_auth"
            except ZteKidsError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._account = entry_data.get(CONF_EMAIL) or entry_data.get(CONF_PHONE, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            try:
                return await self._async_login(update_existing=True)
            except ZteKidsCodeRequired:
                return await self.async_step_code()
            except ZteKidsAuthError:
                errors["base"] = "invalid_auth"
            except ZteKidsError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def _async_login(self, code: str | None = None, update_existing: bool = False) -> FlowResult:
        """Log in, then store the session and watch list.

        The password is used for this call only. Later polls use the access token.
        """
        client = ZteKidsClient(async_get_clientsession(self.hass))
        session = await client.login(self._account, self._password, code)
        devices = await client.list_devices(session["openid"], session["accesstoken"])
        if not devices:
            return self.async_abort(reason="no_devices")
        await self.async_set_unique_id(session["openid"])
        data = {
            CONF_EMAIL: self._account,
            CONF_ACCESS_TOKEN: session["accesstoken"],
            CONF_OPENID: session["openid"],
            CONF_USER_NAME: session["user_name"],
            CONF_DEVICES: devices,
        }
        if update_existing and self.context.get("entry_id"):
            self.hass.config_entries.async_update_entry(self._get_reauth_entry(), data=data)
            await self.hass.config_entries.async_reload(self.context["entry_id"])
            return self.async_abort(reason="reauth_successful")
        self._abort_if_unique_id_configured()
        title = session["user_name"] or self._account
        return self.async_create_entry(title=title, data=data)
