"""UDP discovery + cloud local keys + optional HA key harvest."""

from __future__ import annotations

import ipaddress
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .protocol import TuyaLanDevice, discover

_LOGGER = logging.getLogger(__name__)

PROBE_VERSIONS = ("3.3", "3.4", "3.5", "3.2", "3.1")


def _is_private_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_private
    except ValueError:
        return False

LOCK_STRINGS = {
    "lock",
    "locked",
    "unlock",
    "unlocked",
    "close",
    "closed",
    "open",
    "opened",
}

# Tuya product category codes (cloud). Used only as signals, not device layouts.
LOCK_CATEGORIES = {
    "ms",
    "jtmspro",
    "videolock",
    "photolock",
    "lock",
    "smartlock",
    "mk",
}
SWITCH_CATEGORIES = {
    "kg",
    "cz",
    "pc",
    "tdq",
    "tgq",
    "clkg",
    "wk",
    "cwwsq",
}

LOCK_NAME_HINTS = (
    "lock",
    "fechadura",
    "door lock",
    "smart lock",
    "trava",
    "cadeado",
)


BATTERY_CODES = {
    "residual_electricity",
    "battery_percentage",
    "battery",
    "va_battery",
    "batpercent",
}
BATTERY_STATE_CODES = {"battery_state"}
LOCK_CONTROL_CODES = {
    "lock_motor",
    "lock_motor_state",
    "closed_opened",
    "lock",
    "approve_unlock",
    "remote_unlock",
    "switch_lock",
    "remote_no_dp_key",
}
LOCK_STATE_CODES = {
    "lock_motor_state",
    "closed_opened",
    "door_opened",
    "lock_state",
    "lock",
    "lock_motor",
}
SWITCH_EXCLUDE_CODES = {
    "child_lock",
    "switch_all",
    "relay_status",
    "switch_inching",
    "countdown",
    "cycle_time",
    "random_time",
}


def _sorted_dp_ids(ids: list[str]) -> list[str]:
    return sorted(ids, key=lambda x: int(x) if x.isdigit() else x)


def _category_token(category: str | None) -> str:
    return str(category or "").strip().lower()


def _looks_like_lock(name: str | None, category: str | None) -> bool:
    if _category_token(category) in LOCK_CATEGORIES:
        return True
    text = f"{name or ''} {category or ''}".lower()
    return any(hint in text for hint in LOCK_NAME_HINTS)


def _looks_like_switch_category(category: str | None) -> bool:
    return _category_token(category) in SWITCH_CATEGORIES


def _is_switch_code(code: str) -> bool:
    text = code.lower().strip()
    if not text or text in SWITCH_EXCLUDE_CODES:
        return False
    if text.startswith("countdown") or text.startswith("relay"):
        return False
    if text in {"switch", "socket", "outlet"}:
        return True
    if text.startswith("switch_") and text not in SWITCH_EXCLUDE_CODES:
        return True
    if text.startswith("socket") or text.startswith("outlet"):
        return True
    return False


def _code_for(dp: str, schema_codes: dict[str, str] | None) -> str:
    if not schema_codes:
        return ""
    return str(schema_codes.get(str(dp)) or "").lower()


def _switchable_dps(
    dps: dict[str, Any],
    schema_codes: dict[str, str] | None = None,
) -> list[str]:
    """On/off channels. Prefer schema switch_* / socket; avoid junk bools."""
    if schema_codes:
        ids = [
            str(dp)
            for dp in dps
            if _is_switch_code(_code_for(str(dp), schema_codes))
        ]
        if ids:
            return _sorted_dp_ids(ids)
        ids = [
            dp
            for dp, code in schema_codes.items()
            if _is_switch_code(code)
        ]
        if ids:
            return _sorted_dp_ids(ids)

    ids = [str(k) for k, v in dps.items() if isinstance(v, bool)]
    if not ids:
        ids = [
            str(k)
            for k, v in dps.items()
            if isinstance(v, (int, float))
            and not isinstance(v, bool)
            and int(v) in (0, 1)
        ]
    ids = _sorted_dp_ids(ids)
    # Classic 2 luzes + tomada: DPs 1/2/3. Extra bool often USB/backlight.
    if len(ids) > 3 and all(dp in ids for dp in ("1", "2", "3")):
        return ["1", "2", "3"]
    return ids


def _dp_by_codes(
    schema_codes: dict[str, str] | None,
    wanted: set[str],
) -> str | None:
    if not schema_codes:
        return None
    for dp, code in schema_codes.items():
        if code.lower() in wanted:
            return str(dp)
    return None


def _lock_command_dp(
    dps: dict[str, Any],
    schema_codes: dict[str, str] | None = None,
) -> str | None:
    # unlock_* are event records (tuya-local), not remote control.
    by_code = _dp_by_codes(schema_codes, LOCK_CONTROL_CODES)
    if by_code:
        return by_code
    for key, value in dps.items():
        code = _code_for(str(key), schema_codes)
        if code.startswith("unlock_"):
            continue
        if isinstance(value, str) and value.lower() in LOCK_STRINGS:
            return str(key)
    return None


def _lock_state_dp(
    dps: dict[str, Any],
    command_dp: str | None,
    schema_codes: dict[str, str] | None = None,
) -> str | None:
    by_code = _dp_by_codes(schema_codes, LOCK_STATE_CODES)
    if by_code:
        return by_code
    return command_dp


def _battery_dp(
    dps: dict[str, Any],
    used: set[str],
    schema_codes: dict[str, str] | None = None,
) -> str | None:
    """Battery % DP. Prefer residual_electricity (tuya-local)."""
    by_code = _dp_by_codes(schema_codes, BATTERY_CODES)
    if by_code and by_code not in used:
        return by_code

    candidates: list[tuple[int, str]] = []
    for key, value in dps.items():
        dp = str(key)
        if dp in used:
            continue
        code = _code_for(dp, schema_codes)
        if code in BATTERY_STATE_CODES:
            continue
        if code.startswith("unlock_"):
            continue
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        level = int(value)
        if level < 0 or level > 100:
            continue
        if code in BATTERY_CODES:
            priority = -1
        elif dp in {"8", "12", "47", "56", "11", "10", "9"}:
            priority = 0
        else:
            priority = 1
        candidates.append((priority, dp))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item[0], int(item[1]) if item[1].isdigit() else item[1])
    )
    return candidates[0][1]


def harvest_local_keys(hass: HomeAssistant) -> dict[str, str]:
    """Collect local_key from other HA integrations/files."""
    keys: dict[str, str] = {}

    for domain in ("tuya", "tuya_local", "localtuya", "tuyalocal"):
        bucket = hass.data.get(domain)
        if not bucket:
            continue
        if isinstance(bucket, dict):
            for value in bucket.values():
                _extract_from_obj(value, keys)

    for entry in hass.config_entries.async_entries():
        if entry.domain not in {"tuya", "tuya_local", "localtuya", "tuyalocal", "tinytuya"}:
            continue
        data = entry.data
        _extract_from_mapping(data, keys)
        for device in data.get("devices") or []:
            if isinstance(device, dict):
                _extract_from_mapping(device, keys)

    config_dir = Path(hass.config.config_dir)
    for rel in (
        "devices.json",
        "tuya_devices.json",
        "tinytuya/devices.json",
        "tuya_local_lan/keys.json",
        "tuya_local_lan/devices.json",
    ):
        path = config_dir / rel
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            _LOGGER.debug("skip key file %s: %s", path, err)
            continue
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    _extract_from_mapping(item, keys)
        elif isinstance(raw, dict):
            _extract_from_mapping(raw, keys)
            for item in raw.values():
                if isinstance(item, dict):
                    _extract_from_mapping(item, keys)

    return keys


def _extract_from_obj(obj: Any, keys: dict[str, str]) -> None:
    device_map = getattr(obj, "device_map", None)
    if isinstance(device_map, dict):
        for device in device_map.values():
            dev_id = getattr(device, "id", None) or getattr(device, "uuid", None)
            local_key = getattr(device, "local_key", None)
            if dev_id and local_key:
                keys[str(dev_id)] = str(local_key)
    devices = getattr(obj, "devices", None)
    if isinstance(devices, dict):
        for dev_id, device in devices.items():
            local_key = getattr(device, "local_key", None)
            if local_key is None and isinstance(device, dict):
                local_key = device.get("local_key") or device.get("localKey")
            if local_key:
                keys[str(dev_id)] = str(local_key)


def _extract_from_mapping(data: dict[str, Any], keys: dict[str, str]) -> None:
    dev_id = data.get("device_id") or data.get("dev_id") or data.get("id") or data.get("gwId")
    local_key = data.get("local_key") or data.get("localKey") or data.get("key")
    if dev_id and local_key and local_key not in {"", "None"}:
        keys[str(dev_id)] = str(local_key)


def classify_device(
    dps: dict[str, Any],
    name: str | None = None,
    category: str | None = None,
    schema_codes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Detect lock vs switchable channels from DPs + cloud category/schema."""
    as_lock = _looks_like_lock(name, category)
    if not as_lock:
        for value in dps.values():
            if isinstance(value, str) and value.lower() in LOCK_STRINGS:
                as_lock = True
                break
    if not as_lock and schema_codes:
        as_lock = any(
            code.lower() in BATTERY_CODES
            or code.lower().startswith("unlock_")
            or code.lower() in LOCK_CONTROL_CODES
            for code in schema_codes.values()
        ) and not _looks_like_switch_category(category)

    if as_lock and not _looks_like_switch_category(category):
        dp = _lock_command_dp(dps, schema_codes)
        state_dp = _lock_state_dp(dps, dp, schema_codes)
        used = {x for x in (dp, state_dp) if x}
        battery_dp = _battery_dp(dps, used, schema_codes)
        unlock_dp_ids: list[int] = []
        for raw_dp, code in (schema_codes or {}).items():
            text = str(code or "").lower()
            if not (
                text.startswith("unlock_")
                or text in {"open_inside", "door_opened"}
            ):
                continue
            try:
                unlock_dp_ids.append(int(raw_dp))
            except (TypeError, ValueError):
                continue
        return {
            "kind": "lock",
            "lock_dp": dp,
            "lock_state_dp": state_dp,
            "lock_controllable": bool(dp),
            "bool_dps": [],
            "battery_dp": battery_dp,
            "unlock_dp_ids": sorted(set(unlock_dp_ids)),
            "schema_codes": schema_codes or {},
            "category": category,
        }

    switch_dps = _switchable_dps(dps, schema_codes)
    battery_dp = _battery_dp(dps, set(switch_dps), schema_codes)
    return {
        "kind": "multi_switch",
        "bool_dps": switch_dps,
        "lock_dp": None,
        "lock_state_dp": None,
        "lock_controllable": False,
        "battery_dp": battery_dp,
        "schema_codes": schema_codes or {},
        "category": category,
    }


def switch_labels(
    bool_dps: list[str],
    schema_codes: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Map each discovered DP to a channel label."""
    out: list[tuple[str, str]] = []
    for idx, dp in enumerate(bool_dps):
        code = _code_for(dp, schema_codes)
        if "usb" in code or "socket" in code or "outlet" in code or "cz" in code:
            name = "Tomada"
        elif code.endswith("_1") or code in {"switch_1", "switch_led_1"}:
            name = "Luz 1"
        elif code.endswith("_2") or code in {"switch_2", "switch_led_2"}:
            name = "Luz 2"
        elif code.endswith("_3") or code in {"switch_3", "switch_led_3"}:
            name = "Luz 3" if len(bool_dps) > 3 else "Tomada"
        elif len(bool_dps) == 1:
            name = "Interruptor"
        elif len(bool_dps) == 3 and idx == 2:
            name = "Tomada"
        elif len(bool_dps) >= 2 and idx < 2:
            name = f"Luz {idx + 1}"
        else:
            name = f"Canal {idx + 1}"
        out.append((f"dp_{dp}", name))
    return out


def _merge_device_record(
    *,
    device_id: str,
    host: str,
    local_key: str,
    protocol_version: str,
    product_key: Any,
    lan_dps: dict[str, Any],
    cloud: dict[str, Any],
    name: str | None,
    category: str | None,
) -> dict[str, Any]:
    cloud_dps = dict(cloud.get("dps") or {})
    schema_codes = dict(cloud.get("schema_codes") or {})
    merged = {**cloud_dps, **lan_dps}
    info = classify_device(
        merged,
        name=name or cloud.get("name"),
        category=category or cloud.get("category"),
        schema_codes=schema_codes or None,
    )
    result = {
        "device_id": device_id,
        "host": host,
        "local_key": local_key,
        "protocol_version": protocol_version,
        "product_key": product_key,
        "dps": merged,
        **info,
        "needs_key": not bool(local_key),
    }
    if cloud.get("gid"):
        result["gid"] = cloud["gid"]
    final_name = name or cloud.get("name")
    if final_name:
        result["name"] = final_name
    if category or cloud.get("category"):
        result["category"] = category or cloud.get("category")
    return result


async def probe_device(
    discovered: dict[str, Any],
    local_key: str,
    name: str | None = None,
    category: str | None = None,
    cloud: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Try LAN status across protocol versions; return enriched dict or None."""
    host = discovered.get("ip") or ""
    if not host:
        return None

    preferred = str(discovered.get("version") or "3.3")
    versions = [preferred, *[v for v in PROBE_VERSIONS if v != preferred]]
    last_err: Exception | None = None
    device_name = name or discovered.get("name")
    device_category = category or discovered.get("category")
    cloud = cloud or {}

    for version in versions:
        device = TuyaLanDevice(
            device_id=discovered["device_id"],
            local_key=local_key or "0" * 16,
            host=host,
            version=version,
        )
        try:
            dps = await device.status()
        except Exception as err:
            last_err = err
            _LOGGER.debug(
                "probe failed %s@%s v=%s key=%s: %s",
                discovered["device_id"],
                host,
                version,
                "yes" if local_key else "no",
                err,
            )
            await device.disconnect()
            continue
        await device.disconnect()
        return _merge_device_record(
            device_id=discovered["device_id"],
            host=host,
            local_key=local_key,
            protocol_version=version,
            product_key=discovered.get("product_key"),
            lan_dps=dps or device.dps or {},
            cloud=cloud,
            name=device_name,
            category=device_category,
        )

    if last_err:
        _LOGGER.warning(
            "probe exhausted %s@%s: %s",
            discovered["device_id"],
            host,
            last_err,
        )
    return None


async def async_scan_network(
    hass: HomeAssistant,
    timeout: float = 5.0,
    cloud_devices: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Discover LAN devices; merge cloud local_keys; classify DPs."""
    found = await discover(timeout=timeout)
    keyring = harvest_local_keys(hass)
    cloud_by_id: dict[str, dict[str, Any]] = {}
    for item in cloud_devices or []:
        device_id = str(item.get("device_id") or "")
        if not device_id:
            continue
        cloud_by_id[device_id] = item
        local_key = item.get("local_key")
        if local_key:
            keyring[device_id] = str(local_key)

    lan_by_id = {item["device_id"]: item for item in found}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in found:
        dev_id = item["device_id"]
        seen.add(dev_id)
        local_key = keyring.get(dev_id, "")
        cloud = cloud_by_id.get(dev_id) or {}
        probed = await probe_device(
            item,
            local_key,
            name=cloud.get("name"),
            category=cloud.get("category"),
            cloud=cloud,
        )
        if probed is None:
            results.append(
                _merge_device_record(
                    device_id=dev_id,
                    host=item["ip"],
                    local_key=local_key,
                    protocol_version=str(item.get("version") or "3.3"),
                    product_key=item.get("product_key"),
                    lan_dps={},
                    cloud=cloud,
                    name=cloud.get("name"),
                    category=cloud.get("category"),
                )
            )
            continue
        results.append(probed)

    for device_id, cloud in cloud_by_id.items():
        if device_id in seen:
            continue
        lan_ip = (lan_by_id.get(device_id) or {}).get("ip")
        cloud_ip = cloud.get("host")
        host = lan_ip if _is_private_ip(lan_ip) else None
        if host is None and _is_private_ip(cloud_ip):
            host = cloud_ip
        local_key = str(cloud.get("local_key") or keyring.get(device_id) or "")
        if not host:
            results.append(
                _merge_device_record(
                    device_id=device_id,
                    host="",
                    local_key=local_key,
                    protocol_version="3.3",
                    product_key=None,
                    lan_dps={},
                    cloud=cloud,
                    name=cloud.get("name"),
                    category=cloud.get("category"),
                )
            )
            continue
        discovered = {
            "device_id": device_id,
            "ip": host,
            "version": "3.3",
            "product_key": None,
            "category": cloud.get("category"),
            "name": cloud.get("name"),
        }
        probed = await probe_device(
            discovered,
            local_key,
            name=cloud.get("name"),
            category=cloud.get("category"),
            cloud=cloud,
        )
        if probed is None:
            results.append(
                _merge_device_record(
                    device_id=device_id,
                    host=host,
                    local_key=local_key,
                    protocol_version="3.3",
                    product_key=None,
                    lan_dps={},
                    cloud=cloud,
                    name=cloud.get("name"),
                    category=cloud.get("category"),
                )
            )
            continue
        results.append(probed)

    return results
