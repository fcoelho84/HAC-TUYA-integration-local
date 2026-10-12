from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DP_LIGHT_1,
    CONF_DP_LIGHT_2,
    CONF_DP_LOCK,
    CONF_DP_LOCK_STATE,
    CONF_DP_OUTLET,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DEFAULT_DP_LIGHT_1,
    DEFAULT_DP_LIGHT_2,
    DEFAULT_DP_LOCK,
    DEFAULT_DP_LOCK_STATE,
    DEFAULT_DP_OUTLET,
    DEFAULT_PROTOCOL,
    DEVICE_TYPE_LOCK,
    DEVICE_TYPE_MULTI_SWITCH,
    DOMAIN,
)
from .protocol import TuyaLanDevice, discover

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PROTOCOL_VERSION, default=DEFAULT_PROTOCOL): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["3.1", "3.3", "3.4", "3.5"],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_MULTI_SWITCH): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[DEVICE_TYPE_MULTI_SWITCH, DEVICE_TYPE_LOCK],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)

STEP_MULTI = vol.Schema(
    {
        vol.Required(CONF_DP_LIGHT_1, default=DEFAULT_DP_LIGHT_1): str,
        vol.Required(CONF_DP_LIGHT_2, default=DEFAULT_DP_LIGHT_2): str,
        vol.Required(CONF_DP_OUTLET, default=DEFAULT_DP_OUTLET): str,
    }
)

STEP_LOCK = vol.Schema(
    {
        vol.Required(CONF_DP_LOCK, default=DEFAULT_DP_LOCK): str,
        vol.Required(CONF_DP_LOCK_STATE, default=DEFAULT_DP_LOCK_STATE): str,
    }
)


async def _test_connection(hass: HomeAssistant, data: dict) -> None:
    device = TuyaLanDevice(
        device_id=data[CONF_DEVICE_ID],
        local_key=data[CONF_LOCAL_KEY],
        host=data[CONF_HOST],
        version=data[CONF_PROTOCOL_VERSION],
    )
    try:
        await device.status()
    finally:
        await device.disconnect()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            self._data.update(user_input)
            try:
                await _test_connection(self.hass, self._data)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                if user_input[CONF_DEVICE_TYPE] == DEVICE_TYPE_LOCK:
                    return await self.async_step_lock_dps()
                return await self.async_step_multi_dps()

        return self.async_show_form(step_id="user", data_schema=STEP_USER, errors=errors)

    async def async_step_multi_dps(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(step_id="multi_dps", data_schema=STEP_MULTI)

    async def async_step_lock_dps(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(step_id="lock_dps", data_schema=STEP_LOCK)

    async def async_step_discover(self, user_input: dict | None = None) -> FlowResult:
        devices = await discover(timeout=3.0)
        if not devices:
            return self.async_abort(reason="no_devices")
        options = {
            d["device_id"]: f"{d['device_id']} @ {d['ip']} (v{d['version']})"
            for d in devices
        }
        schema = vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(options)})
        if user_input is not None:
            chosen = next(d for d in devices if d["device_id"] == user_input[CONF_DEVICE_ID])
            self._data[CONF_DEVICE_ID] = chosen["device_id"]
            self._data[CONF_HOST] = chosen["ip"]
            self._data[CONF_PROTOCOL_VERSION] = chosen["version"]
            return await self.async_step_user()
        return self.async_show_form(step_id="discover", data_schema=schema)
