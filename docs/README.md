# Documentação — Tuya Smart Life (local LAN) → Home Assistant

Artefato analisado: **Tuya Smart Life / Smart Living 7.11.4** (`com.tuya.smart`, XAPK APKPure).

| Campo | Valor |
| --- | --- |
| Package | `com.tuya.smart` |
| Version | `7.11.4` (code `866`) |
| minSdk / targetSdk | 24 / 36 |
| Classes DEX | 78129 |
| SHA-256 APK base | `e62a1344d646fd4b5a7c26dec037dfbe012a1856da03d02b2c04cc31040e283a` |
| Native LAN | `libnetwork-android.so` SHA-256 `2ee9c61031bb4e2d4fd434811eb072e9490fb5a7766bb949aeb55d3b1222279c` |

Ferramentas: REA (JADX headless 0.7.1 + Ghidra 12.1.4). Análise estática; o APK não foi executado.

## Índice

1. [Arquitetura das integrações](./01-arquitetura.md)
2. [Protocolo LAN local](./02-protocolo-lan.md)
3. [Descoberta, handshake e DPs](./03-descoberta-dps.md)
4. [Dispositivos alvo (fechadura + interruptor)](./04-dispositivos-alvo.md)
5. [Evidence REA](./05-evidence.md)
6. [HAC Home Assistant](./06-hac-home-assistant.md)
