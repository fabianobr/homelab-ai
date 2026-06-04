# Arquitetura

## C4 L1 - Contexto

```mermaid
%%{init: {'theme': 'default'}}%%
C4Context
    title homelab-ai - System Context

    Person(user, "Fabiano", "Usa chat, agentes e geracao de imagem a partir de celular ou notebook.")

    System_Boundary(homelab, "homelab-ai") {
        System(ai_lab, "Servidor pessoal de IA", "Desktop Ubuntu com GPU NVIDIA executando interfaces e backends locais de IA.")
    }

    System_Ext(cf_access, "Cloudflare Access", "Autenticacao, MFA e politica de acesso.")
    System_Ext(cf_tunnel, "Cloudflare Tunnel", "Publica hostnames sem abrir portas no roteador.")

    Rel(user, cf_access, "Acessa", "HTTPS")
    Rel(cf_access, cf_tunnel, "Autoriza e encaminha", "Zero Trust")
    Rel(cf_tunnel, ai_lab, "Encaminha para servicos locais", "Tunnel")
```

## C4 L2 - Containers

```mermaid
%%{init: {'theme': 'default'}}%%
C4Container
    title homelab-ai - Container Diagram

    Person(user, "Fabiano", "Usuario remoto autorizado.")

    System_Ext(cf_access, "Cloudflare Access", "Login e MFA.")
    System_Ext(cf_tunnel, "Cloudflare Tunnel", "Publica hostnames.")

    Container_Boundary(host, "Desktop homelab - Ubuntu + NVIDIA GPU") {
        Container(open_webui, "Open WebUI", "Docker", "Interface de chat, RAG e ferramentas. :3000")
        Container(comfyui, "ComfyUI", "Python/aiohttp", "Geracao de imagem. :8188")
        Container(ollama, "Ollama", "Snap/systemd", "Backend de modelos locais. :11434")
        Container(lm_studio, "LM Studio", "Desktop app", "Backend OpenAI-compatible. :1234")
        ContainerDb(open_webui_data, "Open WebUI data", "Docker volume", "Configs, usuarios, historico e cache.")
        ContainerDb(local_models, "Modelos locais", "GGUF / safetensors", "Modelos para Ollama, LM Studio e ComfyUI.")
        Container(n8n, "n8n", "Docker", "Automacoes opcionais. :5678")
        Container(ltx, "LTX Video", "Docker/Manual", "Geracao de video. Opcional.")
    }

    Rel(user, cf_access, "Acessa", "HTTPS")
    Rel(cf_access, cf_tunnel, "Autoriza", "Cloudflare Access")
    Rel(cf_tunnel, open_webui, "ai.example.com", "HTTP :3000")
    Rel(cf_tunnel, comfyui, "media.example.com", "HTTP :8188")
    Rel(cf_tunnel, n8n, "flow.example.com", "HTTP :5678")

    Rel(open_webui, ollama, "Lista modelos e envia prompts", "HTTP :11434")
    Rel(open_webui, lm_studio, "Lista modelos e envia prompts", "OpenAI-compatible :1234")
    Rel(open_webui, open_webui_data, "Le e grava", "SQLite/files")

    Rel(ollama, local_models, "Carrega modelos", "GGUF")
    Rel(lm_studio, local_models, "Carrega modelos", "GGUF")
    Rel(comfyui, local_models, "Carrega checkpoints", "safetensors")

    Rel(open_webui, n8n, "Integra automacoes", "HTTP opcional")
    Rel(open_webui, ltx, "Integra video", "HTTP opcional")
```

## Interfaces

| Servico | Porta local | Exposicao | Uso |
|---|---:|---|---|
| Open WebUI | 3000 | `https://ai.example.com` via Cloudflare Access | Interface principal |
| ComfyUI | 8188 | `https://media.example.com` via Cloudflare Access | Geracao de imagem |
| n8n | 5678 | `https://flow.example.com` via Cloudflare Access | Automacoes |
| Ollama | 11434 | Interno | Backend do Open WebUI |
| LM Studio | 1234 | Interno | Backend OpenAI-compatible do Open WebUI |
| LTX Video | variavel | Interno/opcional | Video |

## Politica de Publicacao

Servicos publicados por dominio via Cloudflare Access:

```text
https://ai.example.com  -> http://localhost:3000
https://media.example.com -> http://localhost:8188
https://flow.example.com  -> http://localhost:5678
```

Ollama, LM Studio, n8n, Docker e SSH nao devem ser publicados diretamente. Ollama e LM Studio sao backends internos do Open WebUI.
