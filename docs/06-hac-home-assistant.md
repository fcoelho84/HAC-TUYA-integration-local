# HAC — `tuya_local_lan`

Integração custom em `custom_components/tuya_local_lan/`.

## Instalação

1. Copia `custom_components/tuya_local_lan` para a pasta `custom_components` do Home Assistant.
2. Reinicia o HA.
3. **Configurar** → **Dispositivos e serviços** → **Adicionar integração** → **Tuya Local LAN**.

## Configuração

Por device:

- Nome
- Device ID (`gwId`)
- Local key
- IP / host
- Protocolo: `3.3` | `3.4` | `3.5`
- Tipo: `lock` | `multi_switch`
- DPs (defaults editáveis)

### multi_switch (2 luzes + tomada)

Cria 3 entidades `switch` com DPs `1`, `2`, `3` por default.

### lock

Cria 1 entidade `lock` com DP de comando/status configurável.

## Discovery opcional

Na UI há opção de escanear UDP (portas 6666/6667) na subnet do HA para preencher IP/version. Ainda precisas da `local_key`.

## Limitações

- Sem cloud no runtime do HAC.
- Devices offline / key errada → unavailable.
- Protocolo 3.5 session swap: implementação alinhada ao fluxo tinytuya; se o teu firmware divergir, reporta versão + captura.
