from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_DEVICES, DISCOVERY_TIMEOUT, DOMAIN
from .discovery import async_scan_network


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "hint": "Vou escanear a LAN (UDP). Sem ID, IP ou token manual."
                },
            )

        return await self.async_step_scan()

    async def async_step_scan(self, user_input: dict | None = None) -> FlowResult:
        devices = await async_scan_network(self.hass, timeout=DISCOVERY_TIMEOUT)
        if not devices:
            return self.async_abort(reason="no_devices")

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        title = f"Tuya Local LAN ({len(devices)} device(s))"
        return self.async_create_entry(
            title=title,
            data={CONF_DEVICES: devices},
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema({}))
        devices = await async_scan_network(self.hass, timeout=DISCOVERY_TIMEOUT)
        if not devices:
            return self.async_abort(reason="no_devices")
        return self.async_update_reload_and_abort(
            self._get_reconfigure_entry(),
            data={CONF_DEVICES: devices},
        )
