from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DEVICES, SCAN_INTERVAL_SECONDS, TCP_PORT
from .protocol import TuyaLanDevice

_LOGGER = logging.getLogger(__name__)


class DeviceRuntime:
    def __init__(self, info: dict[str, Any]) -> None:
        self.info = info
        self.device = TuyaLanDevice(
            device_id=info["device_id"],
            local_key=info.get("local_key") or "0" * 16,
            host=info["host"],
            port=TCP_PORT,
            version=info.get("protocol_version") or "3.3",
        )
        self.dps: dict[str, Any] = dict(info.get("dps") or {})
        self.available = bool(info.get("host")) and not info.get("needs_key")

    @property
    def device_id(self) -> str:
        return self.info["device_id"]


class TuyaLocalCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.devices: dict[str, DeviceRuntime] = {
            item["device_id"]: DeviceRuntime(item)
            for item in entry.data.get(CONF_DEVICES, [])
        }

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        errors = 0
        for device_id, runtime in self.devices.items():
            if not runtime.info.get("host"):
                runtime.available = False
                result[device_id] = runtime.dps
                continue
            if runtime.info.get("needs_key") and not runtime.info.get("local_key"):
                runtime.available = False
                result[device_id] = runtime.dps
                continue
            try:
                dps = await runtime.device.status()
                runtime.dps = dps or runtime.device.dps
                runtime.available = True
                result[device_id] = runtime.dps
            except Exception as err:
                errors += 1
                runtime.available = False
                result[device_id] = runtime.dps
                _LOGGER.debug("update failed %s: %s", device_id, err)
        if errors and errors == len(self.devices):
            raise UpdateFailed("all devices unreachable")
        return result

    async def async_set_dp(self, device_id: str, dp: str, value: Any) -> None:
        runtime = self.devices[device_id]
        await runtime.device.set_dps({dp: value})
        runtime.dps[dp] = value
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        for runtime in self.devices.values():
            await runtime.device.disconnect()
