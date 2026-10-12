"""Smart Life / Tuya Smart account login (mobile API). Session persists forever."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from tuya_mobile import (
    TuyaMobileApp,
    TuyaMobileInvalidAuth,
    TuyaMobileSession,
    TuyaPasswordClient,
)

_LOGGER = logging.getLogger(__name__)

APP_SMART_LIFE = "smart_life"
APP_TUYA_SMART = "tuya_smart"

APP_CHOICES = {
    APP_SMART_LIFE: TuyaMobileApp.SMART_LIFE,
    APP_TUYA_SMART: TuyaMobileApp.TUYA_SMART,
}


class CloudAuthError(Exception):
    """Login or session failure."""


def _session_dict(mobile: TuyaMobileSession) -> dict[str, str]:
    return {
        "sid": mobile.sid,
        "ecode": mobile.ecode or "",
        "uid": mobile.uid or "",
        "endpoint": mobile.endpoint or "",
    }


def _apply_session(client: TuyaPasswordClient, session_data: dict[str, str]) -> None:
    sid = session_data.get("sid") or ""
    ecode = session_data.get("ecode") or ""
    uid = session_data.get("uid") or ""
    endpoint = session_data.get("endpoint") or ""
    if not sid:
        raise CloudAuthError("missing sid")
    client.sid = sid
    client.ecode = ecode or None
    client.uid = uid or None
    if endpoint:
        client.mobile_url = endpoint
    client.mobile_session = TuyaMobileSession(
        sid=sid,
        ecode=ecode or None,
        uid=uid or None,
        endpoint=endpoint,
    )


async def async_login(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Login once. Return (session, devices with local_key)."""
    application = APP_CHOICES.get(app)
    if application is None:
        raise CloudAuthError(f"unsupported app: {app}")

    async with aiohttp.ClientSession() as http:
        client = TuyaPasswordClient.for_application(
            application,
            http,
            username=username,
        )
        try:
            mobile = await client.login_with_password(
                password, country_code=str(country_code).lstrip("+")
            )
        except TuyaMobileInvalidAuth as err:
            raise CloudAuthError(str(err)) from err
        except Exception as err:
            raise CloudAuthError(str(err)) from err

        devices = await _list_devices(client)
        return _session_dict(mobile), devices


async def async_list_with_session(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Reuse saved session; re-login only if session is dead."""
    application = APP_CHOICES.get(app)
    if application is None:
        raise CloudAuthError(f"unsupported app: {app}")

    async with aiohttp.ClientSession() as http:
        client = TuyaPasswordClient.for_application(
            application,
            http,
            username=username,
        )
        if session_data and session_data.get("sid"):
            try:
                _apply_session(client, session_data)
                devices = await _list_devices(client)
                return session_data, devices
            except Exception as err:
                _LOGGER.info("saved session expired, re-login: %s", err)

        try:
            mobile = await client.login_with_password(
                password, country_code=str(country_code).lstrip("+")
            )
        except TuyaMobileInvalidAuth as err:
            raise CloudAuthError(str(err)) from err
        except Exception as err:
            raise CloudAuthError(str(err)) from err

        devices = await _list_devices(client)
        return _session_dict(mobile), devices


async def _list_devices(client: TuyaPasswordClient) -> list[dict[str, Any]]:
    records = await client.get_local_keys([])
    out: list[dict[str, Any]] = []
    for item in records:
        device_id = item.get("device_id")
        local_key = item.get("local_key")
        if not device_id or not local_key:
            continue
        out.append(
            {
                "device_id": str(device_id),
                "local_key": str(local_key),
                "host": str(item.get("ip") or "") or None,
                "name": item.get("name"),
                "uuid": item.get("uuid"),
                "is_online": item.get("is_online"),
            }
        )
    return out
