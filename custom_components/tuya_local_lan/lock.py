from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DP_LOCK,
    CONF_DP_LOCK_STATE,
    DEVICE_TYPE_LOCK,
    DOMAIN,
)
from .coordinator import TuyaLocalCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_LOCK:
        return
    coordinator: TuyaLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TuyaLocalLock(coordinator, entry)])


def _is_locked(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value in (1, True)
    text = str(value).lower()
    if text in {"lock", "locked", "close", "closed", "1", "true"}:
        return True
    if text in {"unlock", "unlocked", "open", "opened", "0", "false"}:
        return False
    return None


class TuyaLocalLock(CoordinatorEntity[TuyaLocalCoordinator], LockEntity):
    _attr_has_entity_name = True
    _attr_name = "Fechadura"

    def __init__(self, coordinator: TuyaLocalCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._dp_cmd = str(entry.data[CONF_DP_LOCK])
        self._dp_state = str(entry.data.get(CONF_DP_LOCK_STATE, entry.data[CONF_DP_LOCK]))
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_lock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            name=entry.title,
            manufacturer="Tuya",
            model="Local LAN lock",
        )

    @property
    def is_locked(self) -> bool | None:
        value = self.coordinator.data.get(self._dp_state)
        if value is None:
            value = self.coordinator.device.dps.get(self._dp_state)
        return _is_locked(value)

    async def async_lock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp_cmd, True)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp_cmd, False)
