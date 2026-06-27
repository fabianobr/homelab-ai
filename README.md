# homelab-ai

Lab pessoal para medir o alcance real de LLMs no ciclo de desenvolvimento de software —
o que funciona, o que não funciona, com números. Desktop Ubuntu com GPU NVIDIA RTX 5060 Ti 16GB.

## Trilhas

| | Trilha | O que é |
|---|---|---|
| 🏗️ | [`infra/`](infra/) | Docker Compose, scripts, Cloudflare Tunnel/Access, arquitetura do homelab |
| 🔬 | [`research/sdlc-agentico/`](research/sdlc-agentico/) | Pesquisa: 27+ ferramentas avaliadas, fases do SDLC, backlog com métricas |
| 🚀 | [`products/sdlc-hibrido/`](products/sdlc-hibrido/) | Pipeline flagship: LLM local + cloud, $0.04–0.07 por feature |
| 📦 | [`products/marketplace/`](products/marketplace/) | Mercado Loop — primeiro app não-toy gerado pelo pipeline |

## Aprendizados em destaque

- **$0.04 – $0.07 por feature** com roteamento híbrido (Ollama local + Claude Sonnet para alta
  ambiguidade) vs $0.50–2.00 tudo-cloud ou $0 + mais fixes manuais tudo-local.
- **TDD Invertido elimina circularidade:** gerar testes *a partir da spec* (sem ver código) e
  código *a partir dos testes* (sem escrever testes) impede que o mesmo modelo erre da mesma
  forma nos dois artefatos. Resultado: 6/7 testes passando sem fix manual no PoC.
- **Modelos locais de 14–32B cobrem ~80% dos casos cotidianos.** O gap real está em raciocínio
  multi-arquivo complexo e planejamento de longo horizonte — nesses pontos, modelos frontier
  (Claude Sonnet) compensam o custo.
- **n8n como orquestrador funciona**, com um caveat: o sandbox JS do n8n 2.23.3 bloqueia `fetch()`
  em Code nodes. Todas as chamadas externas precisam de HTTP Request nodes (mais verboso, não bloqueia).

## Por onde começar

- **Subir o homelab:** [`infra/README.md`](infra/README.md)
- **Entender a pesquisa:** [`research/sdlc-agentico/README.md`](research/sdlc-agentico/README.md)
- **Usar o pipeline:** [`products/sdlc-hibrido/README.md`](products/sdlc-hibrido/README.md)
- **Ver um app gerado:** [`products/marketplace/README.md`](products/marketplace/README.md)

## Media Meme Pipeline

O contrato público está em [`infra/media-pipeline/contract.yaml`](infra/media-pipeline/contract.yaml)
e é versionado por tags SemVer exatas. A primeira release planejada é `v1.0.0`;
o pipeline não deve consumir `main`.

```bash
cp .env.media-pipeline.example .env
# Edite .env usando caminhos absolutos do seu workspace.
set -a; source .env; set +a
bash infra/scripts/prepare-media-pipeline.sh
docker compose --env-file .env -f infra/docker/docker-compose.yml \
  --profile media-pipeline up -d ollama comfyui
```

Esse profile contém somente Ollama e ComfyUI. n8n, Hermes e Telegram não são
iniciados. As portas permanecem em loopback. O preparo é idempotente, não usa
`sudo`, preserva modelos e outputs fora do Git e recusa checkouts com alterações
locais. Requisitos oficiais iniciais: Ubuntu, GPU NVIDIA com 16 GiB de VRAM,
Docker Compose, NVIDIA Container Toolkit com CDI e cerca de 100 GiB livres.

O bootstrap do repo `media-meme-pipeline` deve validar a tag antes de executar:

```bash
bash infra/scripts/check-media-pipeline-contract.sh \
  --expected-tag v1.0.0 --expected-contract 1
```

Veja [`infra/media-pipeline/RELEASING.md`](infra/media-pipeline/RELEASING.md)
para os gates de segurança e release.

## Stack principal

- Ollama · Open WebUI · ComfyUI · LTX Video · n8n · LiteLLM
- Cloudflare Tunnel + Access (acesso remoto seguro, sem abrir portas)
- GPU NVIDIA RTX 5060 Ti 16GB VRAM

## Segurança do repositório (repo público)

Este repositório é público no GitHub. Antes de qualquer commit:

```bash
# Instalar o hook (uma vez):
pip install pre-commit && pre-commit install

# Rodar manualmente:
pre-commit run --all-files
```

O hook usa [gitleaks](https://github.com/gitleaks/gitleaks). Nunca commite `.env`,
chaves de API, tokens ou IPs internos. Ver [`SECURITY.md`](SECURITY.md).
