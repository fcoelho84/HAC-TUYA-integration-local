from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
        self._dp_cmd = info.get("lock_dp")
        self._dp_state = info.get("lock_state_dp") or self._dp_cmd
        self._controllable = bool(info.get("lock_controllable") and self._dp_cmd)
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
        if not runtime:
            return False
        # Estado pode vir da nuvem mesmo com LAN dormindo.
        if self._read_state_value() is not None:
            return True
        return bool(runtime.available and self._controllable)

    @property
    def is_locked(self) -> bool | None:
        return _is_locked(self._read_state_value())

    def _read_state_value(self) -> Any:
        if not self._dp_state:
            return None
        dp = str(self._dp_state)
        data = (self.coordinator.data or {}).get(self._device_id) or {}
        value = data.get(dp)
        if value is None:
            runtime = self.coordinator.devices[self._device_id]
            value = runtime.dps.get(dp)
            if value is None:
                value = (runtime.info.get("dps") or {}).get(dp)
        return value

    def _command_value(self, locked: bool) -> Any:
        current = self._read_state_value()
        if isinstance(current, str):
            return "lock" if locked else "unlock"
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            return 1 if locked else 0
        return locked

    async def async_lock(self, **kwargs: Any) -> None:
        if not self._controllable or not self._dp_cmd:
            raise HomeAssistantError(
                "esta fechadura não expõe DP local de trava "
                "(comum em BLE/WiFi Tuya; unlock_* é só evento)"
            )
        await self.coordinator.async_set_dp(
            self._device_id, str(self._dp_cmd), self._command_value(True)
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        if not self._controllable or not self._dp_cmd:
            raise HomeAssistantError(
                "esta fechadura não expõe DP local de trava "
                "(comum em BLE/WiFi Tuya; unlock_* é só evento)"
            )
        await self.coordinator.async_set_dp(
            self._device_id, str(self._dp_cmd), self._command_value(False)
        )
