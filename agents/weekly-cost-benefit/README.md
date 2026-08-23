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

1. Monta queries com ano/mês corrente e alterna um grupo temático a cada semana
2. Executa quatro queries via SearXNG local (fallback: DuckDuckGo), limitadas ao mês
3. Lê o ledger e remove URLs/títulos já avaliados **antes** de usar a GPU,
   incluindo nomes qualificados que contêm um setup conhecido
4. Envia somente fontes candidatas + a **tabela histórica de preços** ao Ollama
   (`qwen3:14b`; um único fallback estrito para `qwen3:8b`)
5. Exige JSON Schema; o modelo escolhe somente `pricing_ids` da tabela fechada
6. Valida campos/notas/URLs e deriva CAPEX, OPEX e breakeven em Python
7. Gera um relatório semanal em `reports/YYYY-MM-DD-cost-benefit.md` com tabela
   comparativa e avaliações detalhadas
8. Adiciona as novas avaliações ao ledger em `research/sdlc-agentico/cost-benefit.md`
9. Notifica via Telegram (bot Hermes) com o resumo dos vereditos
10. Registra tudo em `cost-benefit.log`

Se todas as fontes já forem conhecidas, o relatório registra explicitamente
“nenhuma fonte candidata nova”, não chama o Ollama e encerra com sucesso. Falha,
timeout ou resposta inválida nos dois modelos ainda gera relatório/notificação,
mas o processo encerra com status diferente de zero para o systemd não mascarar
o problema. Zero resultados brutos em todas as queries também é tratado como
falha de busca, não como ausência legítima de novidades.

## Dependências

- **Ollama** rodando em `http://localhost:11434` com pelo menos um modelo instalado
  - Primário exato: `qwen3:14b`
  - Fallback exato: `qwen3:8b`
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
hardware local (CAPEX + energia) e de licenças pagas (US$/mês). Essa tabela é
uma entrada histórica, não um dado que o modelo possa atualizar. O agente nunca
inventa nem substitui preços a partir de snippets de busca. Cada opção possui um
`id` estável. A resposta do modelo não aceita CAPEX/OPEX livres: ela referencia
esses IDs, e o Python valida a composição e soma os custos configurados antes de
qualquer relatório ou escrita no ledger.

Para alterar um valor, confira-o na página oficial do fornecedor, atualize
`reference_date` e registre a URL em `source_url` no item correspondente. O
relatório alerta quando a referência passa de `max_age_months` ou quando há
valores sem fonte oficial. Preço observado de hardware usado e custo local de
energia devem apontar para a fonte verificável adotada pelo operador; não devem
ser apresentados como preço oficial do fabricante.

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
- Ajustar queries base/grupos rotativos e a janela temporal de busca
- Atualizar `pricing_reference` somente com data e fonte oficial verificadas
- Alterar as tags exatas dos modelos Ollama
- Ajustar `num_ctx`, `num_predict` e timeout por requisição
- Adicionar itens ao `known_evaluated` (nunca serão reavaliados)
- Ajustar a URL do SearXNG

## Agendamento (systemd timer)

Executa toda **sexta-feira às 20h** — uma hora depois do
`weekly-sdlc-research` (19h), para não disputar GPU/Ollama:

```bash
mkdir -p ~/.config/systemd/user
cp agents/weekly-cost-benefit/systemd/weekly-cost-benefit.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now weekly-cost-benefit.timer

# Verificar:
systemctl --user list-timers weekly-cost-benefit.timer
```

`Persistent=true` garante catch-up: se a máquina estava desligada na sexta às
20h, roda assim que ligar.

## Logs

```bash
tail -f agents/weekly-cost-benefit/cost-benefit.log
```

## Testes

```bash
python3 -m pytest -q agents/weekly-cost-benefit/tests
```

Os testes usam mocks: não executam buscas/Ollama, não enviam Telegram e não
escrevem relatório ou ledger.
