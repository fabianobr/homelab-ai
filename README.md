# homelab-ai

Laboratório pessoal de IA local para rodar chat, agentes, RAG, geração de imagem, vídeo e automações em um desktop Ubuntu com GPU NVIDIA.

## Objetivo

Transformar o desktop `homelab` em um servidor pessoal de IA acessível remotamente com segurança.

Stack principal:

- Ollama
- LM Studio
- Open WebUI
- Cloudflare Tunnel + Cloudflare Access
- ComfyUI
- LTX Video
- n8n

## Estrutura

```text
homelab-ai/
├── README.md
├── ARCHITECTURE.md
├── INVENTORY.yaml
├── SERVICES.md
├── SECURITY.md
├── STANDARDS.md
├── ROADMAP.md
├── docker/
│   └── docker-compose.yml
├── infra/
│   └── cloudflare/
├── scripts/
├── agents/
└── docs/
```

## Subir serviços Docker

```bash
cd docker
docker compose up -d open-webui
```

O `n8n` é opcional nesta fase e só deve ser iniciado explicitamente:

```bash
cd docker
docker compose --profile optional up -d n8n
```

## Validar ambiente

```bash
bash ../scripts/healthcheck.sh
```

## Aplicar configuração de sistema

Algumas mudanças ficam fora do repositório e exigem root:

```bash
sudo bash scripts/apply-system-config.sh
```

Esse script configura o bind do Ollama Snap, instala o ingress do Cloudflare Tunnel e reinicia os serviços afetados.

## Acesso remoto

O acesso remoto público permitido passa pelo Cloudflare Access:

```text
https://ai.example.com
https://media.example.com
```

Ollama e LM Studio sao backends internos do Open WebUI e nao devem ter hostnames publicos.

## Testar serviços no ar

### 1. Healthcheck geral

```bash
cd /home/user/homelab-ai
bash scripts/healthcheck.sh
```

Resultado esperado: Open WebUI, LM Studio, ComfyUI, Docker Compose, Cloudflare e GPU com `[OK]`. O `n8n` pode aparecer como `[SKIP optional]`.

### 2. Open WebUI local

```bash
curl -I http://localhost:3000
```

Abra no navegador:

```text
http://localhost:3000
```

Resultado esperado: tela inicial do Open WebUI.

Observação operacional: o Open WebUI deve escutar apenas em `127.0.0.1:3000` para Cloudflare. Ele não deve escutar em `0.0.0.0:3000`.

### 3. Open WebUI via Cloudflare

Abra no navegador:

```text
https://ai.example.com
```

Resultado esperado: Cloudflare Access solicita login/MFA e depois abre o Open WebUI.

### 4. LM Studio API

```bash
curl http://localhost:1234/v1/models
```

Resultado esperado: JSON com modelos carregados. Para chat no Open WebUI, carregue um modelo conversacional no LM Studio.

Não teste LM Studio pelo domínio público. Ele não deve responder em `https://ai.example.com`; esse domínio é apenas para Open WebUI.

### 5. Ollama API

```bash
curl http://localhost:11434/api/tags
```

Resultado esperado: JSON com modelos Ollama. O serviço deve escutar em `0.0.0.0:11434` no host para ser alcançável pelo Docker, mas não deve ser publicado no Cloudflare nem no roteador.

### 6. Conectividade Open WebUI -> backends

```bash
docker exec open-webui python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=5).read().decode()[:500])"
docker exec open-webui python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:1234/v1/models', timeout=5).read().decode()[:500])"
```

Resultado esperado: os mesmos JSONs de modelos vistos no host.

### 7. ComfyUI

```bash
curl -I http://localhost:8188
```

Abra no navegador:

```text
http://localhost:8188
```

Resultado esperado: interface do ComfyUI local. Acesso remoto separado:

```text
https://media.example.com
```

Esse hostname deve passar pelo Cloudflare Access com MFA para `user@example.com`.

### 8. GPU NVIDIA

```bash
nvidia-smi
```

Resultado esperado: NVIDIA GPU listada, com uso de VRAM/processos quando LM Studio ou ComfyUI estiverem carregando modelos.

### 9. Docker e Compose

```bash
docker ps
docker compose version
```

Resultado esperado: container `open-webui` saudável e Compose v2 instalado.

## Regra de ouro

Nunca exponha diretamente na internet:

- Ollama `11434`
- LM Studio `1234`
- n8n `5678`
- Docker socket

Use Cloudflare Access para os hostnames publicados: Open WebUI e ComfyUI.
