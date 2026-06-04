# Roadmap

## Fase 1 — Base funcional

- [x] Instalar LM Studio
- [x] Instalar Ollama
- [x] Conectar Open WebUI ao Ollama
- [ ] Corrigir FUSE/driver NVIDIA para LM Studio AppImage
- [x] Instalar Open WebUI
- [x] Conectar Open WebUI ao LM Studio
- [ ] Carregar modelo de chat no LM Studio
- [ ] Testar chat local

## Fase 2 — Acesso remoto

- [x] Instalar cloudflared
- [x] Criar Cloudflare Tunnel
- [x] Corrigir hostname/DNS do tunnel para ai.example.com
- [x] Configurar Cloudflare Access para user@example.com
- [x] Criar hostname/DNS do tunnel para media.example.com
- [ ] Configurar Cloudflare Access com MFA para media.example.com

## Fase 3 — Documentos e busca

- [ ] Configurar RAG no Open WebUI
- [ ] Criar coleções de documentos
- [ ] Configurar busca web
- [ ] Avaliar MCP Brave/Tavily

## Fase 4 — Imagem

- [x] Instalar ComfyUI
- [ ] Instalar modelo FLUX Schnell
- [ ] Testar geração de imagem
- [ ] Publicar ComfyUI via Cloudflare Access

## Fase 5 — Vídeo

- [ ] Instalar LTX Video
- [ ] Testar text-to-video
- [ ] Testar image-to-video
- [ ] Documentar presets para NVIDIA GPU 16GB

## Fase 6 — Automações

- [ ] Instalar n8n
- [ ] Criar primeiro workflow simples
- [ ] Integrar com webhook protegido
- [ ] Avaliar integração com Open WebUI

## Fase 7 — Agentes de código

- [ ] Configurar Continue.dev
- [ ] Configurar Codex/Claude Code/OpenCode
- [ ] Criar padrões para manutenção do projeto
