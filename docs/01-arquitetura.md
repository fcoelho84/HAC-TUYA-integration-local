# Arquitetura das integrações no app

## Camadas observadas

```
UI / painéis (React Native, Lynx, plugins)
        │
        ▼
SDK ThingClips (com.thingclips.*)  ← rebrand Tuya
        │
        ├─ nuvem (MQTT / HTTP) — fora do escopo local
        │
        └─ LAN local
              │
              ├─ DevTransferService (Android Service)
              │     bind AIDL, mapa liveGw de HgwBean
              │     buildConnect / controlByBinary / sendBytes
              │
              ├─ ThingNetworkInterface (Java façade)
              │     connectDeviceWithKey, startSwapKey,
              │     listenUDP, sendBytes / sendBytes2,
              │     encryptGcmData / gcmDecryptData
              │
              └─ ThingNetworkApi (JNI)
                    System.loadLibrary("network-android")
                    │
                    ▼
              libnetwork-android.so
                    BizLogicService / BizNetService
                    UdpSession, AES-GCM / AES-CBC, localKey
```

## Pacotes relevantes (DEX)

| Pacote / classe | Papel |
| --- | --- |
| `com.thingclips.smart.android.hardware.service.DevTransferService` | Serviço de transferência LAN; mantém gateways online |
| `com.thingclips.smart.android.hardware.bean.HgwBean` | Dispositivo descoberto (gwId, ip, version, encrypt, uuid, productKey, active, sl…) |
| `com.thingclips.smart.android.device.ThingNetworkInterface` | API Java de conexão, UDP, criptografia, callbacks |
| `com.thingclips.smart.android.device.ThingNetworkApi` | Wrappers `native`; carrega `network-android` |
| `com.thingclips.sdk.hardware.enums.FrameTypeEnum` | Tipos de frame (CONTROL, DP_QUERY, STATUS, HEART_BEAT, …) |
| `com.thingclips.sdk.hardwareprotocol.bean.HDpResponse` / `HRequest` | Payload de Data Points |
| `com.thingclips.smart.android.hardware.IUDPBroadcastAidlInterface` | Broadcast UDP via AIDL |
| `com.thingclips.smart.android.hardware.IUDPMonitorAidlInterface` | Monitor UDP via AIDL |
| `com.thingclips.smart.interior.hardware.ThingLocalNormalControlBean` | Controle local normal |

## Fluxo de controle local (observado)

1. Descoberta UDP popula `HgwBean` (`gwId`, `ip`, `version`, …).
2. `DevTransferService.buildConnect(hgwBean, localKey, netId)`:
   - se `version >= 3.5` → `connectDeviceWithKey(..., LAN_PROTOCOL_VERSION_3_5, ...)`
   - senão → `connectDeviceWithKey(gwId, localKey, netId)`
   - em sucesso de connect → `startSwapKey(gwId, localKey)` (troca de chave / sessão)
3. Comando: `controlByBinary(devId, frameType, payload)` → `sendBytes`.
4. Versão ≥ 3.5 (ou ≥ 3.4 com `active == 2`) usa `sendBytes2`; caso contrário `sendBytes`.

## Cloud vs local

O app ainda usa nuvem (credenciais, schema de produto, pairing). **Controle local** após o device estar paired exige:

- `deviceId` / `gwId`
- `localKey` (obtida no pairing / API cloud uma vez)
- IP na LAN (descoberta UDP ou IP fixo)
- versão de protocolo anunciada pelo device (`HgwBean.version`)

O HAC deste repositório opera **só na LAN**, sem depender do app em runtime.
