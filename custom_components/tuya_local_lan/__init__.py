from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import CONF_DEVICES, DISCOVERY_TIMEOUT, DOMAIN, PLATFORMS
from .coordinator import TuyaLocalCoordinator
from .discovery import async_scan_network

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TuyaLocalCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(p) for p in PLATFORMS]
    )

    async def _async_rescan(_call: ServiceCall) -> None:
        devices = await async_scan_network(hass, timeout=DISCOVERY_TIMEOUT)
        hass.config_entries.async_update_entry(entry, data={CONF_DEVICES: devices})
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, "rescan", _async_rescan)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform(p) for p in PLATFORMS]
    )
    if unload_ok:
        coordinator: TuyaLocalCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "rescan")
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
