# Serviços

## Estado desejado

| Serviço | Obrigatório | Inicialização | Porta | Observação |
|---|---|---|---:|---|
| LM Studio | Sim | Manual ou systemd | 1234 | Backend dos modelos |
| Open WebUI | Sim | Docker Compose | 3000 | Interface principal |
| Cloudflare Tunnel | Sim | systemd | - | Exposição segura |
| ComfyUI | Sim | Manual/Docker | 8188 | Imagem |
| LTX Video | Opcional | Manual/Docker | variável | Vídeo |
| n8n | Opcional | Docker Compose profile `optional` | 5678 | Automações |

## Ordem de instalação

1. LM Studio
2. Open WebUI
3. Cloudflare Tunnel + Access
4. ComfyUI
5. LTX Video
6. n8n
7. MCPs e ferramentas

## Modelos iniciais recomendados

- Qwen3 14B Q4_K_M
- Gemma 3 12B
- DeepSeek R1 Distill 14B
- Modelo leve auxiliar para tarefas rápidas

## Publicação atual

Somente o Open WebUI deve ser publicado via Cloudflare Access:

```text
https://ai.example.com -> http://localhost:3000
```

E-mail permitido no Access:

```text
user@example.com
```
