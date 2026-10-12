"""Smart Life / Tuya Smart account login (mobile API). Session persists forever."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

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

UNLOCK_CODE_HINTS = (
    "unlock_",
    "open_inside",
    "door_opened",
)
ALARM_CODE_HINTS = (
    "alarm",
    "alarm_lock",
    "doorbell",
    "hijack",
    "unlock_offline_clear",
)

T = TypeVar("T")


class CloudAuthError(Exception):
    """Login or session failure."""


class CloudApiError(Exception):
    """Mobile API call failure after auth."""


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


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


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


def _parse_cloud_dps(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        out[str(key)] = value
    return out


def _parse_cloud_schema(raw: Any) -> dict[str, str]:
    """Map dp id -> code from cloud schema / product metadata."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    entries: list[dict[str, Any]] = []
    if isinstance(raw, list):
        entries = [item for item in raw if isinstance(item, dict)]
    elif isinstance(raw, dict):
        nested = raw.get("schema") or raw.get("dpSchema") or raw.get("properties")
        if isinstance(nested, (list, dict, str)):
            return _parse_cloud_schema(nested)
        entries = _schema_entries(raw)
    codes: dict[str, str] = {}
    for entry in entries:
        code = str(entry.get("code") or entry.get("dpCode") or "").strip()
        raw_id = entry.get("id") or entry.get("dpId") or entry.get("dp_id")
        if not code or raw_id is None:
            continue
        codes[str(raw_id)] = code
    return codes


async def _list_devices(client: TuyaPasswordClient) -> list[dict[str, Any]]:
    homes = await client._call("m.life.home.space.list", {})
    gids = {
        obj.get("gid") or obj.get("groupId") or obj.get("homeId")
        for obj in _walk(homes)
        if obj.get("gid") or obj.get("groupId") or obj.get("homeId")
    }
    records: list[dict[str, Any]] = []
    for gid in gids:
        response = await client._call(
            "m.life.my.group.device.list", {"gid": gid}, version="2.2"
        )
        for obj in _walk(response):
            local_key = obj.get("localKey") or obj.get("local_key")
            device_id = obj.get("devId") or obj.get("deviceId") or obj.get("id")
            if not local_key or not device_id:
                continue
            schema_raw = (
                obj.get("schema")
                or obj.get("dpSchema")
                or (obj.get("productBean") or {}).get("schemaInfo")
                or (obj.get("product") or {}).get("schema")
            )
            dps = _parse_cloud_dps(obj.get("dps") or obj.get("dpsData") or obj.get("status"))
            schema_codes = _parse_cloud_schema(schema_raw)
            records.append(
                {
                    "device_id": str(device_id),
                    "local_key": str(local_key),
                    "host": str(obj.get("ip") or obj.get("lanIp") or "") or None,
                    "name": obj.get("name"),
                    "uuid": obj.get("uuid"),
                    "is_online": obj.get("isOnline", obj.get("cloudOnline")),
                    "category": (
                        obj.get("category")
                        or obj.get("categoryCode")
                        or obj.get("deviceType")
                        or obj.get("categoryCodeNew")
                    ),
                    "product_id": obj.get("productId") or obj.get("product_id"),
                    "product_name": obj.get("productName") or obj.get("product_name"),
                    "dps": dps,
                    "schema_codes": schema_codes,
                }
            )
    unique = {
        (item["device_id"], item["local_key"]): item for item in records
    }
    out = list(unique.values())
    for item in out:
        if item.get("schema_codes") and item.get("dps"):
            continue
        category = str(item.get("category") or "").lower()
        name = str(item.get("name") or "").lower()
        wants_schema = (
            category in {"ms", "jtmspro", "videolock", "photolock", "lock", "smartlock", "mk"}
            or "lock" in name
            or "fechadura" in name
            or not item.get("schema_codes")
        )
        if not wants_schema:
            continue
        try:
            detail = await _device_detail(client, item["device_id"])
        except Exception as err:
            _LOGGER.debug("enrich %s failed: %s", item["device_id"], err)
            continue
        if not item.get("dps"):
            item["dps"] = _parse_cloud_dps(
                detail.get("dps") or detail.get("status") or detail.get("dpsData")
            )
        if not item.get("schema_codes"):
            item["schema_codes"] = _parse_cloud_schema(
                detail.get("schema")
                or detail.get("dpSchema")
                or detail.get("schemaInfo")
            )
        if not item.get("category"):
            item["category"] = (
                detail.get("category")
                or detail.get("categoryCode")
                or item.get("category")
            )
    return out


async def _with_client(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    runner: Callable[[TuyaPasswordClient], Awaitable[T]],
) -> tuple[dict[str, str], T]:
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
                return session_data, await runner(client)
            except (CloudAuthError, CloudApiError):
                raise
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

        session = _session_dict(mobile)
        try:
            return session, await runner(client)
        except Exception as err:
            raise CloudApiError(str(err)) from err


def _schema_entries(device: Any) -> list[dict[str, Any]]:
    if not isinstance(device, dict):
        return []
    schema = device.get("schema") or device.get("dpName") or []
    if isinstance(schema, str):
        return []
    if isinstance(schema, dict):
        out: list[dict[str, Any]] = []
        for key, value in schema.items():
            if isinstance(value, dict):
                entry = dict(value)
                entry.setdefault("id", value.get("id") or key)
                entry.setdefault("code", value.get("code") or key)
                out.append(entry)
            else:
                out.append({"id": key, "code": str(value)})
        return out
    if isinstance(schema, list):
        return [item for item in schema if isinstance(item, dict)]
    return []


def _dp_ids_for_codes(
    schema: list[dict[str, Any]],
    hints: tuple[str, ...],
) -> list[int]:
    ids: list[int] = []
    for entry in schema:
        code = str(entry.get("code") or entry.get("dpCode") or "").lower()
        if not code:
            continue
        if not any(code == hint or code.startswith(hint) for hint in hints):
            continue
        raw = entry.get("id") or entry.get("dpId")
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


def _normalize_history(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"datas": [], "totalCount": 0, "hasNext": False, "raw": payload}
    datas = payload.get("datas")
    if datas is None and isinstance(payload.get("result"), dict):
        nested = payload["result"]
        datas = nested.get("datas")
        payload = nested
    if datas is None and isinstance(payload.get("result"), list):
        datas = payload["result"]
    return {
        "datas": datas if isinstance(datas, list) else [],
        "totalCount": payload.get("totalCount") or payload.get("total") or 0,
        "hasNext": bool(payload.get("hasNext")),
        "raw": payload,
    }


async def _device_detail(client: TuyaPasswordClient, device_id: str) -> dict[str, Any]:
    for action in ("thing.m.device.get", "tuya.m.device.get", "m.device.get"):
        try:
            result = await client._call(action, {"devId": device_id})
        except Exception as err:
            _LOGGER.debug("device get %s via %s failed: %s", device_id, action, err)
            continue
        if isinstance(result, dict):
            if isinstance(result.get("result"), dict):
                return result["result"]
            return result
    return {}


async def async_lock_unlock_history(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
    dp_ids: list[int] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Unlock records via panel API tuya.m.scale.history.list."""

    async def _run(client: TuyaPasswordClient) -> dict[str, Any]:
        ids = list(dp_ids or [])
        if not ids:
            detail = await _device_detail(client, device_id)
            ids = _dp_ids_for_codes(_schema_entries(detail), UNLOCK_CODE_HINTS)
        if not ids:
            raise CloudApiError("no unlock dp ids found for device")
        raw = await client._call(
            "tuya.m.scale.history.list",
            {
                "devId": device_id,
                "dpIds": ids,
                "offset": offset,
                "limit": limit,
                "startTime": 0,
                "endTime": 0,
            },
            version="2.0",
        )
        out = _normalize_history(raw)
        out["dp_ids"] = ids
        return out

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )


async def async_lock_alarm_history(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
    dp_ids: list[int] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Alarm records via tuya.m.device.lock.alarm.list."""

    async def _run(client: TuyaPasswordClient) -> dict[str, Any]:
        ids = list(dp_ids or [])
        if not ids:
            detail = await _device_detail(client, device_id)
            ids = _dp_ids_for_codes(_schema_entries(detail), ALARM_CODE_HINTS)
        if not ids:
            raise CloudApiError("no alarm dp ids found for device")
        raw = await client._call(
            "tuya.m.device.lock.alarm.list",
            {
                "devId": device_id,
                "dpIds": ids,
                "offset": offset,
                "limit": limit,
            },
            version="1.0",
        )
        out = _normalize_history(raw)
        out["dp_ids"] = ids
        return out

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )


async def async_temp_password_list(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Online temporary passwords: tuya.m.device.lock.temppwd.list."""

    async def _run(client: TuyaPasswordClient) -> list[dict[str, Any]]:
        raw = await client._call(
            "tuya.m.device.lock.temppwd.list",
            {"devId": device_id},
            version="2.0",
        )
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            result = raw.get("result", raw)
            if isinstance(result, list):
                return [item for item in result if isinstance(item, dict)]
        return []

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )


def _as_epoch(value: int) -> int:
    """Panel APIs mix seconds and ms; keep seconds-sized values as-is."""
    return int(value)


async def async_temp_password_create(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
    name: str,
    temp_password: str,
    effective_time: int,
    invalid_time: int,
    avail_time: int = 0,
    phone: str | None = None,
) -> tuple[dict[str, str], Any]:
    """Create online temp password (panel plaintext password)."""

    async def _run(client: TuyaPasswordClient) -> Any:
        payload: dict[str, Any] = {
            "devId": device_id,
            "name": name,
            "password": temp_password,
            "effectiveTime": _as_epoch(effective_time),
            "invalidTime": _as_epoch(invalid_time),
            "availTime": int(avail_time),
            "schedule": "",
        }
        if phone:
            payload["phone"] = phone
            payload["countryCode"] = str(country_code).lstrip("+")
        last_err: Exception | None = None
        for version in ("5.0", "4.0", "2.0", "1.0"):
            try:
                return await client._call(
                    "tuya.m.device.lock.temppwd.create",
                    payload,
                    version=version,
                )
            except Exception as err:
                last_err = err
                _LOGGER.debug("temppwd.create v%s failed: %s", version, err)
        assert last_err is not None
        raise last_err

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )


async def async_temp_password_delete(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
    password_id: int | str,
) -> tuple[dict[str, str], Any]:
    """Delete online temp password."""

    async def _run(client: TuyaPasswordClient) -> Any:
        last_err: Exception | None = None
        for action in (
            "tuya.m.device.lock.temppwd.del",
            "tuya.m.device.lock.temppwd.remove",
        ):
            try:
                return await client._call(
                    action,
                    {"devId": device_id, "id": password_id},
                    version="2.0",
                )
            except Exception as err:
                last_err = err
                _LOGGER.debug("%s failed: %s", action, err)
        assert last_err is not None
        raise last_err

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )


async def async_offline_password_get(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
    pwd_type: str = "1",
    gmt_start: int = 0,
    gmt_expired: int = 0,
    pwd_name: str | None = None,
) -> tuple[dict[str, str], Any]:
    """Offline temp password (cloud generates digits)."""

    async def _run(client: TuyaPasswordClient) -> Any:
        payload: dict[str, Any] = {
            "devId": device_id,
            "pwdType": str(pwd_type),
            "gmtStart": int(gmt_start),
            "gmtExpired": int(gmt_expired),
        }
        if pwd_name:
            payload["pwdName"] = pwd_name
        return await client._call(
            "tuya.m.device.lock.offlinepwd.get",
            payload,
            version="1.0",
        )

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )


async def async_offline_password_list(
    *,
    username: str,
    password: str,
    country_code: str,
    app: str,
    session_data: dict[str, str] | None,
    device_id: str,
    pwd_type: str = "0",
) -> tuple[dict[str, str], Any]:
    """List offline temporary passwords."""

    async def _run(client: TuyaPasswordClient) -> Any:
        return await client._call(
            "tuya.m.device.lock.offlinepwd.list",
            {"devId": device_id, "pwdType": str(pwd_type)},
            version="1.0",
        )

    return await _with_client(
        username=username,
        password=password,
        country_code=country_code,
        app=app,
        session_data=session_data,
        runner=_run,
    )
