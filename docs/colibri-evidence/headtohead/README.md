# Head-to-head Claude vs Colibrì (2026-09-05) — incompleto

Objetivo: comparar qualidade de review, não só velocidade, entre `sdlc-review` (Claude) e
`sdlc-review-local` (Colibrì), no mesmo diff real (`a264ea7`, `agents/carwatch` — fix de
anchoring + case-folding).

## Lado Claude — concluído

`review_claude.md`: achou um bug real (os três `field_validator` novos em `models.py` fazem
só `.lower()`/`.upper()`, sem `.strip()` — inconsistente com o padrão já estabelecido no
mesmo arquivo), mais dois riscos não confirmados (idioma do anchor, acoplamento posicional
SQL↔tupla).

O gateway (`sdlc-review` via LiteLLM) não tem `ANTHROPIC_API_KEY` configurada
(`homelab.env`) — a review foi feita diretamente, sem passar pelo LiteLLM.

## Lado Colibrì — não concluído, duas falhas de infraestrutura

1. **1ª tentativa:** travou ~28 min em `activation allocation: out of memory` — o container
   `ollama` tinha um modelo carregado (`qwen3.8:27b-mtp-q4_K_M`) gerando ativamente, 13,1 GiB
   de VRAM. `docker restart ollama` liberou.
2. **2ª tentativa (após liberar a VRAM):** travou de novo, ~44 min, desta vez o próprio
   Colibrì sozinho (`deepseek_v4` a 15,5 GiB de VRAM) em `weight allocation: out of memory` /
   `matvec launch: out of memory`, sem failover para CPU.

Nenhuma resposta do modelo foi obtida. Detalhes e o que isso significa em
`docs/colibri.md`, seções "O Ollama também contende a VRAM" e "Sem esse concorrente, o
próprio Colibrì travou sozinho".

Decisão (2026-09-05): parar aqui em vez de tentar uma 3ª vez. Ver `req_colibri.json` /
`run_colibri.sh` / `log_colibri.txt` para reproduzir quando quiser retomar.
