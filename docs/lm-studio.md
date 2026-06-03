# LM Studio

## Papel

Backend local de modelos LLM.

## Porta

```text
1234
```

## Endpoint

```text
http://localhost:1234/v1
```

## Configuração recomendada

- Flash Attention: ligado
- KV Cache na GPU: ligado
- Contexto inicial: 8k a 16k
- Modelos Q4_K_M para 16GB VRAM
- Evitar contexto gigante sem necessidade

## Healthcheck

```bash
curl http://localhost:1234/v1/models
```

## Observação

LM Studio deve ser acessado pelo Open WebUI, não diretamente pela internet.
