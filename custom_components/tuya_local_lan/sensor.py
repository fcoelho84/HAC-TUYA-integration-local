from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud import (
    CloudApiError,
    CloudAuthError,
    async_lock_unlock_history,
)
from .const import (
    CONF_APP,
    CONF_COUNTRY_CODE,
    CONF_PASSWORD,
    CONF_SESSION,
    CONF_USERNAME,
    DEFAULT_APP,
    DEFAULT_COUNTRY_CODE,
    DEVICE_KIND_LOCK,
    DOMAIN,
    LAST_UNLOCK_SCAN_SECONDS,
)
from .coordinator import TuyaLocalCoordinator

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=LAST_UNLOCK_SCAN_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TuyaLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for runtime in coordinator.devices.values():
        battery_dp = runtime.info.get("battery_dp")
        if battery_dp:
            entities.append(
                TuyaBatterySensor(coordinator, runtime.device_id, str(battery_dp))
            )
        if runtime.info.get("kind") == DEVICE_KIND_LOCK:
            entities.append(
                TuyaLastUnlockSensor(coordinator, entry, runtime.device_id)
            )
    async_add_entities(entities)


class TuyaBatterySensor(CoordinatorEntity[TuyaLocalCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Bateria"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: TuyaLocalCoordinator,
        device_id: str,
        battery_dp: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._dp = battery_dp
        info = coordinator.devices[device_id].info
        self._attr_unique_id = f"{device_id}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=info.get("name") or f"Tuya {device_id[-6:]}",
            manufacturer="Tuya",
            model=info.get("product_key") or info.get("category") or "Local LAN",
        )

    def _raw_value(self) -> Any:
        data = (self.coordinator.data or {}).get(self._device_id) or {}
        value = data.get(self._dp)
        if value is None:
            runtime = self.coordinator.devices.get(self._device_id)
            if runtime:
                value = runtime.dps.get(self._dp)
                if value is None:
                    value = (runtime.info.get("dps") or {}).get(self._dp)
        return value

    @property
    def available(self) -> bool:
        # Fechadura dorme na LAN; bateria ainda vale se já temos valor (cloud/LAN).
        runtime = self.coordinator.devices.get(self._device_id)
        if not runtime:
            return False
        if self._raw_value() is not None:
            return True
        return bool(runtime.available)

    @property
    def native_value(self) -> int | None:
        value = self._raw_value()
        if value is None:
            return None
        try:
            level = int(value)
        except (TypeError, ValueError):
            return None
        if level < 0 or level > 100:
            return None
        return level


class TuyaLastUnlockSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Último desbloqueio"
    _attr_should_poll = True
    scan_interval = SCAN_INTERVAL

    def __init__(
        self,
        coordinator: TuyaLocalCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._device_id = device_id
        info = coordinator.devices[device_id].info
        self._attr_unique_id = f"{device_id}_last_unlock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=info.get("name") or f"Tuya {device_id[-6:]}",
            manufacturer="Tuya",
            model=info.get("product_key") or info.get("category") or "Local LAN lock",
        )
        self._value: str | None = None
        self._extra: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return CONF_USERNAME in self._entry.data and CONF_PASSWORD in self._entry.data

    @property
    def native_value(self) -> str | None:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra

    async def async_update(self) -> None:
        if not self.available:
            return
        info = self.coordinator.devices[self._device_id].info
        try:
            session, result = await async_lock_unlock_history(
                username=self._entry.data[CONF_USERNAME],
                password=self._entry.data[CONF_PASSWORD],
                country_code=self._entry.data.get(
                    CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE
                ),
                app=self._entry.data.get(CONF_APP, DEFAULT_APP),
                session_data=self.coordinator.session
                or self._entry.data.get(CONF_SESSION),
                device_id=self._device_id,
                dp_ids=info.get("unlock_dp_ids"),
                schema_codes=info.get("schema_codes"),
                gid=info.get("gid"),
                limit=1,
                offset=0,
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            _LOGGER.warning("last unlock %s: %s", self._device_id, err)
            self._extra = {"last_error": str(err)}
            return
        self.coordinator.session = session
        datas = result.get("datas") or []
        if not datas:
            self._value = None
            self._extra = {
                "last_error": None,
                "dp_ids": result.get("dp_ids"),
                "gid": result.get("gid"),
                "total_count": result.get("totalCount"),
            }
            return
        row = datas[0] if isinstance(datas[0], dict) else {}
        unlock_name = row.get("unlockName") or row.get("unlock_name") or ""
        user_name = row.get("userName") or row.get("user_name") or ""
        created = row.get("gmtCreate") or row.get("gmt_create")
        stamp = None
        if created is not None:
            try:
                ms = int(created)
                if ms < 1_000_000_000_000:
                    ms *= 1000
                stamp = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                stamp = str(created)
        label = " / ".join(part for part in (unlock_name, user_name) if part) or "unlock"
        self._value = label
        self._extra = {
            "unlock_name": unlock_name or None,
            "user_name": user_name or None,
            "gmt_create": stamp,
            "dp_ids": result.get("dp_ids"),
            "raw": row,
        }
