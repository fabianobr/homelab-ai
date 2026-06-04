# Serviços

## Estado desejado

| Serviço | Obrigatório | Inicialização | Porta | Observação |
|---|---|---|---:|---|
| Ollama | Sim | Snap/systemd | 11434 | Backend interno do Open WebUI |
| LM Studio | Sim | Manual ou systemd | 1234 | Backend OpenAI-compatible interno |
| Open WebUI | Sim | Docker Compose | 3000 | Interface principal |
| Cloudflare Tunnel | Sim | systemd | - | Exposição segura |
| ComfyUI | Sim | Manual/Docker | 8188 | Interface de imagem via Access |
| LTX Video | Opcional | Manual/Docker | variável | Vídeo |
| n8n | Opcional | Docker Compose profile `optional` | 5678 | Automações |

## Ordem de instalação

1. Ollama
2. LM Studio
3. Open WebUI
4. Cloudflare Tunnel + Access
5. ComfyUI
6. LTX Video
7. n8n
8. MCPs e ferramentas

## Modelos iniciais recomendados

- Qwen3 14B Q4_K_M
- Gemma 3 12B
- DeepSeek R1 Distill 14B
- Modelo leve auxiliar para tarefas rápidas

## Publicação atual

Serviços publicados via Cloudflare Access:

```text
https://chat.ai.example.com  -> http://localhost:3000  (Open WebUI)
https://media.ai.example.com -> http://localhost:8188  (ComfyUI)
https://flow.ai.example.com  -> http://localhost:5678  (n8n)
```

E-mail permitido no Access:

```text
user@example.com
```

Ollama e LM Studio ficam internos e sao acessados pelo Open WebUI com:

```text
http://host.docker.internal:11434
http://host.docker.internal:1234/v1
```
