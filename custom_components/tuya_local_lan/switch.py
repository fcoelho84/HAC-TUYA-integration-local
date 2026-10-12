from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DP_LIGHT_1,
    CONF_DP_LIGHT_2,
    CONF_DP_OUTLET,
    DEVICE_TYPE_MULTI_SWITCH,
    DOMAIN,
)
from .coordinator import TuyaLocalCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_MULTI_SWITCH:
        return
    coordinator: TuyaLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    channels = [
        ("luz_1", entry.data[CONF_DP_LIGHT_1], "Luz 1"),
        ("luz_2", entry.data[CONF_DP_LIGHT_2], "Luz 2"),
        ("tomada", entry.data[CONF_DP_OUTLET], "Tomada"),
    ]
    async_add_entities(
        [
            TuyaLocalSwitch(coordinator, entry, key, dp, name)
            for key, dp, name in channels
        ]
    )


class TuyaLocalSwitch(CoordinatorEntity[TuyaLocalCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaLocalCoordinator,
        entry: ConfigEntry,
        key: str,
        dp: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._dp = str(dp)
        self._attr_name = name
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            name=entry.title,
            manufacturer="Tuya",
            model="Local LAN multi-switch",
        )

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self._dp)
        if value is None:
            value = self.coordinator.device.dps.get(self._dp)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp, False)
