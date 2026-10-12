# Dispositivos alvo

## 1. Fechadura (lock)

Entidade HA: `lock`.

DPs típicos Tuya (defaults no HAC; ajuste no config se o schema do seu modelo diferir):

| DP (default) | Código comum | Uso |
| --- | --- | --- |
| `1` | `lock_motor` / `switch` | trancar / destrancar (bool ou enum) |
| `2` | `open_inside` / status | estado reportado |
| `47` / `56` | `battery` / `residual_electricity` | bateria (se existir) |

O HAC trata:

- `lock.lock` / `lock.unlock` → escreve DP de motor
- estado a partir do DP de status (ou do mesmo DP se o device for só bool)

## 2. Interruptor: 2 luzes + 1 tomada

Um device físico, **três canais** booleanos → três entidades `switch` no HA (ou `light` + `switch`).

Defaults (gang switch Tuya clássico):

| Canal | DP default | Entidade sugerida |
| --- | --- | --- |
| Luz 1 | `1` (`switch_1`) | `switch.*_luz_1` |
| Luz 2 | `2` (`switch_2`) | `switch.*_luz_2` |
| Tomada | `3` (`switch_3` / `switch_usb` / outlet) | `switch.*_tomada` |

Se o teu schema usar outros IDs (ex. `switch_led_1`), mude no config flow.

## Credenciais necessárias (por device)

1. `device_id` (`gwId`)
2. `local_key`
3. `host` (IP) — ou discovery UDP
4. `protocol_version` (`3.3` / `3.4` / `3.5`)
5. mapa de DPs

Como obter `local_key` (uma vez, fora do HAC):

- Tuya IoT Platform / Cloud API do projeto onde o device está paired
- tools tipo tinytuya wizard / export do app (conforme política da tua conta)

Sem `local_key` o LAN encrypt falha (`localKey is empty` no SO).
