# DeepSeek Harness — plano de acesso externo protegido por Cloudflare

> **Estado em 2026-08-29:** implementação local concluída e validada; publicação no Cloudflare permanece pendente de configuração manual da conta/DNS.
>
> **Objetivo:** disponibilizar a Web UI do DeepSeek Harness remotamente, no mesmo padrão de Open WebUI, ComfyUI e n8n: serviço local em loopback, publicação pelo Tunnel Cloudflare e autenticação obrigatória pelo Cloudflare Access.

## Progresso da implementação

- [x] Stack isolada `harness` construída com DSH `0.1.0-rc.7`, relay interno e origin `127.0.0.1:3081`.
- [x] Workspace local isolado e estado persistente fora do Git; container não-root, raiz read-only e sem socket Docker/GPU/rede do host.
- [x] Validação local da UI, das duas conexões WebSocket, do `Host` confiável e do acesso interno ao Ollama.
- [ ] Criar aplicação Access, DNS e rota do Tunnel para o hostname real — responsabilidade pendente no Cloudflare.

## Decisão proposta

Criar uma stack Docker dedicada ao Harness, ativada por um profile novo `harness`, com persistência e workspace isolados do repositório e do diretório pessoal. A única porta no host será `127.0.0.1:3081`; o `cloudflared` já instalado encaminhará um novo hostname, sugerido como `harness.example.com`, para essa porta. O Cloudflare Access será o controle obrigatório antes de criar a rota pública.

```text
Navegador autorizado
        │ HTTPS + MFA
        ▼
Cloudflare Access ──► Cloudflare Tunnel ──► 127.0.0.1:3081 (host)
                                                    │
                                                    ▼
                                       relay TCP interno do Compose :8080
                                                    │
                                                    ▼
                               DeepSeek Harness :3080 em 127.0.0.1 (container)
                                      ├── volume de estado DSH
                                      ├── workspace dedicado e revisável
                                      └── Ollama pela rede Compose (quando escolhido)
```

O Harness é software em *developer preview*, sem auditoria de segurança, que pode executar comandos e acessar os arquivos, processos, rede e credenciais que receber. O isolamento proposto reduz o impacto, mas não torna cargas ou plugins não confiáveis seguros. [Aviso oficial de segurança](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)

## Restrição técnica que muda a arquitetura

O `dsh web` escuta em `127.0.0.1:3080` por padrão. Na versão atual, o próprio CLI rejeita `--host 0.0.0.0` explicitamente por risco de exposição de execução remota. Uma porta Docker comum não alcança um processo preso ao loopback do *namespace* do container.

Por isso, **não** será feito patch no Harness nem será usado `network_mode: host`. Em vez disso, a stack terá um relay TCP sem privilégios (por exemplo, `socat`) que compartilha o *namespace* de rede do container DSH:

- o DSH continua em `127.0.0.1:3080` dentro da stack;
- o relay escuta em `:8080` apenas nesse *namespace* e encaminha para `127.0.0.1:3080`;
- a porta publicada do Compose será `127.0.0.1:3081:8080`;
- o DSH será iniciado com `--trusted-host harness.example.com`, para aceitar somente o `Host` externo escolhido;
- o Tunnel aponta para `http://localhost:3081`; a porta nunca é ligada à LAN ou à Internet diretamente.

O relay existe só para compatibilizar o loopback deliberado do upstream com Docker. A fase de prova abaixo precisa confirmar a UI inteira, inclusive WebSockets, Settings, credenciais, seleção de workspace e execução controlada de ferramentas. Se qualquer uma dessas funções retornar 403 ou exigir modificar o código do upstream, o resultado é **não publicar**: manter o uso local/por SSH e abrir uma decisão nova, em vez de enfraquecer a segurança.

Fontes: [README do Harness](https://github.com/deepseek-ai/deepseek-harness), [referência da CLI](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md).

## Escopo e limites

Incluído após aprovação:

- imagem Docker própria e versionada para o DSH, mais o relay interno estritamente necessário;
- profile `harness`, porta loopback, volumes e limites de recursos;
- rota de ingresso no Tunnel já existente e uma aplicação Cloudflare Access exclusiva;
- documentação, validações e procedimento de rollback;
- acesso ao Ollama **somente** pela rede Docker, como provider opcional.

Fora de escopo desta aprovação:

- expor Ollama, LiteLLM, Docker socket, SSH ou qualquer API do Harness sem Access;
- montar o checkout `homelab-ai`, o diretório pessoal, `~/.ssh`, credenciais do host ou o socket Docker dentro do DSH;
- instalar plugins comunitários, habilitar MCPs ou automatizar modo headless;
- atualizar automaticamente o Harness: por estar em preview, toda atualização será deliberada e fixada.

## Arquitetura de implementação

### Stack Docker dedicada

Adicionar ao Compose existente, em `infra/docker/docker-compose.yml`, dois containers do profile `harness`:

| Componente | Responsabilidade | Exposição/isolamento |
|---|---|---|
| `deepseek-harness` | Executa a Web UI do DSH em versão npm exata, como usuário não-root. | Sem portas publicadas; sem GPU, Docker socket, `privileged`, `host network`, `host PID` ou *capabilities*. |
| `deepseek-harness-relay` | Encaminha `:8080` interno para `127.0.0.1:3080` do DSH. | Compartilha apenas a rede do DSH; a única publicação é `127.0.0.1:3081:8080` no serviço principal. |

O `Dockerfile` ficará em `infra/docker/deepseek-harness/`. Ele deve usar uma base Node LTS compatível, criar usuário sem privilégios e instalar `@deepseek-ai/dsh` com versão exata. Antes de codificar, a versão será resolvida e registrada no Dockerfile e na documentação; `latest` não será usado. `DSH_TELEMETRY_DISABLED=1` será configurado explicitamente.

O perfil permite iniciar o Harness sem alterar o conjunto atual de profiles. Não haverá `devices: nvidia.com/gpu=all`: o Harness faz chamadas ao Ollama pela rede, e somente o Ollama disputa a GPU.

### Estado, credenciais e workspace

| Dado | Destino proposto | Regra |
|---|---|---|
| Estado do DSH (`DSH_HOME`) | volume/bind local exclusivo, fora do Git | Persistido em restart; permissões mínimas; contém configurações e pode conter credenciais cadastradas pela UI. |
| Workspaces dos agentes | bind mount de diretório dedicado, por exemplo `/srv/homelab-ai/dsh-workspaces` → `/workspace` | Único caminho de escrita do agente; cada experimento recebe subdiretório Git separado. |
| Cache de pacotes | volume exclusivo | Não compartilhar cache ou diretório pessoal do host. |
| Chaves de providers | fluxo suportado pelo DSH, inserido pelo usuário autenticado | Nunca em `homelab.env`, Compose, Dockerfile, logs, argumentos, Git ou imagens. |

O provider Ollama será configurado dentro da UI para `http://ollama:11434/v1`, e não para `127.0.0.1`. A rede Compose entrega esse nome somente aos containers que precisam conversar. Chaves cloud permanecem opcionais e usam o armazenamento local do DSH; a documentação atual identifica esse estado como `$DSH_HOME/.credentials.yaml`, que não será versionado.

O primeiro workspace deverá ser novo, vazio, sem segredos e inicializado em Git. Não usar o checkout deste homelab como workspace do agente. Para trabalhar em outro repositório, clonar uma cópia deliberada dentro de `dsh-workspaces` e revisar o que for produzido antes de mover mudanças.

### Hardening do container

O Compose deverá aplicar, quando compatível com o runtime:

- usuário não-root, `read_only: true` para a raiz do container e `tmpfs` somente para temporários necessários;
- `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, `privileged: false` e sem `devices`;
- limites explícitos de CPU, memória e PIDs; `restart: unless-stopped` somente depois do smoke test;
- rede Compose própria/limitada para o serviço, sem `network_mode: host`;
- mounts explícitos e mínimos: estado, cache e `/workspace`; nenhum bind amplo de `/home`, `/`, `/var/run` ou do repositório;
- logs rotacionados pelo Docker e instruções de que prompts, saídas e logs podem conter dados sensíveis e não entram no Git.

O Harness precisa de saída de rede para providers, registros de pacotes e, conforme a tarefa, web. Essa capacidade é inerente ao agente e será declarada no README. Restringir egress por allowlist só será avaliado após definir providers e tarefas; não será alegado como controle existente sem uma política tecnicamente verificável.

## O que será feito no Cloudflare — responsabilidade do usuário

Essas ações alteram a conta, DNS e política externa. Podem ser guiadas ou auditadas por IA, mas exigem sua sessão/permissão e confirmação explícita.

1. Escolher e reservar o hostname, com sugestão `harness.example.com` (ou informar outro subdomínio da zona já atendida pelo Tunnel).
2. Em **Zero Trust → Access controls → Applications**, criar antes da rota uma aplicação **Self-hosted** para esse hostname. O Cloudflare nega por padrão até uma política `Allow` corresponder. [Procedimento oficial](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
3. Associar uma política dedicada `Allow` somente à identidade já autorizada no homelab e exigir MFA. Não reutilizar uma política ampla sem revisar o escopo; escolher duração curta de sessão (sugestão inicial: 1 hora) porque a UI controla execução de comandos.
4. Habilitar **Protect with Access** para a rota/túnel, quando disponível na modalidade do Tunnel, e manter a aplicação Access como barreira anterior ao origin. A documentação da Cloudflare recomenda criar a aplicação antes de configurar a rota, para evitar janela pública, e recomenda validação de token no origin/Tunnel. [Referência oficial](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
5. No Tunnel existente, adicionar a rota pública `harness.example.com` → `http://localhost:3081`. Para Tunnel gerenciado localmente, a alteração equivalente é feita no arquivo real, não versionado, `/etc/cloudflared/config.yml`; o template versionado receberá apenas o placeholder/documentação.
6. Confirmar o DNS do hostname. Em zona completa, a rota publicada normalmente cria o registro; em DNS parcial, criar no provedor autoritativo o CNAME indicado pelo Cloudflare. Não registrar IP público/privado do host.
7. Criar regra de WAF/rate limiting específica do hostname, conservadora e testada com a UI/WebSockets. A Access policy continua obrigatória; WAF e rate limit são defesa adicional, não substituta.
8. Validar com três identidades/cenários: sessão anônima (login/negação), identidade não permitida (negação) e identidade permitida com MFA (acesso). Revisar os eventos do Access e o estado saudável do Tunnel.

Não é necessário abrir porta no roteador, criar regra de NAT ou expor a porta 3080 na LAN.

## O que pode ser automatizado com IA

| Atividade | IA pode automatizar? | Limite e aprovação humana |
|---|---|---|
| Criar Dockerfile, serviços Compose, profile, volumes, recursos e documentação | Sim | Aplicar somente após aprovação deste plano; revisão humana do diff. |
| Gerar templates sem segredo para env e `config.example.yml` | Sim | Valores reais e arquivos do host continuam fora do Git. |
| Resolver versão, verificar digest/base image, gerar SBOM e atualizar lock | Sim, com validação | A troca de versão continua uma decisão explícita por ser preview. |
| Executar `docker compose config`, build, smoke tests, inspeções de mounts/portas e testes de rollback | Sim | Só depois da sua aprovação para mudar o host. |
| Testar que 3081 está somente em loopback e que o Tunnel aceita o ingress | Sim | Não substitui o teste de identidade no Cloudflare. |
| Escrever comandos para Cloudflare/Terraform/API | Sim | Não executar sem credenciais, permissão e confirmação; tokens nunca entram no repo. |
| Criar hostname/DNS, Access app, políticas, MFA, WAF/rate limiting e sessão | Não de forma autônoma | Você configura/autoriza no Cloudflare; a IA pode orientar passo a passo e revisar evidências sanitizadas. |
| Inserir API keys de providers no DSH | Não | Você insere na UI autenticada; a IA não recebe nem registra a chave. |
| Decidir aprovar plugins, MCPs, comandos perigosos ou acesso a um repositório sensível | Não | Exige revisão humana caso a caso. |

## Sequência de execução após aprovação

### Fase 0 — pré-requisitos e gate de compatibilidade

1. Confirmar hostname, identidade permitida e a lista inicial de providers (Ollama apenas, DeepSeek cloud, ou ambos).
2. Consultar a versão npm candidata e as notas de compatibilidade; fixar a versão antes do build.
3. Construir a stack localmente, ainda sem rota Cloudflare, e provar que o relay preserva o comportamento esperado:
   - Home, Settings, Credentials, Models e escolha de workspace respondem;
   - as duas conexões WebSocket da UI funcionam;
   - `--trusted-host` aceita somente o hostname previsto;
   - um comando inofensivo cria arquivo apenas em `/workspace`;
   - o DSH não vê socket Docker, diretório pessoal nem este repositório.
4. Se falhar por restrição upstream que exija patch ou remoção de controles, parar a publicação e registrar a incompatibilidade. Não há fallback que use bind público, host networking ou desative as verificações do DSH.

### Fase 1 — artefatos versionados e isolamento

1. Criar `infra/docker/deepseek-harness/Dockerfile` e, se necessário, arquivos mínimos do relay.
2. Adicionar `deepseek-harness` e `deepseek-harness-relay` ao Compose sob profile `harness`; usar só placeholders em exemplos de ambiente.
3. Atualizar `infra/cloudflare/config.example.yml`, `infra/scripts/healthcheck.sh` e `infra/scripts/apply-system-config.sh` para reconhecer o novo hostname/ingress, sem versionar a configuração real do host.
4. Atualizar `CLAUDE.md`, `infra/SERVICES.md`, `infra/ARCHITECTURE.md`, `infra/README.md`, `SECURITY.md`, `README.md` e `docs/deepseek-harness.md`, pois serviço, porta, profile e superfície remota mudam.
5. Registrar operação, backup/restauração dos volumes, upgrade deliberado e rollback no README do serviço.

### Fase 2 — Cloudflare, executada por você

1. Criar e testar a aplicação Access e sua política MFA antes de publicar a rota.
2. Adicionar a rota e o DNS do hostname no Tunnel existente.
3. Ativar as proteções adicionais acordadas (WAF/rate limiting) e registrar apenas identificadores/hostnames sanitizados na documentação pública.

### Fase 3 — validação e entrada em operação

1. Validar configuração: `docker compose ... config`, build da imagem, `cloudflared tunnel ingress validate` e `bash infra/scripts/healthcheck.sh`.
2. Testar localmente `http://127.0.0.1:3081` e confirmar que não há listener em IP de LAN (`ss -lntp`/`docker port`).
3. Testar externamente os três cenários de Access e a UI inteira, incluindo WebSockets e uma execução de baixo risco em workspace descartável.
4. Reiniciar somente a stack `harness` e confirmar persistência de estado/workspace sem reintroduzir segredos no Git.
5. Rodar `pre-commit run --all-files`, `bash infra/scripts/check-public-ready.sh` e revisão manual de `git diff` antes de qualquer commit.

## Critérios de aceite

- [ ] Nenhuma porta de aplicação foi aberta no roteador, LAN ou Internet; apenas `127.0.0.1:3081` no host.
- [ ] O DSH não usa `network_mode: host`, não é root e não recebe Docker socket, GPU, SSH, home ou checkout do `homelab-ai`.
- [ ] O DSH e o relay funcionam sem patchar ou ignorar a proteção upstream contra bind público.
- [ ] O hostname passa pelo Tunnel existente e a aplicação Access existe antes da rota pública.
- [ ] Identidade anônima/não permitida não alcança a UI; a permitida entra somente após MFA.
- [ ] UI, Settings, credenciais, workspace e WebSockets funcionam pelo hostname externo; não há 403 indevido por `Host`/origem.
- [ ] Toda escrita de agente fica em workspace dedicado e um teste prova que tentativas fora dele são bloqueadas ou exigem aprovação conforme o Harness.
- [ ] Segredos não aparecem em Git, env versionado, imagem, argumentos, logs de CI ou documentação.
- [ ] `pre-commit run --all-files`, `check-public-ready.sh`, configuração Compose e validação de ingress passam.

## Rollback seguro

Se o teste externo falhar ou surgir um problema de segurança, a ordem é:

1. desabilitar/remover primeiro a rota pública no Tunnel e a aplicação/política Access correspondente (ou colocar política explícita de bloqueio);
2. parar apenas o profile `harness`;
3. preservar os volumes para investigação, sem copiá-los para o repositório;
4. coletar logs sanitizados, validar que `127.0.0.1:3081` não está em escuta e documentar a causa;
5. apagar dados persistentes somente após decisão explícita do usuário, pois podem conter sessões, credenciais e workspaces.

## Decisões pendentes para a aprovação

1. Confirmar o hostname: aceitar `harness.example.com` ou informar outro subdomínio.
2. Confirmar o conjunto inicial de providers: apenas Ollama ou também DeepSeek cloud.
3. Confirmar duração de sessão proposta de 1 hora e se a política Access deve ser somente seu e-mail atual ou incluir outro grupo/identidade.
4. Aprovar o gate: se o Harness não funcionar integralmente via relay/Access sem patch upstream, não haverá publicação externa nesta fase.
