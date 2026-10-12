# HAC — `tuya_local_lan`

Integração custom em `custom_components/tuya_local_lan/`.

## Instalação (HACS)

Custom repository: URL do git → category Integration → instalar → reiniciar HA.

## Uso

1. **Adicionar integração** → **Tuya Local LAN** → confirmar.
2. Sem formulário de device ID / IP / token.
3. Scan UDP automático (6666/6667).
4. Auto-classifica:
   - 3 bool DPs → Luz 1, Luz 2, Tomada
   - DP de lock → entidade `lock`
5. Serviço `tuya_local_lan.rescan` para novo scan.

## Local key (sem cloud no runtime)

O tráfego LAN cifrado **exige** `local_key` (material do pairing). O HAC **não** pede token cloud.

Ordem de resolução automática:

1. Integrações já no HA (`tuya`, `localtuya`, `tuya_local`, …)
2. Arquivos locais em `/config`:
   - `devices.json` (tinytuya)
   - `tuya_local_lan/keys.json`
3. Se não achar key: device aparece, mas fica unavailable até a key existir num desses locais

Exemplo `/config/tuya_local_lan/keys.json`:

```json
{
  "DEVICE_ID_AQUI": "local_key_aqui",
  "OUTRO_ID": "outra_key"
}
```

## Limitações

- Sem `local_key` em lugar nenhum → controle LAN impossível (AES). Discovery de IP/ID ainda funciona.
- Devices offline → unavailable.
