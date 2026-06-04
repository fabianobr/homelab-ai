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

O Open WebUI acessa esse endpoint de dentro do container usando:

```text
http://host.docker.internal:1234/v1
```

Para chat, mantenha um modelo conversacional carregado no LM Studio. Um modelo de embedding sozinho valida o endpoint, mas nao atende conversa.

## Observação

LM Studio deve ser acessado pelo Open WebUI, não diretamente pela internet.

O domínio público `https://ai.example.com` não deve apontar para LM Studio. Valide a API localmente no host ou indiretamente pelo Open WebUI.
