# CarWatch

Pipeline semanal de detecção de lançamentos automotivos globais a partir de
fontes públicas (feeds de imprensa, mídia especializada, Google News),
classificados via Claude Haiku e publicados no Telegram.

Ver `SPEC.md` (especificação original) e `DESIGN.md` (adaptação para
execução semanal — leia os dois; `DESIGN.md` prevalece em conflitos).

## Dependências

- **Docker + Docker Compose** (roda `db` e `app` como containers)
- **Chave de API Anthropic** (`ANTHROPIC_API_KEY`) — usa `claude-haiku-4-5-20251001`
- **Bot do Telegram dedicado** (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`) —
  não é o bot Hermes usado pelos outros agentes deste repositório
  (DESIGN.md §4)

## Setup (uma vez, vale para rodar e para testar)

`.env` é gitignored — um clone novo só tem `.env.example`. Copie antes de
qualquer outra coisa:

```bash
cd ~/homelab-ai/agents/carwatch
cp .env.example .env   # preencher as chaves
```

## Como rodar manualmente

```bash
cd ~/homelab-ai/agents/carwatch
./run.sh
```

## Testes

Precisam de Postgres real (não são mockados — apenas HTTP é mockado via
`respx`, seguindo SPEC.md §20). Faça o setup acima (`cp .env.example .env`)
antes:

```bash
cd ~/homelab-ai/agents/carwatch
docker compose up -d db
docker compose exec db psql -U carwatch -d carwatch -c "CREATE DATABASE carwatch_test;"  # uma vez
python3 -m pytest -q
```

Cobertura mínima exigida (SPEC.md §20): 90% em `fetcher.py`, `dedupe.py`
(Fase 2), `prefilter.py`.

## Agendamento (systemd timer)

Executa todo **sábado às 09:00**:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/carwatch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now carwatch.timer

# Verificar:
systemctl --user list-timers carwatch.timer
```

`Persistent=true` garante catch-up se a máquina estava desligada no
horário agendado.

## Servindo o feed Atom

`publish` escreve `data/feed.atom` a cada execução — `data/` é montado do
host (`docker-compose.yml`) porque `docker compose run --rm app` destrói o
filesystem do container ao sair; sem esse mount o arquivo nunca chegaria
ao host. Aponte seu nginx/static host/Cloudflare para
`~/homelab-ai/agents/carwatch/data/feed.atom` (SPEC.md §16: "servido por
nginx ou qualquer static host, sem framework web") e ajuste `ATOM_FEED_URL`
no `.env` pra URL pública real.

## Riscos operacionais conhecidos

- `llm/classify.py` usava `max_tokens=300` por lote de 20 itens (valor exato
  do SPEC.md §10). A revisão final da Fase 1 mostrou que essa combinação é
  aritmeticamente impossível — um lote cheio precisa de ~600–800 tokens de
  saída, truncava o JSON no meio e o lote inteiro era descartado (e
  re-cobrado na semana seguinte). Corrigido para `max_tokens=1200` com
  `BATCH_SIZE=8`, mais split-and-retry do lote quando o parse falha.
- `config/keywords.yaml` substitui os termos `stock`/`shares` do SPEC.md §9
  por frases financeiras (`stock price`, `shares fall`, …): a palavra solta
  vetava anúncios legítimos com "now in stock".
- `config/brands.yaml` traz domínios de press room de melhor esforço;
  `carwatch probe` é quem valida de verdade em runtime.

## Definição de pronto (SPEC.md §22) — revisar após 2 execuções semanais

- [ ] Detecta ≥90% dos lançamentos das 40 marcas principais (checar manualmente contra Motor1/Autocar)
- [ ] Taxa de duplicata no Telegram < 5%
- [ ] Custo LLM < US$15/mês (`carwatch stats` → `month_to_date_cost_usd`)
- [ ] Nenhum domínio em `status='blocked'` por culpa do fetcher (não por bloqueio real do site)
- [ ] Intervenção manual ≤ 30 min/semana (tempo gasto em `carwatch review` + confirmar aposentadorias)
