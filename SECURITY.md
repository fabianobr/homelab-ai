# Segurança

## Regras obrigatórias

Nunca:

- Expor `Ollama` diretamente na internet
- Expor `LM Studio` diretamente na internet
- Expor `ComfyUI` sem Cloudflare Access
- Expor `n8n` diretamente na internet sem autenticação forte
- Abrir portas no roteador sem necessidade
- Expor Docker socket
- Instalar MCP desconhecido sem revisar permissões
- Rodar scripts baixados sem ler

Sempre:

- Usar Cloudflare Tunnel para Open WebUI e ComfyUI remotos
- Usar Cloudflare Access com login e MFA
- Manter Docker e Ubuntu atualizados
- Fazer backup antes de mudanças grandes
- Usar usuários sem privilégios quando possível

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
Open WebUI via Cloudflare Access
ComfyUI via Cloudflare Access
n8n via Cloudflare Access
```

Domínios autorizados:

```text
https://chat.ai.example.com
https://media.ai.example.com
https://flow.ai.example.com
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
LM Studio 1234
```
