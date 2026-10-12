from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    SCAN_INTERVAL_SECONDS,
    TCP_PORT,
)
from .protocol import TuyaLanDevice

_LOGGER = logging.getLogger(__name__)


class TuyaLocalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry
        data = entry.data
        self.device = TuyaLanDevice(
            device_id=data[CONF_DEVICE_ID],
            local_key=data[CONF_LOCAL_KEY],
            host=data[CONF_HOST],
            port=TCP_PORT,
            version=data.get(CONF_PROTOCOL_VERSION, "3.3"),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.device.status()
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    async def async_set_dp(self, dp: str, value: Any) -> None:
        await self.device.set_dps({dp: value})
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await self.device.disconnect()
