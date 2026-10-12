# Protocolo LAN local

## Evidência nativa

`ThingNetworkApi` carrega `libnetwork-android.so` (Ghidra, arm64).

Strings / símbolos observados no SO:

- `localKey`, `decryptRespWithLocalKey`
- `LAN_PROTOCOL_VERSION_3_5`, frames `v3.5` (header, nonce, GCM tag)
- `UdpSession::buildPacket() VERSION_3` + validação de tamanho de chave AES
- `encryptGcmData`, `AES-128/256-GCM`, `AES-128-ECB` (legado)
- `ConnectDeviceWithHandShake`, `Thing_Native_ListenUDP`, `Thing_Native_connectDevice`
- JSON de discovery: `"udpport"`, `"udpport_backup"`
- Logs: `UdpSession initialized, local port %d`, `Listen in port %d`

Ports clássicos Tuya presentes como literais no DEX/SO: **6666 / 6667 (UDP discovery)**, **6668 (TCP controle)**.

## Versões de protocolo (app)

Constantes em strings DEX / Java:

| Constante | Uso no app |
| --- | --- |
| `LAN_PROTOCOL_VERSION_BEFORE_3_5` | caminho legado |
| `LAN_PROTOCOL_VERSION_3_2` … `3_4` | AES-CBC / variantes |
| `LAN_PROTOCOL_VERSION_3_5` / `3_5_1` | AES-GCM + session key (`startSwapKey`) |

`DevTransferService.checkHgwVersion(version, 3.5f)` decide connect/send path.

## Tipos de frame (`FrameTypeEnum`)

Nomes observados no APK (valores numéricos do `<clinit>` não decompilaram no JADX; mapeamento abaixo alinha nomes do enum ao protocolo LAN público compatível):

| Nome (APK) | Código usual | Função |
| --- | --- | --- |
| `UDP` | 0x00 | discovery / anúncio |
| `AP_CONFIG` | 0x01 | pairing AP |
| `ACTIVE` | 0x02 | ativação |
| `CONTROL` | 0x07 | set DPs (legado) |
| `STATUS` | 0x08 | status reportado pelo device |
| `HEART_BEAT` | 0x09 | keep-alive |
| `DP_QUERY` | 0x0a | query estado |
| `CONTROL_NEW` | 0x0d | set DPs (v3.3+) |
| `DP_QUERY_NEW` | 0x12 | query (v3.3+) |
| `LAN_GW_UPDATE` | (enum) | OTA gateway (tratado em `controlByBinary`) |

Outros: `LAN_SCENE`, OTA (`LAN_OTA_*`), sub-device (`LAN_SUB_DEV_*`), IPC, etc.

## Formato de pacote (síntese para implementação)

Prefixo histórico Tuya: `0x000055AA` … payload … CRC / sufixo `0x0000AA55` (v3.1–3.4).

- **≤ 3.3**: payload JSON ou AES-CBC com `localKey` (MD5 da key como IV em 3.1 header).
- **3.4 / 3.5**: AES-GCM; 3.5 usa handshake/`startSwapKey` e session key após connect.

Payload de controle tipicamente:

```json
{"dps":{"1":true,"2":false}}
```

Query: `{"dps":{}}` ou lista de IDs.

## Criptografia (observado)

| API Java | Função |
| --- | --- |
| `encryptAesDataForUDP` | UDP discovery / broadcast |
| `encryptGcmData(version, type, data, key)` | frames GCM |
| `gcmDecryptData` | decrypt GCM |
| `encrypt` / `decrypt` (ThingNetworkApi) | AES genérico no SO |
| `startSwapKey(gwId, localKey)` | pós-connect ≥ 3.5 |

## Limitação

Pseudocode de `initUdpSession` (Ghidra) valida listener + key e aloca sessão UDP; parsing completo de wire format 3.5 no SO é grande. O HAC implementa o subset estável usado por clients locais (tinytuya-compatible) alinhado às observations acima.
