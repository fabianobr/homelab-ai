# Custo-Beneficio — Ambientes de Desenvolvimento com LLMs

Avaliacoes de custo-beneficio de setups publicados: hardware local vs licencas
pagas (Anthropic, OpenAI Codex, Google Antigravity, Cursor, Copilot).
Hardware de referencia: RTX 5060 Ti 16GB VRAM, 32GB RAM.

Gerado pelo agente semanal em `agents/weekly-cost-benefit/`.

---

## Setups avaliados

### Analise de 2026-09-04

| Setup | Tipo | CAPEX (US$) | OPEX (US$/mes) | Vel. | Qual. | Breakeven | Veredito |
|---|---|---|---|---|---|---|---|
| OpenClaw 2.0 | local | 430 | 15 | 4/5 | 4/5 | nunca | local |
| Endeavor 1.0 | paid | 0 | 200 | 5/5 | 5/5 | nunca | paid |
| Mistral Small 4 | local | 430 | 15 | 4/5 | 4/5 | nunca | local |
| Kilo AI Leaderboard Models | paid | 0 | 100 | 5/5 | 5/5 | nunca | paid |
| Serena MCP | local | 430 | 15 | 4/5 | 4/5 | nunca | local |

### OpenClaw 2.0
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **IDs de preço:** `rtx-5060-ti-16gb`
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Local setup offers cost efficiency and control over the AI agent without recurring subscription fees.
- **Fonte:** https://www.infoq.com/news/2026/09/openclaw-2-release/

### Endeavor 1.0
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 200/mes
- **IDs de preço:** `claude-max-20x`
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** High performance and quality from a premium model justify the cost for advanced coding tasks.
- **Fonte:** https://flower.ai/blog/2026-09-01-introducing-endeavor-1.0

### Mistral Small 4
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **IDs de preço:** `rtx-5060-ti-16gb`
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Capable of handling coding and reasoning tasks with the available hardware, offering good value for money.
- **Fonte:** https://www.promptquorum.com/local-llms/local-llm-hardware-guide-2026

### Kilo AI Leaderboard Models
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 100/mes
- **IDs de preço:** `claude-max-5x`
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Top-tier models on the Kilo leaderboard provide superior performance and quality for coding tasks.
- **Fonte:** https://kilo.ai/leaderboard

### Serena MCP
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **IDs de preço:** `rtx-5060-ti-16gb`
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Local setup with Serena MCP provides a powerful coding environment without ongoing subscription costs.
- **Fonte:** https://www.xda-developers.com/thought-local-llm-was-limited-discovered-mcp-could-extend-it-ide/


### Analise de 2026-08-28

| Setup | Tipo | CAPEX (US$) | OPEX (US$/mes) | Vel. | Qual. | Breakeven | Veredito |
|---|---|---|---|---|---|---|---|
| Hybrid AI Agent with Local and Cloud Models | hybrid | 430 | 35 | 4/5 | 4/5 | nunca | hybrid |
| Local LLM for Coding (Qwen3-Coder 30B) | local | 430 | 15 | 4/5 | 5/5 | nunca | local |
| DeepSeek Harness (Open-Source Coding Agent) | local | 430 | 15 | 4/5 | 4/5 | nunca | local |

### Hybrid AI Agent with Local and Cloud Models
- **Tipo:** hybrid
- **CAPEX:** US$ 430
- **OPEX:** US$ 35/mes
- **IDs de preço:** `rtx-5060-ti-16gb, claude-pro`
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** hybrid
- **Justificativa:** Hybrid setup balances cost and performance, leveraging local hardware for inference and Claude Pro for advanced tasks, offering better value than pure local or paid solutions.
- **Fonte:** https://hackernoon.com/building-a-hybrid-ai-agent-with-local-and-cloud-models

### Local LLM for Coding (Qwen3-Coder 30B)
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **IDs de preço:** `rtx-5060-ti-16gb`
- **Velocidade:** 4/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Local setup provides high-quality coding assistance with minimal ongoing costs, making it more cost-effective than paid alternatives for consistent use.
- **Fonte:** https://www.orcarouter.ai/blog/best-local-llm-for-coding

### DeepSeek Harness (Open-Source Coding Agent)
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **IDs de preço:** `rtx-5060-ti-16gb`
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Open-source coding agent with long-term memory capabilities is cost-effective for local deployment, offering strong value for development tasks.
- **Fonte:** https://www.marktechpost.com/2026/08/17/deepseek-ai-releases-deepseek-harness-in-developer-preview/


### Analise de 2026-08-01

| Setup | Tipo | CAPEX (US$) | OPEX (US$/mes) | Vel. | Qual. | Breakeven | Veredito |
|---|---|---|---|---|---|---|---|
| Local LLM Rig (RTX 5060 Ti 16GB) | local | 430 | 15 | 3/5 | 4/5 | nunca | local |
| Claude Code Pro | paid | 0 | 20 | 4/5 | 5/5 | nunca | paid |
| Claude Code Max 5x | paid | 0 | 100 | 5/5 | 5/5 | nunca | paid |
| Claude Code Max 20x | paid | 0 | 200 | 5/5 | 5/5 | nunca | paid |
| Google Antigravity Pro | paid | 0 | 20 | 4/5 | 5/5 | nunca | paid |
| Google Antigravity Ultra | paid | 0 | 100 | 5/5 | 5/5 | nunca | paid |
| Hybrid Setup (Local LLM + Claude Code) | hybrid | 430 | 35 | 5/5 | 5/5 | nunca | hybrid |

### Local LLM Rig (RTX 5060 Ti 16GB)
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **Velocidade:** 3/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Local setup offers good balance of cost and performance for most coding tasks, with lower long-term costs compared to paid subscriptions.
- **Fonte:** https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark

### Claude Code Pro
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Paid subscription offers high quality and speed, but at a higher ongoing cost compared to local setups.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Claude Code Max 5x
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 100/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Max 5x plan provides the fastest and highest quality coding assistance, but at a significantly higher cost than local setups.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Claude Code Max 20x
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 200/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Max 20x plan offers the highest performance and quality, but at a very high ongoing cost compared to local alternatives.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Google Antigravity Pro
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Google Antigravity Pro offers high quality and performance, but at a higher ongoing cost compared to local setups.
- **Fonte:** https://vibecoding.app/blog/google-antigravity-pricing-2026

### Google Antigravity Ultra
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 100/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Ultra tier provides the fastest and highest quality coding assistance, but at a significantly higher cost than local setups.
- **Fonte:** https://vibecoding.app/blog/google-antigravity-pricing-2026

### Hybrid Setup (Local LLM + Claude Code)
- **Tipo:** hybrid
- **CAPEX:** US$ 430
- **OPEX:** US$ 35/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** hybrid
- **Justificativa:** Combines the best of both worlds, offering high performance and quality with moderate long-term costs.
- **Fonte:** https://www.xda-developers.com/my-local-llm-doesnt-replace-claude-it-makes-claude-dramatically-better/


### Analise de 2026-07-24

| Setup | Tipo | CAPEX (US$) | OPEX (US$/mes) | Vel. | Qual. | Breakeven | Veredito |
|---|---|---|---|---|---|---|---|
| Cursor Pro | paid | 0 | 20 | 4/5 | 4/5 | nunca | paid |
| GitHub Copilot Pro | paid | 0 | 10 | 3/5 | 3/5 | 0m | paid |
| GitHub Copilot Pro+ | paid | 0 | 39 | 4/5 | 4/5 | nunca | paid |
| Claude Pro | paid | 0 | 20 | 4/5 | 4/5 | nunca | paid |
| Claude Max 5x | paid | 0 | 100 | 5/5 | 5/5 | nunca | paid |
| Claude Max 20x | paid | 0 | 200 | 5/5 | 5/5 | nunca | paid |
| ChatGPT Plus / Codex | paid | 0 | 20 | 4/5 | 4/5 | nunca | paid |
| ChatGPT Pro | paid | 0 | 200 | 5/5 | 5/5 | nunca | paid |
| Google AI Pro (Gemini / Antigravity) | paid | 0 | 20 | 4/5 | 4/5 | nunca | paid |
| Local AI Development Setup (Ollama) | local | 430 | 15 | 4/5 | 4/5 | nunca | local |
| Local LLM Rig (RTX 4090 24GB) | local | 1500 | 25 | 5/5 | 5/5 | nunca | local |
| Mac Studio M4 Max 64GB | local | 2500 | 8 | 5/5 | 5/5 | 1250m | local |

### Cursor Pro
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Paid option offers consistent performance and integration with development tools, though local setups may offer better long-term cost efficiency.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### GitHub Copilot Pro
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 10/mes
- **Velocidade:** 3/5 | **Qualidade:** 3/5
- **Breakeven local vs pago:** 0m
- **Veredito:** paid
- **Justificativa:** Lower cost but less advanced than Cursor, making it suitable for basic coding assistance needs.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### GitHub Copilot Pro+
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 39/mes
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Higher cost but provides more advanced features and better quality output compared to the standard Copilot plan.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Claude Pro
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Balanced cost and performance, suitable for most coding tasks with good integration and reliability.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Claude Max 5x
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 100/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Higher cost but provides superior performance and quality, ideal for complex and large-scale coding tasks.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Claude Max 20x
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 200/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Highest tier with maximum performance and quality, suitable for enterprise-level coding needs.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### ChatGPT Plus / Codex
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Moderate cost with good performance, suitable for general coding assistance and integration with existing tools.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### ChatGPT Pro
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 200/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Higher cost but offers top-tier performance and quality, ideal for advanced coding tasks and professional use.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Google AI Pro (Gemini / Antigravity)
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Balanced cost and performance, suitable for most coding tasks with good integration and reliability.
- **Fonte:** https://www.cosmicjs.com/blog/claude-code-vs-github-copilot-vs-cursor-which-ai-coding-agent-should-you-use-2026

### Local AI Development Setup (Ollama)
- **Tipo:** local
- **CAPEX:** US$ 430
- **OPEX:** US$ 15/mes
- **Velocidade:** 4/5 | **Qualidade:** 4/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Lower long-term cost with good performance, suitable for developers who prefer control and customization.
- **Fonte:** https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark

### Local LLM Rig (RTX 4090 24GB)
- **Tipo:** local
- **CAPEX:** US$ 1500
- **OPEX:** US$ 25/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** local
- **Justificativa:** Higher upfront cost but offers superior performance and quality, ideal for heavy usage and complex tasks.
- **Fonte:** https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark

### Mac Studio M4 Max 64GB
- **Tipo:** local
- **CAPEX:** US$ 2500
- **OPEX:** US$ 8/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** 1250m
- **Veredito:** local
- **Justificativa:** High upfront cost but offers excellent performance and quality, suitable for professional and enterprise use.
- **Fonte:** https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark


### Analise de 2026-07-07

| Setup | Tipo | CAPEX (US$) | OPEX (US$/mes) | Vel. | Qual. | Breakeven | Veredito |
|---|---|---|---|---|---|---|---|
| Local AI Development Setup (AMD Ryzen 7, RTX 4070) | local | 2500 | 0 | 5/5 | 5/5 | 250m | local |
| Google Antigravity 2.0 (Free Tier) | paid | 0 | 0 | 4/5 | 5/5 | 0m | paid |
| Google Antigravity 2.0 (Ultra Tier) | paid | 0 | 100 | 4/5 | 5/5 | nunca | paid |
| Claude Code (Pro Plan) | paid | 0 | 20 | 4/5 | 5/5 | nunca | paid |
| Local LLM Setup (Ollama) | local | 0 | 0 | 5/5 | 5/5 | 0m | local |

### Local AI Development Setup (AMD Ryzen 7, RTX 4070)
- **Tipo:** local
- **CAPEX:** US$ 2500
- **OPEX:** US$ 0/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** 250m
- **Veredito:** local
- **Justificativa:** High upfront cost but no recurring fees; modern hardware enables fast, high-quality local model training/inference.
- **Fonte:** https://www.kunalganglani.com/blog/local-llms-complete-guide

### Google Antigravity 2.0 (Free Tier)
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 0/mes
- **Velocidade:** 4/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** 0m
- **Veredito:** paid
- **Justificativa:** Free tier offers basic access with low monthly costs; suitable for light use but limited by quotas.
- **Fonte:** https://vibecoding.app/blog/google-antigravity-pricing-2026

### Google Antigravity 2.0 (Ultra Tier)
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 100/mes
- **Velocidade:** 4/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Mid-tier subscription provides balanced performance for daily developers without excessive costs.
- **Fonte:** https://vibecoding.app/blog/google-antigravity-pricing-2026

### Claude Code (Pro Plan)
- **Tipo:** paid
- **CAPEX:** US$ 0
- **OPEX:** US$ 20/mes
- **Velocidade:** 4/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** nunca
- **Veredito:** paid
- **Justificativa:** Low monthly cost with enterprise-grade quality; ideal for individual developers.
- **Fonte:** https://www.getaiperks.com/en/blogs/34-claude-code-pricing-vs-alternatives

### Local LLM Setup (Ollama)
- **Tipo:** local
- **CAPEX:** US$ 0
- **OPEX:** US$ 0/mes
- **Velocidade:** 5/5 | **Qualidade:** 5/5
- **Breakeven local vs pago:** 0m
- **Veredito:** local
- **Justificativa:** Zero-cost software stack with no recurring fees; leverages existing hardware for maximum efficiency.
- **Fonte:** https://www.kunalganglani.com/blog/local-llms-complete-guide


_Setups avaliados pela analise semanal automatica._

---

## Descartados

_Setups julgados irrelevantes ou duplicados._
