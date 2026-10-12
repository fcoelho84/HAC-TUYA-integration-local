# Descoberta, handshake e Data Points

## Descoberta (`HgwBean`)

Campos observados:

| Campo | Tipo | Significado |
| --- | --- | --- |
| `gwId` | String | ID do device/gateway |
| `ip` | String | IP LAN |
| `version` | String | versão protocolo (ex. `"3.4"`, `"3.5"`) |
| `encrypt` | boolean | tráfego cifrado |
| `uuid` | String | UUID hardware |
| `productKey` | String | produto |
| `active` | int | estado; `active == 2` força `sendBytes2` em 3.4 |
| `sl` | int | security level |
| `ssid` | String | Wi‑Fi (pairing) |
| `token` / `wf_cfg` | boolean | flags de config |
| `lastSeenTime` | long | última vista |
| `mode` / `ablilty` / `proAbility` / `apConfigType` / `devConfigAttribute` / `extend` | vários | capacidades |

UDP listener: `ThingNetworkInterface.listenUDP(port)` → nativo `Thing_Native_ListenUDP` → callback com `HgwBean` / `ThingFrame`.

## Handshake LAN

Em `buildConnect` com `localKey != null`:

1. Registra `LanHandShakeCallback` (onSuccess / onError).
2. `connectDeviceWithKey` (com ou sem `LAN_PROTOCOL_VERSION_3_5`).
3. Se connect OK → `startSwapKey(gwId, localKey)`.
4. Sucesso de handshake → `connectSuccess` → device em `liveGw`.

Sem key: tenta `connectDevice` / `connectDeviceWithKey(..., null, ...)`.

## Data Points (DPs)

Controle e status usam mapa `dps` (código string ou int → valor bool/int/string/enum).

Strings DEX: `publishDps`, `onDpUpdate`, `local dps`, `report dps`, `send dps`.

Schema completo do produto (nomes `switch_1`, `lock_motor_state`, …) vem da nuvem no app. Em LAN só trafegam **IDs numéricos** + valores.

Para o HAC: mapear DPs na config (config flow), com defaults para interruptor multi e fechadura comuns.
