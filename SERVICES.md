# Serviços

## Estado desejado

| Serviço | Obrigatório | Inicialização | Porta | Observação |
|---|---|---|---:|---|
| Ollama | Sim | Docker Compose | 11434 | Backend único de modelos |
| Open WebUI | Sim | Docker Compose | 3000 | Interface principal |
| ComfyUI | Sim | Docker Compose | 8188 | Interface de imagem via Access |
| Cloudflare Tunnel | Sim | systemd | - | Exposição segura |
| LTX Video | Opcional | Docker | variável | Vídeo |
| n8n | Opcional | Docker Compose profile `optional` | 5678 | Automações |

## Ordem de instalação

1. Ollama (Docker)
2. Open WebUI (Docker)
3. ComfyUI (Docker)
4. Cloudflare Tunnel + Access
5. LTX Video
6. n8n
7. MCPs e ferramentas

## Modelos iniciais recomendados

- Qwen3 14B Q4_K_M
- Gemma 3 12B
- DeepSeek R1 Distill 14B
- Modelo leve auxiliar para tarefas rápidas

## Publicação atual

Serviços publicados via Cloudflare Access:

```text
https://ai.example.com  -> http://localhost:3000  (Open WebUI)
https://media.example.com -> http://localhost:8188  (ComfyUI)
https://flow.example.com  -> http://localhost:5678  (n8n)
```

E-mail permitido no Access:

```text
user@example.com
```

Ollama é acessado pelo Open WebUI via rede interna do Docker Compose:

```text
http://ollama:11434        (chat/completions)
http://ollama:11434/v1     (endpoint OpenAI-compatible)
```

## Paths de modelos (bind mounts)

Modelos ficam fora do Docker (muito volume de storage):

| Serviço | Path local | Path no container |
|---|---|---|
| Ollama | `/srv/homelab-ai/ollama` | `/root/.ollama` |
| ComfyUI | `/srv/homelab-ai/comfyui` | `/comfyui` |
