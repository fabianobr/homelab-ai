# Timestamps das mortes em background — reconstruídos, não gravados em arquivo

Achado do review do PR #36: os números "~13s", "~6s", "~10s", "~8s" citados no README para
as tentativas mortas não estavam em nenhum arquivo — vieram de observação feita durante a
sessão (comparar `request_start` do `timeline*.txt` contra o instante em que eu chequei o
estado logo após a notificação de morte), nunca salva em disco. Este arquivo reconstrói essa
observação com os timestamps reais que apareceram na conversa, para não deixar a afirmação sem
lastro.

**Importante:** `checked_at` é o momento em que eu rodei `date -u` para investigar, não o
instante exato da morte — a morte aconteceu em algum ponto entre `request_start` e
`checked_at`. Os números "~Xs" no README e no `docs/colibri.md` são um teto (a morte não
demorou mais que isso), não uma medição precisa.

| Tentativa | request_start (UTC) | checked_at (UTC) | teto observado |
|---|---|---|---|
| 2000 tok, 1ª vez (timeout 4800 + restart LiteLLM) | não registrado — a task morreu antes de `timeline3.txt` ser escrito, o único sinal foi 1 linha `GET /v1/models` no log do servidor | — | desconhecido, provavelmente segundos |
| 2000 tok, 2ª vez (timeout 4800, sem restart) | 2026-09-03T09:39:39.271612697Z | 2026-09-03T09:39:52.848479658Z | ~13s |
| 1300 tok (isolamento) | 2026-09-03T09:54:17.648051114Z | 2026-09-03T09:54:23.435561904Z | ~6s |
| 900 tok (replay exato do que funcionou) | 2026-09-03T09:57:47.15510449Z | 2026-09-03T09:57:57.647419526Z | ~10s |
| 200 tok (replay exato do que funcionou) | 2026-09-03T10:35:22.497085909Z | 2026-09-03T10:35:30.707898766Z | ~8s |

A conclusão da investigação (não é RAM/OOM, não é `colibri-serve.sh`, não é LiteLLM/timeout,
não é `max_tokens`/payload) não depende da precisão desses números — depende só de que todas
as cinco tentativas morreram antes de qualquer linha `v4_prefill` aparecer no log do servidor,
o que **está** registrado (ver `tail` do log citado nas respostas da sessão, não capturado em
arquivo aqui por não ter sido copiado para o repo — outra lacuna, ver "Próximos passos" no
`README.md`).
