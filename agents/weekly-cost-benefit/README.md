# Weekly Cost-Benefit Agent

Agente semanal irmão do `weekly-sdlc-research`: mesma mecânica de pesquisa
(SearXNG → DuckDuckGo → análise via Ollama local), mas com **output diferente** —
em vez de descobrir ferramentas novas, ele avalia o **custo-benefício dos
ambientes de desenvolvimento com LLMs publicados na web**.

## A pergunta que ele responde

Para cada setup publicado (ex.: "vibe coding com Claude Code", "rig local com
RTX 4090 + Ollama", "Cursor + Copilot"):

- **Custo:** quanto custa montar? CAPEX (comprar máquina) + OPEX
  (licença/assinatura/API/energia por mês)
- **Benefício:** qual a velocidade e a qualidade do software gerado? (notas 1–5)
- **Comparação:** tudo com hardware local (Ollama) **versus** tudo pagando
  licença (Anthropic Claude, OpenAI Codex, Google Antigravity, Cursor, Copilot)
- **Breakeven:** em quantos meses o investimento em hardware local se paga
  frente à assinatura equivalente
- **Veredito:** `local`, `paid` ou `hybrid`

## O que faz

1. Executa queries de busca pré-configuradas via SearXNG local (fallback: DuckDuckGo)
2. Lê o ledger existente para extrair setups já avaliados
3. Envia os resultados + a **tabela de preços de referência** (config.yaml) ao
   Ollama local (`qwen2.5-coder:14b`) para análise de custo-benefício
4. Gera um relatório semanal em `reports/YYYY-MM-DD-cost-benefit.md` com tabela
   comparativa e avaliações detalhadas
5. Adiciona as novas avaliações ao ledger em `research/sdlc-agentico/cost-benefit.md`
6. Notifica via Telegram (bot Hermes) com o resumo dos vereditos
7. Registra tudo em `cost-benefit.log`

## Dependências

- **Ollama** rodando em `http://localhost:11434` com pelo menos um modelo instalado
  - Preferencial: `qwen2.5-coder:14b`
  - Fallback: `llama3.2:latest`
- **Python 3.11+**
- **SearXNG** em `http://localhost:8080` (opcional — usa DuckDuckGo se indisponível)

## Como rodar manualmente

```bash
cd ~/homelab-ai
./agents/weekly-cost-benefit/run.sh
```

O script cria um virtualenv em `.venv/` na primeira execução e instala as dependências.

## Tabela de preços de referência

A análise é ancorada em `pricing_reference` no `config.yaml`: preços de
hardware local (CAPEX + energia) e de licenças pagas (US$/mês). **Atualizar
periodicamente** — preços de assinatura e de GPU mudam; o campo
`reference_date` marca a validade da tabela.

## Onde ficam os relatórios

```
agents/weekly-cost-benefit/reports/YYYY-MM-DD-cost-benefit.md
```

Um arquivo por execução, com data no nome.

## Como o ledger é atualizado

O agente lê `research/sdlc-agentico/cost-benefit.md`, extrai os nomes de setups
já avaliados, e adiciona apenas avaliações **novas** sob a seção
`## Setups avaliados`, agrupadas por data de análise.

A operação é **idempotente**: rodar duas vezes no mesmo dia não duplica entradas.

## Configuração

Edite `agents/weekly-cost-benefit/config.yaml` para:
- Adicionar/remover queries de busca
- Atualizar a tabela `pricing_reference` (licenças, hardware, energia, câmbio)
- Alterar o modelo Ollama
- Adicionar itens ao `known_evaluated` (nunca serão reavaliados)
- Ajustar a URL do SearXNG

## Agendamento (systemd timer)

Executa toda segunda-feira às 10h — uma hora depois do `weekly-sdlc-research`
(9h), para não disputar GPU/Ollama:

```bash
mkdir -p ~/.config/systemd/user
cp agents/weekly-cost-benefit/systemd/weekly-cost-benefit.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now weekly-cost-benefit.timer

# Verificar:
systemctl --user list-timers weekly-cost-benefit.timer
```

`Persistent=true` garante catch-up: se a máquina estava desligada na segunda
às 10h, roda assim que ligar.

## Logs

```bash
tail -f agents/weekly-cost-benefit/cost-benefit.log
```
