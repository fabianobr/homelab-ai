# Evidência crua: teste de truncamento no `sdlc-review-local` (2026-09-03 a 2026-09-04)

Contexto: depois de confirmar (PR #35) que os ~18 min de latência de um prompt grande pelo
gateway não são causados por RAM, o pedido seguinte foi mostrar os dados crus (prompt, resposta,
timeline) sem interpretação, e depois tentar um `max_tokens` maior para não truncar a resposta.
Esta pasta é o registro bruto dessa tentativa.

**Resolvido em 2026-09-04 (rodada 7):** rodar fora de qualquer tarefa em background do Claude
Code contorna a morte sistemática das rodadas 3-6 — ver seção "Rodada 7" abaixo. A pendência
está fechada; a causa raiz continua atribuída à camada de background task do Claude Code, não
investigada mais a fundo por ser externa a este repositório.

## Rodadas que completaram

| Arquivo | max_tokens | timeout gateway | Resultado |
|---|---|---|---|
| `request.json` / `response_raw.txt` / `timeline.txt` | 200 | 2400s | ✅ HTTP 200, 1286,47s, `finish_reason: length` |
| `request2.json` / `response2_raw.txt` / `timeline2.txt` | 900 | 2400s | ✅ HTTP 200, 1911,47s, `finish_reason: length` |

Ambas truncaram (`finish_reason: length`) — a resposta do modelo não coube no limite de tokens
em nenhuma das duas. `response2_raw.txt` mostra o texto cortado no meio do "Bug 4" da review.

**Nota do review do PR #36:** o `time_total` do `curl -w` é impresso no stdout, não no arquivo
gravado por `-o` — então `response*_raw.txt` não contém essas métricas, e o número citado na
tabela acima não batia com nenhum arquivo commitado originalmente. `metrics.txt` (adicionado
depois do review) guarda o `time_total` real, recuperado do output da tarefa em background.

Prompt usado nas duas: diff real combinado dos commits `5e5a9ad` + `66f978d` deste repo
(~14,4 KB, `usage.prompt_tokens: 4858`), pedindo review de bugs no `colibri-serve.sh`.
Script usado: `run.sh` / `run2.sh` (idênticos exceto o arquivo de request).

## Rodadas que NÃO completaram (achado principal desta sessão)

| Tentativa | max_tokens | O que mudou | Resultado |
|---|---|---|---|
| `request3.json` via `run3.sh` (1ª vez) | 2000 | timeout gateway 2400→4800 + restart do container LiteLLM | task em background morta, sem timestamp registrado (`timeline3.txt` nunca chegou a ser escrito), antes do prefill |
| `request3.json` via `run3.sh` (2ª vez, sobrescreveu a 1ª) | 2000 | mesmo, sem restart desta vez | task morta, teto observado ~13s após início |
| `request4.json` via `run4.sh` (isolamento) | 1300 | nada além do max_tokens | task morta, teto observado ~6s após início |
| `request2.json` via `run5.sh` (replay exato) | 900 | nada — payload idêntico ao que funcionou | task morta, teto observado ~10s após início |
| `request.json` via `run6.sh` (replay exato) | 200 | nada — payload idêntico à 1ª rodada bem-sucedida | task morta, teto observado ~8s após início |

Os tempos "teto observado" vêm de `kill-timestamps.md` (adicionado depois do review do PR #36)
— são o intervalo entre `request_start` e o instante em que checei o estado após a notificação
de morte, não o timestamp exato da morte, que nenhum arquivo grava.

**Conclusão da investigação:** eliminado, um a um — não é o Colibrì (processo seguiu vivo e são
depois de cada morte), não é o `colibri-serve.sh` (script idêntico), não é o LiteLLM/timeout
(testado com e sem restart, 2400 e 4800), não é o `max_tokens`/payload (o replay exato de uma
rodada que tinha funcionado morreu do mesmo jeito), não é falta de RAM/OOM do host (`dmesg`,
`journalctl --user`, `journalctl` do sistema e `earlyoom` limpos nos três horários checados,
memória disponível 91%+ em todos).

O padrão que sobrou: **as duas primeiras tarefas em background desta sessão de chat completaram;
toda tarefa em background depois disso morreu em segundos**, sempre no mesmo ponto do ciclo
(logo após a linha `[V4] temperature 0.7 ignored` no log do servidor, antes de qualquer
`v4_prefill`). Isso aponta para a camada que gerencia tarefas em background do Claude Code
(fora do host, sem logs inspecionáveis daqui), não para nada neste repositório. Já reportado
como feedback de produto durante a sessão.

## Arquivos desta pasta

- `request*.json` — payloads enviados (prompt = diff real + max_tokens variando: 200, 900,
  2000, 1300 respectivamente para `request`/`request2`/`request3`/`request4`)
- `response*.txt` — respostas cruas do servidor (só as que completaram têm response)
- `timeline*.txt` — timestamps UTC de início (e fim, quando completou) de cada tentativa
- `metrics.txt` — `time_total`/`http_code` reais das duas rodadas que completaram (ausentes
  dos `response*.txt` porque `curl -w` escreve no stdout, não no arquivo de `-o`)
- `kill-timestamps.md` — reconstrução dos "tetos observados" de quanto tempo cada tentativa
  morta rodou, com o disclaimer de que não é medição exata
- `run*.sh` — scripts usados para disparar cada tentativa; `run.sh`/`run2.sh`/`run3.sh`/
  `run4.sh` correspondem 1:1 a `request.json`/`request2.json`/`request3.json`/`request4.json`;
  `run5.sh` e `run6.sh` são replays que reusam `request2.json` e `request.json` (comentado no
  topo de cada script). Todos usam `cd "$(dirname "$0")"`, então rodam de qualquer diretório.
  `run7.sh` é o único pensado para rodar fora do Claude Code (ver seção "Rodada 7") e tem
  lockfile próprio (`run7.lock`) contra execução concorrente.
- `diff_combined.patch` — o diff real usado como corpo do prompt (rodadas 1-6)
- `request7.json` / `response7_raw.txt` / `timeline7.txt` / `log7.txt` — payload, resposta,
  timestamps e log de execução da rodada 7

## Rodada 7 (2026-09-04) — resolvida rodando fora do Claude Code

`request7.json` (mesmo estilo de prompt, diff menor ~6 KB, `max_tokens: 4000`) via `run7.sh`,
disparado pelo usuário num terminal próprio com `nohup ... & disown` — fora de qualquer task
gerenciada por esta sessão de chat, que era o suspeito principal das mortes em segundos das
rodadas 3-6.

| | Resultado |
|---|---|
| HTTP | 200 |
| `finish_reason` | **`stop`** — primeira resposta completa, sem truncar |
| Tempo total (`timeline7.txt`, início→fim) | **1.330 s (~22 min 10 s)** |
| `usage` | `prompt_tokens: 2079`, `completion_tokens: 1081`, `total: 3160` |

**Confirma a opção 1 dos "próximos passos" originais:** rodar fora do gerenciamento de
background do Claude Code contorna o problema, ao custo de bloquear ~22 min por chamada — sem
precisar entender a causa raiz exata daquela camada.

Dois problemas apareceram na própria execução, não no Colibrì:

1. **O usuário disparou `run7.sh` duas vezes em sequência** (comando colado/executado 2x) —
   as duas cópias escreviam no mesmo `response7_raw.txt`, o que corromperia o arquivo ao
   terminar. Detectado a tempo (`ps aux`, dois PGIDs do mesmo PPID) e a cópia mais nova foi
   morta manualmente antes de concluir. Corrigido depois: `run7.sh` agora usa um lockfile
   (`run7.lock`, via `mkdir` atômico) que aborta uma segunda execução concorrente em vez de
   disputar arquivo.
2. **`metrics7.txt` nunca foi gerado** — repetição do mesmo erro que o review do PR #36 já
   tinha documentado (`curl -w` escreve no *stdout* do processo `curl`, não no arquivo do
   `-o`), agravado pelo `nohup ... > /dev/null` que o usuário usou para desacoplar do
   terminal: mesmo se a extração de `response7_raw.txt` funcionasse, o redirect já tinha
   descartado esse stdout. O tempo real só ficou disponível porque `timeline7.txt` (escrito
   pelo próprio script, não pelo `-w` do curl) registra início e fim à parte.

## Próximos passos

Nenhum pendente para esta investigação — ver "Resolvido" no topo. Se o custo de ~20-22 min por
chamada precisar cair, a via não explorada é investigar por que o modo serve do Colibrì é caro
nesse patamar independente de RAM (hipótese aberta em `docs/colibri.md`, não desta pasta).

## Limitações desta evidência (do review do PR #36)

- O log do servidor Colibrì (`~/.local/state/colibri/serve.log`) nunca foi copiado pra esta
  pasta — as citações a `v4_prefill`/`[V4] temperature ignored` nas respostas da sessão vêm de
  `tail` rodado ao vivo, não de um arquivo commitado aqui.
- Os timestamps de morte são tetos observados, não exatos — ver `kill-timestamps.md`.
- A 1ª tentativa com `request3.json` teve seu `timeline3.txt` sobrescrito pela 2ª — dado
  irrecuperável.
