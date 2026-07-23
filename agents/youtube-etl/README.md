# YouTube ETL — Mercado Automotivo

Pipeline ETL semanal em **n8n** que monitora canais de YouTube do mercado
automotivo (ex.: Brian Pasch, Autoline Network), extrai as legendas dos
vídeos novos via **yt-dlp** (sem chave/cota — roda dentro do próprio
container n8n), estrutura os dados com **Ollama local (`llama3.2`)** e entrega:

- um **relatório markdown** por execução em `reports/YYYY-MM-DD-youtube-etl.md`;
- um **resumo via Telegram** (bot Hermes).

Diferente dos agents irmãos (`weekly-sdlc-research`, `weekly-cost-benefit`),
que são scripts Python agendados por cron/systemd, este vive como workflow
dentro do n8n — o agendamento é o Schedule Trigger do próprio workflow.

## O que faz

```
Cron (segunda 08:00) / Webhook manual (POST /webhook/youtube-etl-run)
  → Config Canais            (channelIds + uploadsPlaylistId derivado + validação de env vars)
  → YouTube Data API v3      (playlistItems.list na playlist de uploads; filtro de 7 dias no Code node)
  → Extrair VideoIds         (1 item por vídeo; falhas de API e fora-da-janela viram rodapé)
  → Agrupar VideoIds         (junta os ids extraídos num csv só, 1 item)
  → YouTube Data API v3      (videos.list?part=statistics — views/likes de até 50 vídeos, 1 chamada)
  → Mesclar Estatisticas     (views/likes de volta em cada vídeo, por videoId)
  → yt-dlp (Execute Command) (legenda .vtt em inglês; sem legenda → pula)
  → Ollama /api/chat         (llama3.2, format: json — saída JSON forçada)
  → Validar JSON             (parse + schema; inválido → rodapé, não derruba)
  → Montar Relatório         (ordenado por views desc; markdown + resumo Telegram)
  → Gravar em reports/       (volume montado no container)
  → Telegram (Hermes)
```

O relatório apresenta os vídeos em ordem decrescente de **views** (não mais
agrupados por canal) — o vídeo mais assistido da semana vem primeiro,
independente do canal. Cada vídeo mostra `views` e `likes` (quando o criador
não os oculta; nesse caso vira `—`).

`search.list?channelId=...` está bloqueado nesta chave (e aparentemente em chaves de API
"puras" em geral) com `403 accountDelegationForbidden` — bug/restrição do lado do Google,
não deste projeto. `playlistItems.list` na playlist de uploads do canal (`UU` + o `channelId`
sem o prefixo `UC`) contorna o problema e de quebra custa **1 unidade** em vez de 100.

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
- **Chave da YouTube Data API v3** (Google Cloud Console; `playlistItems.list`
  custa 1 unidade/chamada — ~1 chamada por canal por semana, quota diária
  padrão de 10.000)
- **yt-dlp** dentro do container n8n — a imagem oficial não traz o binário;
  este repo builda uma variante custom (`infra/docker/n8n/Dockerfile`, ver
  "Transcrição via yt-dlp" abaixo). `docker compose build n8n` antes do
  primeiro `up`.
- **Bot Telegram Hermes** (token já usado pelos outros agents, em `~/.hermes/.env`)

## Como importar e rodar

```bash
cd ~/homelab-ai

# 1. Permissão do diretório de relatórios (n8n roda como uid 1000)
sudo chown 1000:1000 agents/youtube-etl/reports

# 2. Buildar a imagem do n8n com yt-dlp e subir os serviços
cd infra/docker
docker compose build n8n
docker compose --profile media-pipeline --profile optional up -d ollama n8n

# 3. Importar e publicar o workflow
cd ../../
./agents/youtube-etl/import-workflow.sh
```

No nó **Config Canais**, a lista `CANAIS` já vem versionada no JSON — edite
direto no arquivo (ou na UI) para adicionar/remover canais; não precisa mais
de placeholder.

**Rodar manualmente** (sem esperar a segunda-feira), via o trigger de webhook
que o workflow já expõe:

```bash
curl -X POST http://localhost:5678/webhook/youtube-etl-run
```

Dispara a execução real (consome quota da YouTube API; yt-dlp não tem cota
própria). Para inspecionar o resultado sem UI, veja a execução mais recente
direto no banco do n8n (`docker exec n8n` não tem `sqlite3`; copie o arquivo
com `docker cp n8n:/home/node/.n8n/database.sqlite …` — inclua os arquivos
`-wal`/`-shm` juntos, senão a leitura fica desatualizada por causa do WAL do
SQLite).

## Configuração

### Credenciais (env vars do container n8n)

Os nós leem as chaves via `$env.*`. Defina no `.env` **untracked** de
`infra/docker/` (placeholders nos `.env*.example` da raiz; o token do Telegram
é o mesmo do `~/.hermes/.env`):

```bash
YOUTUBE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Requisitos, já configurados no `docker-compose.yml` do compose deste repo:

- `HOMELAB_ROOT` apontando para a raiz do clone (usado pelo volume de relatórios).
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` — a partir do n8n 2.23 o default passou a
  **bloquear** `$env` em Code nodes (nome da flag mudou, sem o sufixo `_JS`).
- `N8N_RESTRICT_FILE_ACCESS_TO=/data/youtube-etl/reports` — o default do n8n
  restringe nós Read/Write File a `~/.n8n-files`; sem isso, o nó `Gravar
  Relatorio` falha com "is not writable" mesmo com permissão de sistema de
  arquivos correta.
- `NODES_EXCLUDE=[]` — o n8n desabilita o nó **Execute Command** por padrão
  desde a v2 (hardening; junto com `localFileTrigger`). O nó `Obter
  Transcricao (yt-dlp)` depende dele. Sem essa flag, o workflow falha ao
  ativar com `Unrecognized node type: n8n-nodes-base.executeCommand`.

### Parâmetros do pipeline (nó Config Canais)

- `CANAIS`: lista de `{channelId, channelName}` — não é segredo, fica
  versionada no JSON do workflow.
- `DIAS_JANELA`: 7 (semanal). Para bi-semanal: 14 + `weeksInterval: 2` no
  Schedule Trigger.
- `MAX_VIDEOS_POR_CANAL`: 3. Teto dos vídeos mais recentes analisados por
  canal a cada rodada. Não é mais uma proteção de cota paga (yt-dlp não tem
  cota), mas continua valendo como limite de custo de GPU/tempo: 6 canais
  postando quase diariamente sem teto geram dezenas de chamadas ao Ollama
  numa única rodada semanal.

### Transcrição via yt-dlp

Primeira versão deste pipeline usava a API `youtube-transcript3` (RapidAPI).
Na prática, o plano gratuito (**100 chamadas/mês**) zerou numa única execução
real (46 vídeos, 6 canais que postam quase diariamente) — não dava nem para
uma rodada semanal. Trocado por **yt-dlp** rodando dentro do próprio
container n8n via nó **Execute Command**: baixa só a legenda automática em
inglês (`--skip-download --write-auto-sub --sub-format vtt`), sem cota nem
chave de API. O nó `Montar Prompt Ollama` faz o parse do `.vtt` (remove
timestamps, tags inline e linhas consecutivas repetidas) antes de montar o
prompt.

Trade-off: yt-dlp depende do extractor do YouTube, que quebra ocasionalmente
quando o Google muda algo no lado deles — a correção geralmente sai rápido
upstream, mas exige `docker compose build --no-cache n8n` para pegar a versão
nova (o Dockerfile pina `latest` de propósito, ver comentário nele). Também
existe risco (baixo, mas real) de bloqueio temporário por IP se o volume de
chamadas crescer muito; não observado neste uso pessoal de baixo volume.

## Agendamento

Schedule Trigger interno: **toda segunda-feira às 08:00** (uma hora antes do
`weekly-sdlc-research`, que roda às 9h — sem disputa de GPU). O n8n precisa
estar de pé no horário; diferente dos systemd timers dos outros agents, não há
catch-up se o container estiver parado.

O workflow também tem um segundo trigger, `Trigger Manual (Webhook)`, ligado
ao mesmo `Config Canais` — serve só para disparar uma execução sob demanda
(`POST /webhook/youtube-etl-run`, ver seção "Como importar e rodar"). Não
substitui o Schedule Trigger, só evita depender da UI para testar.

## Relatórios

```
agents/youtube-etl/reports/YYYY-MM-DD-youtube-etl.md
```

Um arquivo por execução (gitignored, como nos demais agents). O diretório é
montado no container n8n em `/data/youtube-etl/reports` via compose.

## Testes

```bash
node agents/youtube-etl/tests/test-workflow.js
```

Executa o JavaScript real dos 5 Code nodes do workflow (extraído do próprio
JSON) com respostas simuladas para os nós HTTP e o Execute Command (yt-dlp),
cobrindo: caminho feliz, canal com erro de API, vídeo sem legenda,
JSON/schema inválido do modelo, semana vazia, credencial ausente (fail-fast)
e truncamento de transcrição longa. Não precisa de n8n, Ollama, yt-dlp nem
chaves — só Node.js.

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
escalabilidade de consumo.
