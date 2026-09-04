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

Prompt usado nas duas: diff real combinado dos commits `5e5a9ad` + `66f978d` deste repo
(~14,4 KB, `usage.prompt_tokens: 4858`), pedindo review de bugs no `colibri-serve.sh`.
Script usado: `run.sh` / `run2.sh` (idênticos exceto o arquivo de request).

## Rodadas que NÃO completaram (achado principal desta sessão)

| Tentativa | max_tokens | O que mudou | Resultado |
|---|---|---|---|
| `request3.json` (1ª vez) | 2000 | timeout gateway 2400→4800 + restart do container LiteLLM | task em background morta ~13s após início, antes do prefill |
| `request3.json` (2ª vez) | 2000 | mesmo, sem restart desta vez | task morta ~6s após início |
| `request4.json` (isolamento) | 1300 | nada além do max_tokens | task morta ~6s após início |
| `request2.json` (replay exato) | 900 | nada — payload idêntico ao que funcionou | task morta ~10s após início |
| `request.json` (replay exato) | 200 | nada — payload idêntico à 1ª rodada bem-sucedida | task morta ~8s após início |

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

- `request*.json` — payloads enviados (prompt = diff real + max_tokens variando)
- `response*.txt` — respostas cruas do servidor (só as que completaram têm response)
- `timeline*.txt` — timestamps UTC de início/fim de cada tentativa
- `run*.sh` — scripts exatos usados para disparar cada tentativa
- `diff_combined.patch` — o diff real usado como corpo do prompt

## Próximos passos (para decidir em outra sessão)

1. **Rodar em foreground** (sem tarefa em background) — contorna o problema sem entender a
   causa, ao custo de bloquear a sessão ~20-30 min por chamada.
2. **Nova sessão** — o padrão "2 primeiras OK, resto morre" sugere algo por-sessão; não
   confirmado.
3. **Aceitar os dois dados já coletados** — já respondem a pergunta original (RAM
   desconfirmada, ~18-19 min de custo operacional pelo gateway); o truncamento afeta só a
   completude do texto de review, não a métrica de tempo.
