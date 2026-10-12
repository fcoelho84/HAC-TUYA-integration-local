from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .cloud import (
    APP_SMART_LIFE,
    APP_TUYA_SMART,
    CloudAuthError,
    async_list_with_session,
    async_login,
)
from .const import (
    CONF_APP,
    CONF_COUNTRY_CODE,
    CONF_DEVICES,
    CONF_PASSWORD,
    CONF_SESSION,
    CONF_USERNAME,
    DEFAULT_APP,
    DEFAULT_COUNTRY_CODE,
    DISCOVERY_TIMEOUT,
    DOMAIN,
)
from .discovery import async_scan_network

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_COUNTRY_CODE, default=DEFAULT_COUNTRY_CODE): str,
        vol.Required(CONF_APP, default=DEFAULT_APP): vol.In(
            [APP_TUYA_SMART, APP_SMART_LIFE]
        ),
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=USER_SCHEMA,
                errors=errors,
            )

        try:
            session, cloud_devices = await async_login(
                username=user_input[CONF_USERNAME].strip(),
                password=user_input[CONF_PASSWORD],
                country_code=str(user_input[CONF_COUNTRY_CODE]).strip(),
                app=user_input[CONF_APP],
            )
        except CloudAuthError:
            errors["base"] = "invalid_auth"
            return self.async_show_form(
                step_id="user",
                data_schema=USER_SCHEMA,
                errors=errors,
            )

        devices = await async_scan_network(
            self.hass,
            timeout=DISCOVERY_TIMEOUT,
            cloud_devices=cloud_devices,
        )
        if not devices:
            return self.async_abort(reason="no_devices")

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        title = f"Tuya Local LAN ({len(devices)} device(s))"
        return self.async_create_entry(
            title=title,
            data={
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_COUNTRY_CODE: str(user_input[CONF_COUNTRY_CODE]).strip(),
                CONF_APP: user_input[CONF_APP],
                CONF_SESSION: session,
                CONF_DEVICES: devices,
            },
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        try:
            session, cloud_devices = await async_list_with_session(
                username=entry.data[CONF_USERNAME],
                password=entry.data[CONF_PASSWORD],
                country_code=entry.data.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
                app=entry.data.get(CONF_APP, DEFAULT_APP),
                session_data=entry.data.get(CONF_SESSION),
            )
        except CloudAuthError:
            return self.async_abort(reason="invalid_auth")

        devices = await async_scan_network(
            self.hass,
            timeout=DISCOVERY_TIMEOUT,
            cloud_devices=cloud_devices,
        )
        if not devices:
            return self.async_abort(reason="no_devices")

        return self.async_update_reload_and_abort(
            entry,
            data={
                **entry.data,
                CONF_SESSION: session,
                CONF_DEVICES: devices,
            },
        )
