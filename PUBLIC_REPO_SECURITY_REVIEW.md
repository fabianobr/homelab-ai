# Revisão de Segurança para Publicação do Repositório

## Escopo e método

Avaliação feita sobre o estado atual do worktree e histórico Git local visível em `2026-06-09`.

Verificações executadas:

- busca por padrões comuns de segredo no conteúdo versionado e no histórico
- revisão de documentação, inventário, compose e scripts de bootstrap/exposição
- revisão de arquivos locais não versionados com potencial de commit acidental

Conclusão executiva:

- Não encontrei credenciais, chaves privadas ou tokens ativos versionados no estado atual do repositório.
- O maior risco identificado antes dos fixes era vazamento de inteligência operacional: domínios reais, e-mail real, hostname, paths locais, topologia de exposição e controles defensivos.
- O worktree atual foi sanitizado para usar placeholders públicos e templates.
- Há também um risco de desenho operacional: a proteção do Ollama depende de bind amplo mais firewall no host. Isso não é uma falha de repo público por si só, mas amplia impacto caso a configuração derive do documentado e o controle falhe.

## Achados por criticidade

### Alto

#### 1. Possível bypass de autenticação se o Open WebUI ficar exposto fora do caminho Cloudflare

Evidências:

- `infra/docker/docker-compose.yml` confia no header `Cf-Access-Authenticated-User-Email`
- `README.md` afirma que o serviço não pode escutar em `0.0.0.0`
- `SECURITY.md` define Cloudflare Access como controle obrigatório

Risco:

Se o serviço for publicado fora do bind `127.0.0.1`, ou se houver algum bypass do túnel/proxy, um atacante pode tentar injetar o header confiável e contornar autenticação na aplicação. O repo público não cria esse bypass sozinho, mas expõe claramente a dependência desse controle e as condições exatas de exploração.

### Médio

#### 2. Exposição de topologia real do ambiente e superfície de ataque

Evidências:

- `INVENTORY.yaml`
- `ARCHITECTURE.md`
- `SERVICES.md`
- `README.md`

Risco:

O repositório revela hostname do host, domínios reais, portas, serviços publicados, paths locais e stack exata. Isso reduz custo de enumeração, melhora phishing direcionado, facilita password spraying contra o Access e acelera exploração caso algum serviço fique exposto por erro operacional.

Status:

- Mitigado no worktree atual com placeholders em documentação, inventário e exemplos.

#### 3. Exposição de e-mail real usado como identidade permitida no Cloudflare Access

Evidências:

- `INVENTORY.yaml`
- `SECURITY.md`
- `infra/cloudflare/README.md`

Risco:

O repositório publica o identificador exato da conta autorizada. Isso aumenta risco de phishing direcionado, MFA fatigue/social engineering e correlação entre identidade pessoal e infraestrutura exposta.

Status:

- Mitigado no worktree atual com `user@example.com`.

#### 4. UUID real do Cloudflare Tunnel versionado antes da sanitização

Evidências:

- `infra/cloudflare/config.example.yml`

Risco:

O UUID do túnel não é um segredo equivalente à credencial JSON, mas é um identificador real da infraestrutura. Ele ajuda correlação operacional, troubleshooting hostil e campanhas direcionadas contra o ativo correto.

Status:

- Mitigado no worktree atual com `infra/cloudflare/config.example.yml` e placeholder `CLOUDFLARE_TUNNEL_ID`.

#### 5. Proteção do Ollama depende de bind amplo em `0.0.0.0` e regra local de firewall

Evidências:

- `infra/scripts/apply-system-config.sh`
- `README.md`
- `SECURITY.md`

Risco:

O desenho expõe o backend ao bind amplo no host e depende de `iptables` para isolamento. Se o script não for aplicado, se houver drift de firewall, mudança para nftables incompatível, ou reload parcial fora do fluxo esperado, o backend pode ficar acessível além do escopo previsto. Tornar o repo público revela exatamente essa dependência.

### Baixo

#### 6. Paths absolutos, inventário de hardware e timezone vazam dados de privacidade e contexto operacional

Evidências:

- `INVENTORY.yaml`
- `infra/docker/docker-compose.yml`

Risco:

Esses dados não dão acesso direto, mas melhoram fingerprinting do ambiente e ajudam um atacante a montar playbooks específicos para SO, GPU, layout de diretórios e contexto geográfico.

Status:

- Mitigado no worktree atual com paths e inventário genéricos.

#### 7. Configuração local do Claude não estava protegida contra commit acidental

Evidências:

- `.claude/settings.local.json` contém permissões locais amplas
- `.gitignore` não ignorava `.claude/`

Risco:

O arquivo não está versionado hoje, então não é vazamento atual. Mas ele contém permissões e paths locais relevantes. Sem regra de ignore, havia risco real de commit acidental futuro.

Status:

- Corrigido nesta revisão com inclusão de `.claude/` no `.gitignore`.

## Histórico Git

Resultado da inspeção:

- Não encontrei tokens, chaves privadas ou credenciais ativas evidentes no histórico local usando busca por padrões comuns.
- O histórico repete os mesmos domínios, e-mail e detalhes operacionais em múltiplos commits e branches. Se houver sanitização futura, ela deve considerar o histórico inteiro e não apenas `main`.

## Sugestões de correção

### Prioridade 1

1. Remover dados reais da documentação pública e substituir por placeholders.
2. Trocar domínios reais por exemplos como `ai.example.com`, `media.example.com`, `flow.example.com`.
3. Trocar e-mail real por `user@example.com`.
4. Trocar hostname real, paths locais e inventário de hardware por valores genéricos onde não forem essenciais.

### Prioridade 2

1. Transformar `infra/cloudflare/config.yml` em template, por exemplo `config.example.yml`.
2. Remover UUID real do túnel do conteúdo versionado.
3. Documentar explicitamente que a credencial JSON do tunnel nunca deve entrar em Git.

### Prioridade 3

1. Reduzir confiança implícita no header do Cloudflare.
2. Manter o serviço preso a `127.0.0.1` e adicionar verificação automatizada disso.
3. Se possível, adicionar uma camada de autenticação própria da aplicação ou um proxy local que descarte headers sensíveis vindos de origens não confiáveis.

### Prioridade 4

1. Revisar o desenho do Ollama para evitar dependência de `0.0.0.0` no host.
2. Preferir conectividade por rede Docker, socket/proxy local dedicado ou regra declarativa de firewall mais verificável.
3. Adicionar checagem de conformidade no healthcheck para garantir que a porta `11434` não esteja acessível fora de loopback/interfaces Docker.

### Prioridade 5

1. Manter `.claude/`, `.cloudflared/`, `.env*`, backups e artefatos locais fora do versionamento.
2. Adicionar um scanner de segredos no CI antes de abrir o repositório.
3. Antes da publicação, revisar todo o histórico com ferramenta dedicada de detecção de segredos e, se necessário, reescrever histórico.

## Parecer final

O repositório estava mais próximo de um risco de privacidade e enumeração do que de um vazamento crítico imediato de credenciais. O worktree atual já remove os principais dados operacionais reais do conteúdo versionável. Ainda resta o risco arquitetural de confiança no header do Cloudflare e no isolamento do Ollama por firewall, que deve ser tratado como hardening operacional antes de uma exposição pública mais ampla.
