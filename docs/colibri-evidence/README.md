# Evidência crua: teste de truncamento no `sdlc-review-local` (2026-09-03)

Contexto: depois de confirmar (PR #35) que os ~18 min de latência de um prompt grande pelo
gateway não são causados por RAM, o pedido seguinte foi mostrar os dados crus (prompt, resposta,
timeline) sem interpretação, e depois tentar um `max_tokens` maior para não truncar a resposta.
Esta pasta é o registro bruto dessa tentativa — para não perder nada ao fechar a sessão, antes
de decidir (em outra sessão) como prosseguir.

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
- `diff_combined.patch` — o diff real usado como corpo do prompt

## Próximos passos (para decidir em outra sessão)

1. **Rodar em foreground** (sem tarefa em background) — contorna o problema sem entender a
   causa, ao custo de bloquear a sessão ~20-30 min por chamada.
2. **Nova sessão** — o padrão "2 primeiras OK, resto morre" sugere algo por-sessão; não
   confirmado.
3. **Aceitar os dois dados já coletados** — já respondem a pergunta original (RAM
   desconfirmada, ~18-19 min de custo operacional pelo gateway); o truncamento afeta só a
   completude do texto de review, não a métrica de tempo.

## Limitações desta evidência (do review do PR #36)

- O log do servidor Colibrì (`~/.local/state/colibri/serve.log`) nunca foi copiado pra esta
  pasta — as citações a `v4_prefill`/`[V4] temperature ignored` nas respostas da sessão vêm de
  `tail` rodado ao vivo, não de um arquivo commitado aqui.
- Os timestamps de morte são tetos observados, não exatos — ver `kill-timestamps.md`.
- A 1ª tentativa com `request3.json` teve seu `timeline3.txt` sobrescrito pela 2ª — dado
  irrecuperável.
