# Segurança

## Regras obrigatórias

Nunca:

- Expor `Ollama` diretamente na internet
- Expor `ComfyUI` sem Cloudflare Access
- Expor `n8n` diretamente na internet sem autenticação forte
- Abrir portas no roteador sem necessidade
- Expor Docker socket
- Expor DeepSeek Harness sem Cloudflare Access
- Instalar MCP desconhecido sem revisar permissões
- Rodar scripts baixados sem ler

Sempre:

- Usar Cloudflare Tunnel para Open WebUI e ComfyUI remotos
- Usar Cloudflare Access com login e MFA
- Manter Docker e Ubuntu atualizados
- Fazer backup antes de mudanças grandes
- Usar usuários sem privilégios quando possível

## Divulgação de vulnerabilidades (MUST)

Este repositório é público. Vulnerabilidades encontradas na infraestrutura, nos
scripts ou nos produtos deste repo:

- **MUST**: ser reportadas em privado via
  [GitHub Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  (aba *Security* → *Report a vulnerability*).
- **MUST NOT**: ser descritas em issues públicas, PRs, mensagens de commit,
  logs commitados ou documentação antes de a correção estar publicada.
- **MUST**: detalhes de exploração (payloads, caminhos internos, versões
  vulneráveis em uso) permanecerem fora do Git mesmo após a correção; a
  mensagem de commit da correção descreve o efeito, não a exploração.
- **MUST**: correções de vulnerabilidade serem verificadas com
  `pre-commit run --all-files` e `infra/scripts/check-public-ready.sh` antes
  do push, como qualquer commit.

## Integração pública do media pipeline

- O bootstrap não recebe nem persiste segredos. `HF_TOKEN` pertence somente ao
  ambiente do processo consumidor e nunca deve aparecer em argumentos ou logs.
- O script de preparo clona apenas origens públicas allowlisted no lock file e
  faz checkout de commits completos fixos.
- Nenhum script da integração usa `sudo`, altera firewall, configura Cloudflare,
  inicia Hermes ou publica portas fora de `127.0.0.1`.
- Modelos, mídia, prompts privados, payloads, inputs e outputs ficam fora do Git.
- Releases dependentes devem fixar uma tag SemVer exata do `homelab-ai`; executar
  código de `main` não faz parte do contrato suportado.
- Antes de uma tag pública, execute `pre-commit run --all-files`, gitleaks no
  worktree e histórico, revisão de CVEs das imagens e
  `infra/scripts/check-public-ready.sh`.

## Cloudflare

Configuração recomendada:

```text
Cloudflare Tunnel
+
Cloudflare Access
+
MFA
+
WAF
+
Rate Limiting
+
Geoblocking opcional
```

## Ameaças principais

| Risco | Mitigação |
|---|---|
| Descobrirem o domínio | Cloudflare Access antes da aplicação |
| Força bruta | MFA + rate limit |
| Exploração de serviço local | Não expor serviço direto |
| MCP perigoso | Instalar apenas MCP confiável |
| Prompt injection em agente | Limitar permissões e revisar ações |
| Vazamento de arquivos | RAG com pastas controladas |

## Política de exposição

Público externo permitido apenas para:

```text
ComfyUI via Cloudflare Access
n8n via Cloudflare Access
DeepSeek Harness via Cloudflare Access
```

Domínios autorizados:

```text
https://media.example.com
https://flow.example.com
https://dsh.example.com
```

Identidade permitida no Access:

```text
user@example.com
```

Preferência operacional:

```text
Cloudflare Access > porta pública direta
```

Backends internos que nao devem ter hostname publico:

```text
Ollama 11434
```

O DeepSeek Harness publica apenas `127.0.0.1:3081` para o Tunnel. Ele não recebe socket Docker, rede do host, GPU, diretório pessoal ou checkout do repositório; seus workspaces ficam em mount dedicado. Cloudflare Access é uma barreira necessária, mas não torna workloads, plugins ou prompts não confiáveis seguros.

Ollama fica em `0.0.0.0:11434` apenas para permitir acesso do container Docker via `host.docker.internal`. A unidade `homelab-ai-ollama-firewall.service` deve estar ativa para bloquear essa porta fora de loopback e interfaces Docker.
