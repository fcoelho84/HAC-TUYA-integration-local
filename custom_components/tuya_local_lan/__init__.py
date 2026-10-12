from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .cloud import (
    CloudApiError,
    CloudAuthError,
    async_list_with_session,
    async_lock_alarm_history,
    async_lock_unlock_history,
    async_offline_password_get,
    async_offline_password_list,
    async_temp_password_create,
    async_temp_password_delete,
    async_temp_password_list,
)
from .const import (
    CONF_APP,
    CONF_COUNTRY_CODE,
    CONF_DEVICES,
    CONF_PASSWORD,
    CONF_SESSION,
    CONF_USERNAME,
    DEFAULT_APP,
    DEFAULT_COUNTRY_CODE,
    DISCOVERY_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TuyaLocalCoordinator
from .discovery import async_scan_network

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_NAMES = (
    "rescan",
    "get_unlock_history",
    "get_alarm_history",
    "list_temp_passwords",
    "create_temp_password",
    "delete_temp_password",
    "get_offline_password",
    "list_offline_passwords",
)


def _entry_and_coordinator(
    hass: HomeAssistant, device_id: str
) -> tuple[ConfigEntry, TuyaLocalCoordinator]:
    for entry in hass.config_entries.async_entries(DOMAIN):
        devices = entry.data.get(CONF_DEVICES) or []
        for device in devices:
            if str(device.get("device_id")) != device_id:
                continue
            coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coordinator is None:
                raise HomeAssistantError("coordenador indisponível")
            return entry, coordinator
    raise HomeAssistantError(f"device not found: {device_id}")


def _auth_kwargs(
    entry: ConfigEntry, coordinator: TuyaLocalCoordinator
) -> dict[str, Any]:
    if CONF_USERNAME not in entry.data or CONF_PASSWORD not in entry.data:
        raise HomeAssistantError("conta Tuya não configurada nesta entry")
    return {
        "username": entry.data[CONF_USERNAME],
        "password": entry.data[CONF_PASSWORD],
        "country_code": entry.data.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
        "app": entry.data.get(CONF_APP, DEFAULT_APP),
        "session_data": coordinator.session or entry.data.get(CONF_SESSION),
    }


def _remember_session(
    coordinator: TuyaLocalCoordinator, session: dict[str, str]
) -> None:
    coordinator.session = session


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TuyaLocalCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(p) for p in PLATFORMS]
    )

    async def _async_rescan(_call: ServiceCall) -> None:
        for target in hass.config_entries.async_entries(DOMAIN):
            cloud_devices = None
            session = target.data.get(CONF_SESSION)
            coord = hass.data.get(DOMAIN, {}).get(target.entry_id)
            if coord and coord.session:
                session = coord.session
            if CONF_USERNAME in target.data and CONF_PASSWORD in target.data:
                try:
                    session, cloud_devices = await async_list_with_session(
                        username=target.data[CONF_USERNAME],
                        password=target.data[CONF_PASSWORD],
                        country_code=target.data.get(
                            CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE
                        ),
                        app=target.data.get(CONF_APP, DEFAULT_APP),
                        session_data=session,
                    )
                except CloudAuthError:
                    cloud_devices = None
            devices = await async_scan_network(
                hass,
                timeout=DISCOVERY_TIMEOUT,
                cloud_devices=cloud_devices,
            )
            data = {**target.data, CONF_DEVICES: devices}
            if session is not None:
                data[CONF_SESSION] = session
            hass.config_entries.async_update_entry(
                target,
                data=data,
                title=f"Tuya Local LAN ({len(devices)} device(s))",
            )
            await hass.config_entries.async_reload(target.entry_id)

    async def _async_unlock_history(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, result = await async_lock_unlock_history(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
                limit=int(call.data.get("limit", 50)),
                offset=int(call.data.get("offset", 0)),
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return result

    async def _async_alarm_history(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, result = await async_lock_alarm_history(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
                limit=int(call.data.get("limit", 50)),
                offset=int(call.data.get("offset", 0)),
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return result

    async def _async_list_temp(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, passwords = await async_temp_password_list(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return {"passwords": passwords}

    async def _async_create_temp(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, result = await async_temp_password_create(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
                name=str(call.data["name"]),
                temp_password=str(call.data["password"]),
                effective_time=int(call.data["effective_time"]),
                invalid_time=int(call.data["invalid_time"]),
                avail_time=int(call.data.get("avail_time", 0)),
                phone=call.data.get("phone"),
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return {"result": result}

    async def _async_delete_temp(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, result = await async_temp_password_delete(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
                password_id=call.data["password_id"],
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return {"result": result}

    async def _async_offline_get(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, result = await async_offline_password_get(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
                pwd_type=str(call.data.get("pwd_type", "1")),
                gmt_start=int(call.data.get("gmt_start", 0)),
                gmt_expired=int(call.data.get("gmt_expired", 0)),
                pwd_name=call.data.get("pwd_name"),
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return {"result": result}

    async def _async_offline_list(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"])
        target, coordinator = _entry_and_coordinator(hass, device_id)
        try:
            session, result = await async_offline_password_list(
                **_auth_kwargs(target, coordinator),
                device_id=device_id,
                pwd_type=str(call.data.get("pwd_type", "0")),
            )
        except (CloudAuthError, CloudApiError, RuntimeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err
        _remember_session(coordinator, session)
        return {"result": result}

    if not hass.services.has_service(DOMAIN, "rescan"):
        hass.services.async_register(DOMAIN, "rescan", _async_rescan)
        hass.services.async_register(
            DOMAIN,
            "get_unlock_history",
            _async_unlock_history,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "get_alarm_history",
            _async_alarm_history,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "list_temp_passwords",
            _async_list_temp,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "create_temp_password",
            _async_create_temp,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "delete_temp_password",
            _async_delete_temp,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "get_offline_password",
            _async_offline_get,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "list_offline_passwords",
            _async_offline_list,
            supports_response=SupportsResponse.ONLY,
        )

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
            for name in SERVICE_NAMES:
                if hass.services.has_service(DOMAIN, name):
                    hass.services.async_remove(DOMAIN, name)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
