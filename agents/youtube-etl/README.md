# YouTube ETL — Mercado Automotivo

Pipeline ETL semanal em **n8n** que monitora canais de YouTube do mercado
automotivo (ex.: Brian Pasch, Autoline Network), extrai as transcrições dos
vídeos novos, estrutura os dados com **Ollama local (`llama3.2`)** e entrega:

- um **relatório markdown** por execução em `reports/YYYY-MM-DD-youtube-etl.md`;
- um **resumo via Telegram** (bot Hermes).

Diferente dos agents irmãos (`weekly-sdlc-research`, `weekly-cost-benefit`),
que são scripts Python agendados por cron/systemd, este vive como workflow
dentro do n8n — o agendamento é o Schedule Trigger do próprio workflow.

## O que faz

```
Cron (segunda 08:00)
  → Config Canais            (lista de channelIds + validação de env vars)
  → YouTube Data API v3      (search.list: vídeos dos últimos 7 dias por canal)
  → Extrair VideoIds         (1 item por vídeo; falhas de API viram rodapé)
  → Transcript API (RapidAPI)(transcrição por vídeo; sem transcrição → pula)
  → Ollama /api/chat         (llama3.2, format: json — saída JSON forçada)
  → Validar JSON             (parse + schema; inválido → rodapé, não derruba)
  → Montar Relatório         (markdown + resumo Telegram)
  → Gravar em reports/       (volume montado no container)
  → Telegram (Hermes)
```

O JSON extraído por vídeo segue o schema:

```json
{
  "assunto_principal": "string",
  "demanda_estoque": "string ou null",
  "incentivos_subsidios": "string ou null",
  "metricas_performance": {
    "cvr_taxa_conversao": "string ou null",
    "ctr_cliques": "string ou null",
    "vendas_volume": "string ou null"
  },
  "insight_estrategico": "string"
}
```

Campos não mencionados no vídeo voltam como `null` (o system prompt proíbe
inferência/invenção).

## Resiliência

Erros parciais **não derrubam o run**: canal com erro na YouTube API, vídeo sem
transcrição e resposta do modelo com JSON/schema inválido são contabilizados no
rodapé "Execução" do relatório. Semana sem vídeo novo gera relatório e
notificação de "semana vazia".

## Dependências

- **n8n** (profile `optional` do compose em `infra/docker/`)
- **Ollama** (profile `media-pipeline`) com o modelo `llama3.2`:
  `docker exec ollama ollama pull llama3.2`
- **Chave da YouTube Data API v3** (Google Cloud Console; `search.list` custa
  100 unidades/chamada — ~1 chamada por canal por semana, quota diária padrão
  de 10.000)
- **Chave RapidAPI** assinada em uma API de transcrição (padrão do workflow:
  `youtube-transcript3.p.rapidapi.com`; para outra API, ajuste URL/host no nó
  `Obter Transcricao (RapidAPI)` — o parser aceita os formatos de resposta
  comuns `{transcript|data|text|content}` com raiz objeto)
- **Bot Telegram Hermes** (token já usado pelos outros agents, em `~/.hermes/.env`)

## Como importar e rodar

```bash
cd ~/homelab-ai

# 1. Permissão do diretório de relatórios (n8n roda como uid 1000)
sudo chown 1000:1000 agents/youtube-etl/reports

# 2. Subir os serviços
cd infra/docker
docker compose --profile media-pipeline --profile optional up -d ollama n8n

# 3. Importar e publicar o workflow
cd ../../
./agents/youtube-etl/import-workflow.sh
```

Depois, na UI (`http://localhost:5678`):

1. Abra o workflow **YouTube ETL — Mercado Automotivo**.
2. No nó **Config Canais**, substitua os placeholders `UC_SUBSTITUA_...` pelos
   channelIds reais (YouTube → canal → "Sobre" → "Compartilhar canal" →
   "Copiar ID do canal").
3. Rode manualmente com **Execute workflow** para validar antes de esperar a
   segunda-feira.

**Teste sem gastar quota:** pine (pin data) no nó `Buscar Videos (YouTube)` uma
resposta de exemplo da `search.list` e no nó `Obter Transcricao (RapidAPI)` um
transcript curto — o restante do fluxo roda 100% local (Ollama), custo zero.

## Configuração

### Credenciais (env vars do container n8n)

Os nós leem as chaves via `$env.*`. Defina no `.env` **untracked** de
`infra/docker/` (placeholders nos `.env*.example` da raiz; o token do Telegram
é o mesmo do `~/.hermes/.env`):

```bash
YOUTUBE_API_KEY=...
RAPIDAPI_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Requisitos: `HOMELAB_ROOT` apontando para a raiz do clone (usado pelo volume de
relatórios) e `N8N_BLOCK_ENV_ACCESS_IN_NODE_JS` **não** pode estar `true`
(o default do n8n permite `$env` em Code nodes).

### Parâmetros do pipeline (nó Config Canais)

- `CANAIS`: lista de `{channelId, channelName}` — não é segredo, fica
  versionada no JSON do workflow.
- `DIAS_JANELA`: 7 (semanal). Para bi-semanal: 14 + `weeksInterval: 2` no
  Schedule Trigger.

## Agendamento

Schedule Trigger interno: **toda segunda-feira às 08:00** (uma hora antes do
`weekly-sdlc-research`, que roda às 9h — sem disputa de GPU). O n8n precisa
estar de pé no horário; diferente dos systemd timers dos outros agents, não há
catch-up se o container estiver parado.

## Relatórios

```
agents/youtube-etl/reports/YYYY-MM-DD-youtube-etl.md
```

Um arquivo por execução (gitignored, como nos demais agents). O diretório é
montado no container n8n em `/data/youtube-etl/reports` via compose.

## Logs

- Aba **Executions** na UI do n8n (histórico por nó, com payloads)
- `docker logs n8n`

## Segurança

- O repo é público: chaves só em env vars/`.env` untracked, nunca no JSON do
  workflow.
- **Não exportar execuções nem re-exportar o workflow pela UI** depois de rodar:
  os dados de execução contêm a chave da YouTube API na URL da requisição.
- `pre-commit run --all-files` (gitleaks) antes de qualquer commit que toque
  nesta pasta.

## Evolução futura — RAG (não implementado)

Próximo passo natural: gravar transcrições limpas + JSONs num banco vetorial
(Qdrant no compose) com embeddings `nomic-embed-text` (já usados pelo
open-webui), transformando os alertas semanais num repositório consultável
("o que o Brian Pasch falou de CVR no último trimestre?"). Trade-off: mais
engenharia inicial (embeddings + upsert no fluxo) e manutenção moderada
(tamanho do banco, qualidade dos embeddings) em troca de altíssima
escalabilidade de consumo. Outra otimização documentada: trocar `search.list`
(100 unidades) por `playlistItems.list` da playlist de uploads (1 unidade) se a
quota da YouTube API apertar.
