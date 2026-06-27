---
description: Lança o runner Bash interativo do pipeline SDLC híbrido. Uso: /sdlc-hybrid <descrição do produto>
model: ollama/qwen3:8b
---

Execute exatamente este comando bash, sem criar TODOs, sem explorar arquivos, sem chamar subagentes, sem glob, sem plano e sem texto antes:

```bash
cd /home/fabiano/homelab-ai && ./products/sdlc-hibrido/tests/sdlc-hybrid-interactive.sh "$1"
```

Depois apenas retransmita a saída do script e respeite as pausas interativas dele.
