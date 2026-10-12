from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_KIND_LOCK, DOMAIN
from .coordinator import TuyaLocalCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TuyaLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        TuyaLocalLock(coordinator, runtime.device_id)
        for runtime in coordinator.devices.values()
        if runtime.info.get("kind") == DEVICE_KIND_LOCK
    ]
    async_add_entities(entities)


def _is_locked(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    text = str(value).lower()
    if text in {"lock", "locked", "close", "closed", "1", "true"}:
        return True
    if text in {"unlock", "unlocked", "open", "opened", "0", "false"}:
        return False
    return None


class TuyaLocalLock(CoordinatorEntity[TuyaLocalCoordinator], LockEntity):
    _attr_has_entity_name = True
    _attr_name = "Fechadura"

    def __init__(self, coordinator: TuyaLocalCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        info = coordinator.devices[device_id].info
        self._dp_cmd = str(info.get("lock_dp") or "1")
        self._dp_state = str(info.get("lock_state_dp") or self._dp_cmd)
        self._attr_unique_id = f"{device_id}_lock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=info.get("name") or f"Tuya {device_id[-6:]}",
            manufacturer="Tuya",
            model=info.get("product_key") or "Local LAN lock",
        )

    @property
    def available(self) -> bool:
        runtime = self.coordinator.devices.get(self._device_id)
        return bool(runtime and runtime.available)

    @property
    def is_locked(self) -> bool | None:
        data = (self.coordinator.data or {}).get(self._device_id) or {}
        value = data.get(self._dp_state)
        if value is None:
            value = self.coordinator.devices[self._device_id].dps.get(self._dp_state)
        return _is_locked(value)

    def _command_value(self, locked: bool) -> Any:
        data = (self.coordinator.data or {}).get(self._device_id) or {}
        current = data.get(self._dp_state)
        if current is None:
            current = self.coordinator.devices[self._device_id].dps.get(self._dp_state)
        if isinstance(current, str):
            return "lock" if locked else "unlock"
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            return 1 if locked else 0
        return locked

    async def async_lock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(
            self._device_id, self._dp_cmd, self._command_value(True)
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(
            self._device_id, self._dp_cmd, self._command_value(False)
        )
