# Evidence REA (IDs)

Análise estática. Confidence: `observed` / `derived` conforme cada operação.

## Android (JADX)

| Operação | Evidence ID | Achado |
| --- | --- | --- |
| `inspect_android_package` | `ev_23302c827458a0c4035f30c7efd28184e1e5c4286caa3223f35fcfb590365d7c` | package `com.tuya.smart` 7.11.4, 78129 classes |
| `inspect_android_class` DevTransferService | `ev_89c8183104fbd53dc3d8b4a4171ac5f28bea08c32dbe2693d8711c79dac1c643` | serviço LAN |
| `inspect_android_method` buildConnect | `ev_00304fd63f5aeafd1521847891d0056ab11d50288feb4b839a8b24a2c053759f` | 3.5 + swap key |
| `inspect_android_method` controlByBinary | `ev_838aaf5ca38aa93a5fff6b64074928ed2f98a30f6f5ec4a9b4553ac7d6906d2c` | frame type + send |
| `inspect_android_method` sendBytes | `ev_4b8aa51fbaa93379b1f3c4ab121a2afad858d850c8e17117d1f5bc739b3121c9` | sendBytes vs sendBytes2 |
| `inspect_android_class` HgwBean | `ev_45c6fa9fe6d42b18f091f5835dd622e70f0d41ad4b52b0d83267ad1143fb3940` | discovery fields |
| `inspect_android_class` ThingNetworkInterface | `ev_d3add099ac888d0c62284599607904e110373360f1d3f33ccfabba1f18516c0a` | LAN API |
| `inspect_android_class` FrameTypeEnum | `ev_5b4cd4518aadf520c91c3db22b1f60282ef8bae099cb94488c30818cdd026030` | command names |
| `inspect_android_class` ThingNetworkApi | `ev_b6a6462a3cac448ac36b29d3fbc213841812453c08b4516bb862201277188a79` | JNI surface |
| `inspect_android_method` ThingNetworkApi.`<clinit>` | `ev_04dd01d0c6f0470cee2c24f45c29a4edb3d28e3261905d9180ba7aa54988d92f` | `loadLibrary("network-android")` |

## Native (Ghidra)

| Operação | Evidence ID | Achado |
| --- | --- | --- |
| `binary_overview` | `ev_346126297d87b572919a497876129250fa08ce2ec4432583da6d664965d496e2` | 5276 procedures, arm64 |
| `search_procedures` JNI | `ev_f3602bb2373ffc0801eead92c75825f2d2c6eba1a95f145e006f1086279ada1e` | ThingNetworkApi_* |
| `search_strings` protocol | `ev_23ba9f652c76dc98df92620202a0a4d47a3978d16814d63745c39267f02bcb44` | v3.5 / localKey / GCM |
| `search_strings` listenUDP | `ev_3841b464f004c2670f559152aa3fee92c2ee4f83e9be33bef456818c9015aa2b` | ListenUDP / BizLogicService |
| `analyze_function` initUdpSession | (retained session; large pseudocode) | UDP session + key validation |

Bundle exportado (sessão parcial): `.rea-work/evidence-bundle.json`.

## Unknowns restantes

- Ints exatos de cada `FrameTypeEnum` no `<clinit>` (JADX sem body).
- Wire format byte-a-byte completo do frame 3.5 no SO (só logs/headers observados).
- Schema DP **específico** da tua fechadura/interruptor (requer device real ou export cloud).
