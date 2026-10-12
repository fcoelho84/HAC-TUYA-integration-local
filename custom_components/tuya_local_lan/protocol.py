"""Tuya LAN client via tinytuya (3.1–3.5, session key, encrypted UDP)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import tinytuya

_LOGGER = logging.getLogger(__name__)

TCP_PORT = 6668


def _normalize_dps(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if payload.get("Error") or payload.get("Err"):
        raise ConnectionError(
            str(payload.get("Error") or payload.get("Err") or payload)
        )
    dps = payload.get("dps")
    if not isinstance(dps, dict):
        return {}
    return {str(k): v for k, v in dps.items()}


def _make_device(
    device_id: str,
    host: str,
    local_key: str,
    version: str,
    timeout: float,
) -> tinytuya.Device:
    device = tinytuya.Device(
        device_id,
        address=host,
        local_key=local_key or "",
        version=float(version),
        connection_timeout=timeout,
        persist=False,
    )
    device.set_socketTimeout(timeout)
    device.set_socketRetryLimit(1)
    return device


class TuyaLanDevice:
    def __init__(
        self,
        device_id: str,
        local_key: str,
        host: str,
        port: int = TCP_PORT,
        version: str = "3.3",
        timeout: float = 8.0,
    ) -> None:
        self.device_id = device_id
        self.local_key = local_key
        self.host = host
        self.port = port
        self.version = str(version)
        self.timeout = timeout
        self.dps: dict[str, Any] = {}

    def _sync_status(self) -> dict[str, Any]:
        device = _make_device(
            self.device_id,
            self.host,
            self.local_key,
            self.version,
            self.timeout,
        )
        raw = device.status()
        dps = _normalize_dps(raw)
        self.dps.update(dps)
        return dps

    def _sync_set_dps(self, dps: dict[str, Any]) -> dict[str, Any]:
        device = _make_device(
            self.device_id,
            self.host,
            self.local_key,
            self.version,
            self.timeout,
        )
        payload = {str(k): v for k, v in dps.items()}
        if hasattr(device, "set_multiple_values"):
            raw = device.set_multiple_values(payload)
        else:
            raw = None
            for key, value in payload.items():
                raw = device.set_value(key, value)
        try:
            parsed = _normalize_dps(raw)
        except ConnectionError:
            parsed = {}
        self.dps.update(payload)
        if parsed:
            self.dps.update(parsed)
        return self.dps

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync_status)

    async def set_dps(self, dps: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync_set_dps, dps)


async def discover(timeout: float = 4.0) -> list[dict[str, Any]]:
    """UDP discovery including encrypted 6667/3.4 broadcasts."""

    def _scan() -> dict[str, Any]:
        return tinytuya.deviceScan(
            verbose=False,
            maxretry=max(1, int(timeout)),
            color=False,
            poll=False,
            forcescan=False,
        )

    try:
        scanned = await asyncio.to_thread(_scan)
    except Exception as err:
        _LOGGER.warning("tinytuya scan failed: %s", err)
        return []

    found: dict[str, dict[str, Any]] = {}
    if not isinstance(scanned, dict):
        return []

    for ip, info in scanned.items():
        if not isinstance(info, dict):
            continue
        device_id = info.get("gwId") or info.get("devId") or info.get("id")
        if not device_id:
            continue
        device_id = str(device_id)
        version = str(info.get("version") or "3.3")
        found[device_id] = {
            "device_id": device_id,
            "ip": str(info.get("ip") or ip),
            "version": version,
            "product_key": info.get("productKey") or info.get("product_key"),
            "raw": info,
        }
    return list(found.values())
