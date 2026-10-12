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


def _switchable_dps(dps: dict[str, Any]) -> list[str]:
    """All DPs that look on/off controllable (bool or exact 0/1)."""
    ids = [str(k) for k, v in dps.items() if isinstance(v, bool)]
    if not ids:
        ids = [
            str(k)
            for k, v in dps.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) in (0, 1)
        ]
    return _sorted_dp_ids(ids)


def _lock_command_dp(dps: dict[str, Any]) -> str | None:
    for key, value in dps.items():
        if isinstance(value, str) and value.lower() in LOCK_STRINGS:
            return str(key)
    switchable = _switchable_dps(dps)
    return switchable[0] if switchable else None


def _battery_dp(dps: dict[str, Any], used: set[str]) -> str | None:
    """Pick a numeric 0–100 DP that looks like battery percentage."""
    candidates: list[tuple[int, str]] = []
    for key, value in dps.items():
        dp = str(key)
        if dp in used:
            continue
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        level = int(value)
        if level < 0 or level > 100:
            continue
        # Prefer common Tuya battery DP ids, else any 0-100 leftover.
        priority = 0 if dp in {"47", "56", "12", "11", "10", "9"} else 1
        candidates.append((priority, dp))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], int(item[1]) if item[1].isdigit() else item[1]))
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
) -> dict[str, Any]:
    """Detect lock vs switchable channels from DPs + cloud category/name."""
    as_lock = _looks_like_lock(name, category)
    if not as_lock:
        for value in dps.values():
            if isinstance(value, str) and value.lower() in LOCK_STRINGS:
                as_lock = True
                break

    if as_lock and not _looks_like_switch_category(category):
        dp = _lock_command_dp(dps) or "1"
        battery_dp = _battery_dp(dps, {dp})
        return {
            "kind": "lock",
            "lock_dp": dp,
            "lock_state_dp": dp,
            "bool_dps": [],
            "battery_dp": battery_dp,
            "category": category,
        }

    switch_dps = _switchable_dps(dps)
    battery_dp = _battery_dp(dps, set(switch_dps))
    return {
        "kind": "multi_switch",
        "bool_dps": switch_dps,
        "lock_dp": None,
        "lock_state_dp": None,
        "battery_dp": battery_dp,
        "category": category,
    }


def switch_labels(bool_dps: list[str]) -> list[tuple[str, str]]:
    """Map each discovered DP to a generic channel label."""
    out: list[tuple[str, str]] = []
    for idx, dp in enumerate(bool_dps):
        if len(bool_dps) == 1:
            name = "Interruptor"
        else:
            name = f"Canal {idx + 1}"
        out.append((f"dp_{dp}", name))
    return out


async def probe_device(
    discovered: dict[str, Any],
    local_key: str,
    name: str | None = None,
    category: str | None = None,
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
        info = classify_device(
            dps or device.dps,
            name=device_name,
            category=device_category,
        )
        result = {
            "device_id": discovered["device_id"],
            "host": host,
            "local_key": local_key,
            "protocol_version": version,
            "product_key": discovered.get("product_key"),
            "dps": dps or device.dps,
            **info,
        }
        if device_name:
            result["name"] = device_name
        return result

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
        )
        if probed is None:
            fallback = classify_device(
                {},
                name=cloud.get("name"),
                category=cloud.get("category"),
            )
            results.append(
                {
                    "device_id": dev_id,
                    "host": item["ip"],
                    "local_key": local_key,
                    "name": cloud.get("name"),
                    "protocol_version": str(item.get("version") or "3.3"),
                    "product_key": item.get("product_key"),
                    "dps": {},
                    **fallback,
                    "needs_key": not bool(local_key),
                }
            )
            continue
        probed["needs_key"] = not bool(local_key)
        if cloud.get("name"):
            probed["name"] = cloud["name"]
        if cloud.get("category"):
            probed["category"] = cloud["category"]
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
            fallback = classify_device(
                {},
                name=cloud.get("name"),
                category=cloud.get("category"),
            )
            results.append(
                {
                    "device_id": device_id,
                    "host": "",
                    "local_key": local_key,
                    "name": cloud.get("name"),
                    "protocol_version": "3.3",
                    "product_key": None,
                    "dps": {},
                    **fallback,
                    "needs_key": not bool(local_key),
                }
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
        )
        if probed is None:
            fallback = classify_device(
                {},
                name=cloud.get("name"),
                category=cloud.get("category"),
            )
            results.append(
                {
                    "device_id": device_id,
                    "host": host,
                    "local_key": local_key,
                    "name": cloud.get("name"),
                    "protocol_version": "3.3",
                    "product_key": None,
                    "dps": {},
                    **fallback,
                    "needs_key": not bool(local_key),
                }
            )
            continue
        probed["needs_key"] = not bool(local_key)
        if cloud.get("name"):
            probed["name"] = cloud["name"]
        if cloud.get("category"):
            probed["category"] = cloud["category"]
        results.append(probed)

    return results
