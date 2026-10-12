"""UDP discovery + cloud local keys + optional HA key harvest."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .protocol import TuyaLanDevice, discover

_LOGGER = logging.getLogger(__name__)

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


def classify_device(dps: dict[str, Any]) -> dict[str, Any]:
    """Infer lock vs switches from live DP values."""
    bool_dps = sorted(
        (str(k) for k, v in dps.items() if isinstance(v, bool)),
        key=lambda x: int(x) if x.isdigit() else x,
    )
    lock_dps = [
        str(k)
        for k, v in dps.items()
        if isinstance(v, str) and str(v).lower() in LOCK_STRINGS
    ]

    if lock_dps:
        dp = lock_dps[0]
        return {"kind": "lock", "lock_dp": dp, "lock_state_dp": dp, "bool_dps": []}

    if not bool_dps and dps:
        # single numeric 0/1 often used as switch/lock
        numeric = [
            str(k)
            for k, v in dps.items()
            if isinstance(v, (int, float)) and v in (0, 1)
        ]
        if len(numeric) == 1:
            return {
                "kind": "lock",
                "lock_dp": numeric[0],
                "lock_state_dp": numeric[0],
                "bool_dps": [],
            }
        bool_dps = sorted(numeric, key=lambda x: int(x) if x.isdigit() else x)

    return {"kind": "multi_switch", "bool_dps": bool_dps, "lock_dp": None, "lock_state_dp": None}


def switch_labels(bool_dps: list[str]) -> list[tuple[str, str]]:
    """Map DP list to (key, friendly name)."""
    labels_3 = ["Luz 1", "Luz 2", "Tomada"]
    labels_2 = ["Luz 1", "Luz 2"]
    out: list[tuple[str, str]] = []
    for idx, dp in enumerate(bool_dps):
        if len(bool_dps) == 3 and idx < 3:
            name = labels_3[idx]
        elif len(bool_dps) == 2 and idx < 2:
            name = labels_2[idx]
        elif len(bool_dps) == 1:
            name = "Interruptor"
        else:
            name = f"Canal {idx + 1}"
        out.append((f"dp_{dp}", name))
    return out


async def probe_device(
    discovered: dict[str, Any],
    local_key: str,
) -> dict[str, Any] | None:
    """Try LAN status; return enriched device dict or None."""
    version = str(discovered.get("version") or "3.3")
    device = TuyaLanDevice(
        device_id=discovered["device_id"],
        local_key=local_key or "0" * 16,
        host=discovered["ip"],
        version=version,
    )
    try:
        dps = await device.status()
    except Exception as err:
        _LOGGER.debug(
            "probe failed %s@%s key=%s: %s",
            discovered["device_id"],
            discovered["ip"],
            "yes" if local_key else "no",
            err,
        )
        if local_key:
            return None
        # retry nonsense key already failed; give up
        return None
    finally:
        await device.disconnect()

    info = classify_device(dps or device.dps)
    return {
        "device_id": discovered["device_id"],
        "host": discovered["ip"],
        "local_key": local_key,
        "protocol_version": version,
        "product_key": discovered.get("product_key"),
        "dps": dps or device.dps,
        **info,
    }


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
        probed = await probe_device(item, local_key)
        if probed is None and local_key:
            continue
        if probed is None:
            results.append(
                {
                    "device_id": dev_id,
                    "host": item["ip"],
                    "local_key": "",
                    "name": cloud.get("name"),
                    "protocol_version": str(item.get("version") or "3.3"),
                    "product_key": item.get("product_key"),
                    "dps": {},
                    "kind": "multi_switch",
                    "bool_dps": ["1", "2", "3"],
                    "lock_dp": None,
                    "lock_state_dp": None,
                    "needs_key": True,
                }
            )
            continue
        probed["needs_key"] = not bool(local_key)
        if cloud.get("name"):
            probed["name"] = cloud["name"]
        results.append(probed)

    for device_id, cloud in cloud_by_id.items():
        if device_id in seen:
            continue
        host = cloud.get("host") or (lan_by_id.get(device_id) or {}).get("ip")
        if not host:
            results.append(
                {
                    "device_id": device_id,
                    "host": "",
                    "local_key": str(cloud.get("local_key") or ""),
                    "name": cloud.get("name"),
                    "protocol_version": "3.3",
                    "product_key": None,
                    "dps": {},
                    "kind": "multi_switch",
                    "bool_dps": ["1", "2", "3"],
                    "lock_dp": None,
                    "lock_state_dp": None,
                    "needs_key": not bool(cloud.get("local_key")),
                }
            )
            continue
        discovered = {
            "device_id": device_id,
            "ip": host,
            "version": "3.3",
            "product_key": None,
        }
        local_key = str(cloud.get("local_key") or keyring.get(device_id) or "")
        probed = await probe_device(discovered, local_key)
        if probed is None:
            results.append(
                {
                    "device_id": device_id,
                    "host": host,
                    "local_key": local_key,
                    "name": cloud.get("name"),
                    "protocol_version": "3.3",
                    "product_key": None,
                    "dps": {},
                    "kind": "multi_switch",
                    "bool_dps": ["1", "2", "3"],
                    "lock_dp": None,
                    "lock_state_dp": None,
                    "needs_key": not bool(local_key),
                }
            )
            continue
        probed["needs_key"] = not bool(local_key)
        if cloud.get("name"):
            probed["name"] = cloud["name"]
        results.append(probed)

    return results
