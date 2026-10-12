"""Tuya LAN protocol client (local only).

Wire format aligned with observations from Smart Life 7.11.4
(ThingNetworkApi / libnetwork-android.so) and the public LAN profile
used by local clients (prefix 0x000055AA, commands CONTROL/DP_QUERY/STATUS).
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
import time
from hashlib import md5
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_LOGGER = logging.getLogger(__name__)

PREFIX = b"\x00\x00\x55\xaa"
SUFFIX = b"\x00\x00\xaa\x55"

CMD_UDP = 0x00
CMD_CONTROL = 0x07
CMD_STATUS = 0x08
CMD_HEARTBEAT = 0x09
CMD_DP_QUERY = 0x0A
CMD_CONTROL_NEW = 0x0D
CMD_DP_QUERY_NEW = 0x12
CMD_SESS_KEY_NEG_START = 0x03
CMD_SESS_KEY_NEG_RESP = 0x04
CMD_SESS_KEY_NEG_FINISH = 0x05

CRC_TABLE = [
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
    0xC601, 0x06C0, 0x0780, 0xC741, 0x0500, 0xC5C1, 0xC481, 0x0440,
    0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40,
    0x0A00, 0xCAC1, 0xCB81, 0x0B40, 0xC901, 0x09C0, 0x0880, 0xC841,
    0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40,
    0x1E00, 0xDEC1, 0xDF81, 0x1F40, 0xDD01, 0x1DC0, 0x1C80, 0xDC41,
    0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641,
    0xD201, 0x12C0, 0x1380, 0xD341, 0x1100, 0xD1C1, 0xD081, 0x1040,
    0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240,
    0x3600, 0xF6C1, 0xF781, 0x3740, 0xF501, 0x35C0, 0x3480, 0xF441,
    0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41,
    0xFA01, 0x3AC0, 0x3B80, 0xFB41, 0x3900, 0xF9C1, 0xF881, 0x3840,
    0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41,
    0xEE01, 0x2EC0, 0x2F80, 0xEF41, 0x2D00, 0xEDC1, 0xEC81, 0x2C40,
    0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640,
    0x2200, 0xE2C1, 0xE381, 0x2340, 0xE101, 0x21C0, 0x2080, 0xE041,
    0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240,
    0x6600, 0xA6C1, 0xA781, 0x6740, 0xA501, 0x65C0, 0x6480, 0xA441,
    0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41,
    0xAA01, 0x6AC0, 0x6B80, 0xAB41, 0x6900, 0xA9C1, 0xA881, 0x6840,
    0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41,
    0xBE01, 0x7EC0, 0x7F80, 0xBF41, 0x7D00, 0xBDC1, 0xBC81, 0x7C40,
    0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640,
    0x7200, 0xB2C1, 0xB381, 0x7340, 0xB101, 0x71C0, 0x7080, 0xB041,
    0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241,
    0x9601, 0x56C0, 0x5780, 0x9741, 0x5500, 0x95C1, 0x9481, 0x5440,
    0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40,
    0x5A00, 0x9AC1, 0x9B81, 0x5B40, 0x9901, 0x59C0, 0x5880, 0x9841,
    0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40,
    0x4E00, 0x8EC1, 0x8F81, 0x4F40, 0x8D01, 0x4DC0, 0x4C80, 0x8C41,
    0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641,
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040,
]


def _crc(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def _pad(data: bytes) -> bytes:
    padlen = 16 - (len(data) % 16)
    return data + bytes([padlen] * padlen)


def _unpad(data: bytes) -> bytes:
    if not data:
        return data
    padlen = data[-1]
    if padlen < 1 or padlen > 16:
        return data
    return data[:-padlen]


def _aes_cbc_encrypt(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(_pad(data)) + encryptor.finalize()


def _aes_cbc_decrypt(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    return _unpad(decryptor.update(data) + decryptor.finalize())


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for p in version.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class TuyaLanDevice:
    def __init__(
        self,
        device_id: str,
        local_key: str,
        host: str,
        port: int = 6668,
        version: str = "3.3",
        timeout: float = 8.0,
    ) -> None:
        self.device_id = device_id
        self.local_key = local_key.encode("utf-8")
        self.host = host
        self.port = port
        self.version = version
        self.timeout = timeout
        self._seq = 0
        self._session_key: bytes | None = None
        self.dps: dict[str, Any] = {}
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def _key(self) -> bytes:
        if self._session_key is not None:
            return self._session_key
        return self.local_key

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return self._seq

    def _pack(self, command: int, payload: bytes) -> bytes:
        ver = _version_tuple(self.version)
        seq = self._next_seq()
        if ver >= (3, 4):
            return self._pack_gcm(command, payload, seq)
        return self._pack_legacy(command, payload, seq)

    def _pack_legacy(self, command: int, payload: bytes, seq: int) -> bytes:
        ver = _version_tuple(self.version)
        body = payload
        if command not in (CMD_DP_QUERY, CMD_HEARTBEAT) or payload:
            if ver >= (3, 3) and payload:
                encrypted = _aes_cbc_encrypt(self._key, payload)
                if command in (CMD_CONTROL_NEW, CMD_DP_QUERY_NEW, CMD_STATUS):
                    body = self.version.encode("utf-8") + b"\x00" * 12 + encrypted
                elif command == CMD_CONTROL:
                    body = encrypted
                else:
                    body = encrypted
            elif ver < (3, 3) and payload and command == CMD_CONTROL:
                body = b"3.1" + md5(
                    b"data=" + _aes_cbc_encrypt(self._key, payload)
                    + b"||lpv=3.1||"
                    + self.local_key
                ).hexdigest()[8:24].encode() + _aes_cbc_encrypt(self._key, payload)

        header = PREFIX + struct.pack(">II", seq, command)
        full_len = 4 + len(body) + 8
        packet = header + struct.pack(">I", full_len) + body
        packet += struct.pack(">I", _crc(packet)) + SUFFIX
        return packet

    def _pack_gcm(self, command: int, payload: bytes, seq: int) -> bytes:
        key = self._key
        if len(key) not in (16, 24, 32):
            key = md5(key).digest()
        aesgcm = AESGCM(key)
        nonce = seq.to_bytes(12, "big")
        header = PREFIX + struct.pack(">II", seq, command)
        aad = header
        ciphertext = aesgcm.encrypt(nonce, payload if payload else b"", aad)
        # ciphertext includes tag at end (16 bytes)
        body = self.version.encode("utf-8")[:3].ljust(3, b"\x00") + nonce + ciphertext
        full_len = 4 + len(body) + 8
        packet = header + struct.pack(">I", full_len) + body
        packet += struct.pack(">I", _crc(packet)) + SUFFIX
        return packet

    def _unpack(self, data: bytes) -> tuple[int, bytes]:
        if len(data) < 24 or data[:4] != PREFIX:
            raise ValueError("invalid frame prefix")
        seq, command, length = struct.unpack(">III", data[4:16])
        payload = data[16 : 16 + length - 12]
        ver = _version_tuple(self.version)
        if ver >= (3, 4):
            return command, self._decrypt_gcm(payload, seq, command, data)
        return command, self._decrypt_legacy(payload, command)

    def _decrypt_legacy(self, payload: bytes, command: int) -> bytes:
        if not payload:
            return b""
        data = payload
        if data.startswith(self.version.encode("utf-8")[:3]):
            data = data[15:]
        try:
            return _aes_cbc_decrypt(self._key, data)
        except Exception:
            return payload

    def _decrypt_gcm(self, payload: bytes, seq: int, command: int, full: bytes) -> bytes:
        if len(payload) < 15:
            return b""
        # version(3) + nonce(12) + ciphertext+tag
        nonce = payload[3:15]
        ciphertext = payload[15:]
        key = self._key
        if len(key) not in (16, 24, 32):
            key = md5(key).digest()
        aesgcm = AESGCM(key)
        aad = full[0:12]
        try:
            return aesgcm.decrypt(nonce, ciphertext, aad)
        except Exception as err:
            _LOGGER.debug("GCM decrypt failed: %s", err)
            return b""

    async def connect(self) -> None:
        async with self._lock:
            if self._writer is not None:
                return
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            if _version_tuple(self.version) >= (3, 4):
                await self._negotiate_session_key()

    async def disconnect(self) -> None:
        async with self._lock:
            if self._writer is not None:
                self._writer.close()
                try:
                    await self._writer.wait_closed()
                except Exception:
                    pass
            self._reader = None
            self._writer = None
            self._session_key = None

    async def _exchange(self, command: int, payload: bytes) -> bytes:
        await self.connect()
        assert self._writer is not None and self._reader is not None
        packet = self._pack(command, payload)
        self._writer.write(packet)
        await self._writer.drain()
        header = await asyncio.wait_for(self._reader.readexactly(16), timeout=self.timeout)
        length = struct.unpack(">I", header[12:16])[0]
        rest_len = length - 4 + 8
        rest = await asyncio.wait_for(self._reader.readexactly(rest_len), timeout=self.timeout)
        cmd, body = self._unpack(header + rest)
        return body

    async def _negotiate_session_key(self) -> None:
        # Simplified 3.4/3.5 local session path used by local clients.
        # Full Android startSwapKey lives in native; this keeps LAN usable.
        local_nonce = md5(str(time.time()).encode()).digest()
        try:
            resp = await self._exchange(CMD_SESS_KEY_NEG_START, local_nonce)
            if len(resp) >= 32:
                remote = resp[:16]
                self._session_key = md5(local_nonce + remote + self.local_key).digest()
                await self._exchange(CMD_SESS_KEY_NEG_FINISH, remote)
        except Exception as err:
            _LOGGER.debug("session key negotiate skipped/failed: %s", err)
            self._session_key = None

    async def status(self) -> dict[str, Any]:
        ver = _version_tuple(self.version)
        cmd = CMD_DP_QUERY_NEW if ver >= (3, 3) else CMD_DP_QUERY
        payload = b'{"dps":{}}' if ver < (3, 4) else json.dumps({"dps": {}}).encode()
        body = await self._exchange(cmd, payload)
        return self._parse_dps(body)

    async def set_dps(self, dps: dict[str, Any]) -> dict[str, Any]:
        ver = _version_tuple(self.version)
        cmd = CMD_CONTROL_NEW if ver >= (3, 3) else CMD_CONTROL
        payload = json.dumps({"dps": dps, "t": int(time.time())}).encode()
        body = await self._exchange(cmd, payload)
        parsed = self._parse_dps(body)
        self.dps.update(dps)
        if parsed:
            self.dps.update(parsed)
        return self.dps

    def _parse_dps(self, body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        text = body.decode("utf-8", errors="ignore").strip("\x00")
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        dps = data.get("dps") or {}
        normalized = {str(k): v for k, v in dps.items()}
        self.dps.update(normalized)
        return normalized


async def discover(timeout: float = 4.0) -> list[dict[str, Any]]:
    """Listen for UDP broadcasts on classic Tuya ports."""
    found: dict[str, dict[str, Any]] = {}
    loop = asyncio.get_running_loop()

    class _Proto(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            try:
                text = data.decode("utf-8", errors="ignore")
                start = text.find("{")
                end = text.rfind("}")
                if start < 0 or end < 0:
                    return
                payload = json.loads(text[start : end + 1])
                gw = payload.get("gwId") or payload.get("devId")
                if not gw:
                    return
                found[gw] = {
                    "device_id": gw,
                    "ip": payload.get("ip") or addr[0],
                    "version": str(payload.get("version") or "3.3"),
                    "product_key": payload.get("productKey") or payload.get("productKey"),
                    "raw": payload,
                }
            except Exception:
                return

    transports = []
    for port in (6666, 6667):
        try:
            transport, _ = await loop.create_datagram_endpoint(
                _Proto,
                local_addr=("0.0.0.0", port),
                reuse_port=True,
            )
            transports.append(transport)
        except OSError as err:
            _LOGGER.debug("UDP bind %s failed: %s", port, err)

    # also broadcast a nudge
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        for port in (6666, 6667):
            try:
                sock.sendto(b"\x00", ("255.255.255.255", port))
            except OSError:
                pass
        sock.close()
    except OSError:
        pass

    await asyncio.sleep(timeout)
    for t in transports:
        t.close()
    return list(found.values())
