# Serviços

## Estado desejado

| Serviço | Obrigatório | Inicialização | Porta | Observação |
|---|---|---|---:|---|
| LM Studio | Sim | Manual ou systemd | 1234 | Backend dos modelos |
| Open WebUI | Sim | Docker Compose | 3000 | Interface principal |
| Tailscale | Sim | systemd | - | VPN privada |
| Cloudflare Tunnel | Sim | systemd | - | Exposição segura |
| ComfyUI | Sim | Manual/Docker | 8188 | Imagem |
| LTX Video | Opcional | Manual/Docker | variável | Vídeo |
| n8n | Opcional | Docker Compose | 5678 | Automações |

## Ordem de instalação

1. LM Studio
2. Open WebUI
3. Tailscale
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
