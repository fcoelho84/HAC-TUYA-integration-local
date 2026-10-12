from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_KIND_MULTI_SWITCH, DOMAIN
from .coordinator import TuyaLocalCoordinator
from .discovery import switch_labels


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TuyaLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[TuyaLocalSwitch] = []
    for runtime in coordinator.devices.values():
        if runtime.info.get("kind") != DEVICE_KIND_MULTI_SWITCH:
            continue
        bool_dps = list(runtime.info.get("bool_dps") or [])
        for (key, name), dp in zip(switch_labels(bool_dps), bool_dps, strict=False):
            entities.append(
                TuyaLocalSwitch(coordinator, runtime.device_id, key, dp, name)
            )
    async_add_entities(entities)


class TuyaLocalSwitch(CoordinatorEntity[TuyaLocalCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaLocalCoordinator,
        device_id: str,
        key: str,
        dp: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._dp = str(dp)
        self._attr_name = name
        self._attr_unique_id = f"{device_id}_{key}"
        runtime = coordinator.devices[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=runtime.info.get("name") or f"Tuya {device_id[-6:]}",
            manufacturer="Tuya",
            model=runtime.info.get("product_key") or "Local LAN",
        )

    @property
    def available(self) -> bool:
        runtime = self.coordinator.devices.get(self._device_id)
        return bool(runtime and runtime.available)

    @property
    def is_on(self) -> bool | None:
        data = (self.coordinator.data or {}).get(self._device_id) or {}
        value = data.get(self._dp)
        if value is None:
            value = self.coordinator.devices[self._device_id].dps.get(self._dp)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._device_id, self._dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._device_id, self._dp, False)
