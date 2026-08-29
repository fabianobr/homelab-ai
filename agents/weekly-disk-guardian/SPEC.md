# SPEC — Weekly Disk Guardian

**Versão:** 1.0  
**Data:** 2026-08-23  
**Status:** Draft para implementação  
**Dono:** operador do homelab  
**Cadência:** semanal, com diagnóstico automático e execução assistida

## 1. Contexto

Em 2026-08-23, o filesystem raiz chegou a 99% de uso, com apenas 9,8 GiB
disponíveis. A recuperação manual combinou diagnóstico, limpeza de caches,
remoção seletiva de imagens Docker, migração transacional de modelos e
deduplicação por SHA-256. O filesystem terminou em 70%, com 209 GiB disponíveis,
sem perda funcional observada.

A manutenção funcionou, mas dependeu de investigação manual e decisões difíceis:

- diferenciar cache descartável de dados pessoais;
- não confundir imagens Docker sem container com rollbacks dispensáveis;
- detectar modelos ainda referenciados por workflows;
- copiar para outro filesystem, validar o hash, trocar por symlink e só então
  remover o original;
- separar comandos sem privilégio daqueles que exigem `sudo` interativo;
- verificar serviços e links depois da alteração.

O Weekly Disk Guardian transforma essa sequência em um ciclo repetível,
auditável e seguro. O agente não é um `rm` semanal: ele produz evidência,
oferece alternativas e executa apenas um manifesto aprovado.

## 2. Objetivos

- Executar uma avaliação completa de armazenamento uma vez por semana.
- Detectar pressão de espaço antes de ela interromper Docker, downloads ou
  geração de modelos.
- Produzir uma lista priorizada de sugestões com ganho estimado, risco,
  reversibilidade e impacto operacional.
- Permitir que o operador escolha um plano conservador, equilibrado ou
  customizado.
- Executar ações aprovadas com precondições, validação posterior e rollback.
- Manter o filesystem raiz abaixo de 75% quando houver ações seguras aprovadas.
- Preservar dados pessoais, modelos em uso, imagens ativas e rollbacks recentes.

## 3. Fora do escopo

- Apagar automaticamente arquivos em `Downloads`, `Documents`, `Pictures`,
  repositórios ou outros diretórios pessoais.
- Remover volumes Docker, bancos de dados ou imagens usadas por containers.
- Decidir exclusões com base apenas na idade, no nome ou na opinião de um LLM.
- Reparar filesystems, executar `fsck`, alterar partições ou reduzir a reserva
  ext4 automaticamente.
- Instalar um serviço root ou conceder `NOPASSWD` amplo ao usuário.
- Ser uma solução de backup. Modelos migrados continuam precisando de backup ou
  de uma fonte conhecida para novo download.
- Otimizar desempenho de storage ou substituir monitoramento SMART.

## 4. Princípios de segurança

1. **Diagnóstico é somente leitura.** O timer semanal nunca apaga dados.
2. **Sugestão não é autorização.** Toda ação recebe um ID estável e precisa
   constar no manifesto aprovado.
3. **Revalidar antes de agir.** Tamanho, inode, mount, image ID, saúde do serviço
   e espaço de destino são conferidos novamente no instante da execução.
4. **Falhar fechado.** Evidência ausente, estado alterado ou ganho incerto bloqueia
   a ação; não a torna mais agressiva.
5. **Nenhum shell arbitrário.** Ações são tipos estruturados executados por
   funções conhecidas com argumentos explícitos; não existe `shell=True`.
6. **Sem glob destrutivo.** Exclusões usam caminhos ou IDs resolvidos no
   diagnóstico e revalidados na execução.
7. **Copiar, verificar, trocar, observar, remover.** Esta é a ordem obrigatória
   para migração e deduplicação.
8. **Parar ao atingir a meta.** O executor não continua limpando apenas porque
   ainda existem candidatos.
9. **O LLM pode narrar, nunca decidir.** Uma explicação via Ollama pode ser
   opcional; elegibilidade, risco e comandos são sempre determinísticos.

## 5. Experiência semanal: Scout → Proposal → Approval → Apply → Proof

### 5.1 Scout — segunda-feira, 10:00

O timer executa `weekly-disk-guardian diagnose`. A coleta é somente leitura,
usa lock exclusivo e cria um `run_id` no formato
`YYYYMMDDTHHMMSS-<8-hex>`.

O diagnóstico classifica cada filesystem:

| Estado | Critério primário |
|---|---|
| `green` | uso < 75% e disponível >= 100 GiB |
| `amber` | uso entre 75% e 84% ou disponível < 100 GiB |
| `red` | uso entre 85% e 91% ou disponível < 40 GiB |
| `critical` | uso >= 92%, disponível < 20 GiB ou mount inesperadamente `ro` |

Os limites são configuráveis. O pior critério vence.

### 5.2 Proposal — três planos derivados da mesma evidência

O planner produz cartões de ação e três visões:

- **Conservador:** caches regeneráveis, journal acima do limite, cache APT e
  revisões snap comprovadamente desabilitadas.
- **Equilibrado (recomendado):** conservador + imagens Docker seletivas e
  migrações/deduplicações verificáveis, até atingir a meta.
- **Customizado:** o operador escolhe ações individuais.

Não existe plano “agressivo” automático. Exclusão de dados pessoais aparece
apenas como recomendação manual, sem botão de execução.

Exemplo de cartão:

```text
[A-004] Migrar checkpoint legado
Ganho no /:       40,3 GiB
Custo em destino: 40,3 GiB
Risco:            médio
Reversível:       sim, antes de remover o backup local
Evidência:        2 workflows; nenhum uso nos últimos 30 dias
Impacto:          primeiro carregamento pode ficar mais lento
Requer parada:    comfyui (~30-90 s)
```

### 5.3 Approval — uma conversa curta, não um daemon

A notificação desktop e o resumo Telegram mostram somente estado, ganho possível,
número de ações e `run_id`. Caminhos completos e nomes pessoais ficam apenas no
relatório local.

O operador abre a revisão:

```bash
./agents/weekly-disk-guardian/run.sh review --run latest
```

A interface oferece:

```text
1. Aplicar plano conservador
2. Aplicar plano equilibrado (recomendado)
3. Escolher ações
4. Adiar por 24 horas
5. Ignorar esta semana
```

A aprovação expira em 48 horas. Depois disso, um novo diagnóstico é obrigatório.
O executor imprime o diff operacional e exige `APLICAR <run_id>` no modo
interativo. Para automação explícita, `--yes` só é aceito com `--run` e
`--plan` informados.

### 5.4 Apply — execução como manifesto

O comando de aprovação congela um manifesto estruturado. Antes de cada ação, o
executor compara a precondição atual com a evidência do diagnóstico. Uma ação
com drift vira `skipped-drift`; as demais podem continuar se forem independentes.

Ordem padrão:

1. ações sem parada e regeneráveis;
2. remoções Docker seletivas;
3. cópias e hashes de migração/deduplicação;
4. um único lote de cutover por serviço;
5. ações que exigem `sudo` interativo;
6. validação e eventual remoção dos backups temporários.

O executor interrompe novas ações quando o filesystem alcança a meta configurada,
mas sempre conclui a validação das ações já iniciadas.

### 5.5 Proof — relatório antes/depois

Cada execução termina com:

- `df`/inodes antes e depois;
- bytes estimados versus bytes realmente recuperados;
- ações aplicadas, puladas, falhas e rollback;
- containers e serviços afetados com status final;
- links quebrados ou temporários residuais;
- espaço restante nos destinos;
- comandos manuais ainda recomendados;
- próxima execução prevista.

## 6. Máquina de estados do run

```text
DISCOVERING
    ↓
PROPOSED ──→ EXPIRED
    ↓ approve          ↓ novo diagnose
APPROVED
    ↓
APPLYING ──→ FAILED_SAFE | ROLLED_BACK
    ↓
VERIFYING ──→ NEEDS_ATTENTION
    ↓
COMPLETED
```

Um run nunca volta de `COMPLETED` para `APPLYING`. Uma nova execução cria outro
`run_id`. Rodar `diagnose` duas vezes no mesmo minuto não reutiliza aprovação.

## 7. Diagnóstico obrigatório

### 7.1 Filesystems

- `findmnt` para origem, target, tipo e opções (`rw`/`ro`).
- `df` em bytes e formato humano para total, usado, disponível e percentual.
- `statvfs` para distinguir blocos livres de blocos disponíveis ao usuário.
- `df -i` para pressão de inodes.
- Travessia `du -x`: nunca cruza mounts.
- Maiores diretórios nos níveis configurados.
- Arquivos acima de um limiar configurável, por padrão 5 GiB.
- Arquivos apagados ainda abertos, quando `lsof` estiver disponível.

### 7.2 Docker

- `docker system df -v`.
- Containers ativos e seus image IDs imutáveis.
- Imagens sem container.
- Referências atuais em todos os Compose configurados, inclusive profiles
  inativos.
- Tags de proteção, por padrão `rollback-*`, `backup-*` e imagens criadas nos
  últimos sete dias.
- Volumes são apenas reportados; nunca entram no executor v1.

Uma imagem só é candidata quando não está ativa, não é referenciada em Compose,
não tem tag protegida e não é recente. A execução usa image ID e repete as quatro
verificações imediatamente antes de `docker image rm`.

### 7.3 Caches e logs

- caches pip, uv e outros diretórios explicitamente allowlisted;
- cache APT;
- uso do journal;
- revisões snap desabilitadas, quando o snapd responder;
- caches de navegador são apenas sugeridos, não executados no v1.

### 7.4 Modelos e artefatos grandes

- tamanho físico e caminho relativo à raiz configurada;
- referências por nome em workflows/configurações;
- evidência recente em logs, quando disponível;
- symlinks existentes e resolução dentro do container consumidor;
- duplicatas candidatas por tamanho e nome; duplicata só é confirmada por hash;
- espaço, filesystem e opções do destino.

`atime` não é prova suficiente de uso ou abandono. “Sem referência encontrada”
reduz confiança, mas nunca autoriza exclusão de modelo no v1.

## 8. Tipos de ação

| Tipo | Risco | Autoaplicável | Regra principal |
|---|---:|---:|---|
| `clean_pip_cache` | baixo | opcional | usa a CLI do pip |
| `clean_uv_cache` | baixo | opcional | usa a CLI do uv |
| `clean_apt_cache` | baixo | não | requer sudo interativo |
| `vacuum_journal` | baixo | não | preserva piso configurado |
| `remove_disabled_snap` | baixo | não | revisão precisa estar disabled |
| `remove_docker_image` | médio | não | image ID não ativo/protegido/referenciado |
| `migrate_model` | médio | não | cópia + hash + symlink + healthcheck |
| `deduplicate_file` | médio | não | hashes iguais + canônico verificado |
| `manual_personal_cleanup` | variável | nunca | aparece só como sugestão |
| `adjust_ext4_reserve` | alto | nunca | relatório manual, fora do executor |

`auto_apply_safe` existe na configuração, mas o padrão é `false`. Quando ativado,
só permite os tipos explicitamente marcados como autoaplicáveis e ainda respeita
o limite máximo de bytes por run.

## 9. Contrato de uma ação

O plano não armazena uma string shell. Cada ação segue um schema equivalente a:

```json
{
  "action_id": "A-004",
  "type": "migrate_model",
  "risk": "medium",
  "source": {"path": "<redacted-in-notification>", "size": 43285058242},
  "destination": {"path": "<local-state-only>", "min_free_after": 53687091200},
  "expected_reclaim_bytes": 43285058242,
  "preconditions": ["source_inode_unchanged", "destination_rw", "service_healthy"],
  "postconditions": ["sha256_equal", "link_readable_in_container", "service_healthy"],
  "rollback": "restore_local_backup",
  "requires_sudo": false,
  "requires_service_stop": "comfyui"
}
```

O JSON local usa schema versionado e permissões `0600`. Campos desconhecidos ou
versão incompatível invalidam a aprovação.

## 10. Algoritmo transacional para migração

1. Confirmar que origem é arquivo regular, não mudou de inode/tamanho e não tem
   escrita ativa conhecida.
2. Confirmar destino `rw` e que restará o maior entre 50 GiB ou 20% livre.
3. Copiar para `<destino>.incoming` com retomada.
4. Fazer flush quando suportado e calcular SHA-256 na origem e no destino.
5. Publicar o destino por rename no mesmo filesystem.
6. Agrupar todas as ações do mesmo serviço.
7. Parar o serviço uma única vez.
8. Criar symlink temporário, renomear a origem para backup local e publicar o
   symlink por rename.
9. Reiniciar o serviço e aguardar healthcheck com timeout.
10. Validar dentro do container: `islink`, `isfile`, `realpath` e tamanho.
11. Executar smoke test configurado quando existir.
12. Só depois remover o backup local.

Se qualquer passo entre 7 e 11 falhar, restaurar o arquivo local e reiniciar o
serviço. Se a remoção final falhar, o run termina `NEEDS_ATTENTION`, mas mantém o
serviço funcional e o backup.

## 11. Algoritmo de deduplicação

1. Agrupar candidatos por tamanho.
2. Calcular hash integral de todos os candidatos selecionados.
3. Escolher canônico pelo destino configurado, nunca arbitrariamente pelo primeiro
   resultado de `find`.
4. Copiar e validar o canônico no destino, se necessário.
5. Aplicar o mesmo cutover transacional a cada consumidor.
6. Verificar que todos os `realpath` convergem ao canônico.
7. Remover backups somente após healthcheck.

Uma mudança futura feita no canônico afeta todos os consumidores; esse trade-off
deve aparecer no cartão de aprovação.

## 12. Layout proposto

```text
agents/weekly-disk-guardian/
├── README.md
├── SPEC.md
├── config.yaml
├── disk_guardian.py
├── collectors/
│   ├── filesystems.py
│   ├── docker.py
│   ├── caches.py
│   └── models.py
├── planner.py
├── executor.py
├── schemas.py
├── notifications.py
├── run.sh
├── run-with-notify.sh
├── systemd/
│   ├── weekly-disk-guardian.service
│   └── weekly-disk-guardian.timer
└── tests/
    ├── test_collectors.py
    ├── test_planner.py
    ├── test_executor.py
    ├── test_migrations.py
    └── test_cli.py
```

Dados operacionais não ficam no repositório público:

```text
~/.local/state/homelab-ai/disk-guardian/
├── guardian.log
├── lock
├── runs/<run_id>/diagnosis.json
├── runs/<run_id>/proposal.json
├── runs/<run_id>/approval.json
├── runs/<run_id>/execution.json
└── reports/<run_id>.md
```

## 13. CLI

```bash
# Somente leitura
./agents/weekly-disk-guardian/run.sh diagnose

# Revisão interativa
./agents/weekly-disk-guardian/run.sh review --run latest

# Gerar aprovação sem executar
./agents/weekly-disk-guardian/run.sh approve --run <id> --plan balanced

# Executar manifesto aprovado
./agents/weekly-disk-guardian/run.sh apply --run <id>

# Diagnóstico + revisão + execução em uma sessão manual
./agents/weekly-disk-guardian/run.sh maintain

# Ver relatório e verificar estado
./agents/weekly-disk-guardian/run.sh report --run latest
./agents/weekly-disk-guardian/run.sh verify --run latest
```

`diagnose` e `report` nunca pedem sudo. `apply` agrupa ações privilegiadas e
solicita sudo apenas no momento necessário.

## 14. Configuração inicial

```yaml
schedule:
  on_calendar: "Mon 10:00"
  randomized_delay_sec: 120
  approval_ttl_hours: 48

policy:
  target_root_percent: 75
  min_root_available_gib: 100
  red_percent: 85
  critical_percent: 92
  critical_available_gib: 20
  destination_min_free_gib: 50
  destination_min_free_percent: 20
  auto_apply_safe: false
  auto_apply_max_gib: 20

filesystems:
  - mount: "/"
    role: "root"
  - mount: "/mnt/models"
    role: "model-store"

docker:
  compose_files:
    - "../../infra/docker/docker-compose.yml"
  protected_tag_patterns:
    - "rollback-*"
    - "backup-*"
  protect_newer_than_days: 7
  allow_volume_prune: false

models:
  roots:
    - "$HOME/AI/ComfyUI/models"
  migration_root: "/mnt/models/comfyui"
  consumer_container: "comfyui"
  consumer_mount: "/comfyui/models"
  large_file_gib: 5
  require_sha256: true

journal:
  vacuum_size: "200M"

notifications:
  desktop: true
  telegram: true
  include_paths: false
```

Variáveis como `$HOME` são expandidas pela aplicação com APIs de path, não pelo
shell. O arquivo público contém somente defaults; overrides locais e IDs de chat
permanecem fora do Git.

## 15. systemd

O timer é um serviço do usuário e executa apenas diagnóstico:

```ini
[Timer]
OnCalendar=Mon 10:00
Persistent=true
RandomizedDelaySec=2min
```

O `Persistent=true` executa um diagnóstico perdido quando a máquina volta. Se já
existir proposta válida não expirada, o catch-up atualiza a evidência e invalida a
aprovação anterior; nunca aplica uma aprovação contra um snapshot antigo.

O executor roda manualmente. Uma futura unidade root restrita fica fora do v1.

## 16. Requisitos funcionais

- **RF-01:** o sistema MUST gerar semanalmente um snapshot somente leitura dos
  filesystems configurados.
- **RF-02:** o sistema MUST classificar pressão de espaço com limites configuráveis
  e registrar a evidência em bytes.
- **RF-03:** o sistema MUST gerar ações priorizadas com ganho, risco,
  reversibilidade, impacto e precondições.
- **RF-04:** o sistema MUST oferecer planos conservador, equilibrado e customizado
  derivados da mesma proposta.
- **RF-05:** o sistema MUST NOT executar ações de médio/alto risco sem aprovação
  explícita e não expirada.
- **RF-06:** o executor MUST revalidar cada ação imediatamente antes de aplicá-la.
- **RF-07:** migrações e deduplicações MUST validar hash integral antes do cutover.
- **RF-08:** serviços afetados MUST ser agrupados em uma única janela de parada e
  MUST voltar saudáveis antes da remoção do backup local.
- **RF-09:** o sistema MUST parar de iniciar novas ações quando a meta de espaço for
  atingida.
- **RF-10:** o sistema MUST produzir relatório antes/depois mesmo quando não houver
  ação elegível ou quando a execução falhar.
- **RF-11:** o sistema MUST notificar o operador sem expor caminhos pessoais ou
  segredos no Telegram.
- **RF-12:** uma segunda execução do mesmo manifesto MUST ser idempotente e MUST
  NOT repetir exclusões já concluídas.

## 17. Requisitos não funcionais

| Requisito | Meta | Verificação |
|---|---|---|
| Segurança | zero exclusão fora do manifesto | testes de allowlist e drift |
| Privacidade | nenhum caminho pessoal em notificação remota | snapshot test |
| Auditabilidade | toda ação possui before/after e exit status | schema do execution.json |
| Disponibilidade | <= 2 min de parada por lote de serviço | teste de integração |
| Performance | diagnóstico comum <= 10 min | benchmark com collectors mockados/reais |
| Resiliência | interrupção preserva origem ou backup verificável | testes de falha por etapa |
| Compatibilidade | Python 3.11+; sem banco externo | CI/testes locais |

## 18. Critérios de aceitação

### CA-01 — diagnóstico sem mutação

**Dado** um filesystem com caches e imagens não usadas  
**Quando** `diagnose` for executado  
**Então** ele MUST gerar proposta e relatório sem alterar `df`, imagens, arquivos
ou serviços além dos próprios artefatos em `~/.local/state`.

### CA-02 — pressão crítica

**Dado** uso >= 92%  
**Quando** o snapshot for classificado  
**Então** o run MUST ser `critical`, a notificação MUST destacar urgência e nenhuma
ação de médio risco MUST ser aplicada sem aprovação.

### CA-03 — imagem Docker protegida

**Dado** uma imagem sem container cuja tag combine `rollback-*`  
**Quando** o planner avaliar Docker  
**Então** a imagem MUST aparecer como protegida e MUST NOT gerar ação executável.

### CA-04 — drift Docker

**Dado** um image ID aprovado que passou a ser usado por um container  
**Quando** `apply` revalidar a ação  
**Então** a ação MUST virar `skipped-drift` sem chamar `docker image rm`.

### CA-05 — migração válida

**Dado** origem e destino com hashes iguais e serviço saudável  
**Quando** o plano aprovado for aplicado  
**Então** o consumidor MUST enxergar um symlink legível, o serviço MUST voltar
`healthy` e o backup local só então MAY ser removido.

### CA-06 — hash divergente

**Dado** uma cópia `.incoming` com hash diferente  
**Quando** a validação terminar  
**Então** o cutover MUST NOT ocorrer, a origem MUST permanecer intacta e o run MUST
registrar falha segura.

### CA-07 — falha no healthcheck

**Dado** um cutover aplicado e healthcheck falhando  
**Quando** o timeout expirar  
**Então** o executor MUST restaurar o backup local, reiniciar o serviço e registrar
`ROLLED_BACK` ou `NEEDS_ATTENTION` se o rollback também falhar.

### CA-08 — meta atingida

**Dado** que ações de baixo risco já reduziram o root abaixo da meta  
**Quando** houver ações de médio risco restantes  
**Então** elas MUST permanecer sugeridas, mas MUST NOT ser iniciadas nesse run.

### CA-09 — sudo indisponível

**Dado** que sudo exige interação não disponível  
**Quando** uma ação privilegiada for alcançada  
**Então** ela MUST virar `pending-manual`, as ações não privilegiadas MUST manter
seus resultados e o relatório MUST mostrar os comandos exatos.

### CA-10 — execução repetida

**Dado** um manifesto já `COMPLETED`  
**Quando** `apply --run <id>` for chamado novamente  
**Então** o comando MUST sair sem mutação e informar que o run já foi concluído.

### CA-11 — alternativas derivadas da mesma evidência

**Dado** um diagnóstico com ações de riscos diferentes  
**Quando** a proposta for criada  
**Então** os planos conservador, equilibrado e customizado MUST referenciar os
mesmos action IDs, sem inventar ações ou alterar estimativas entre as visões.

### CA-12 — relatório sem execução completa

**Dado** um diagnóstico sem ação elegível ou uma execução que falhou com segurança  
**Quando** o run for finalizado  
**Então** um relatório MUST registrar estado, evidência, ações vazias/aplicadas,
falha ou rollback e próximos passos manuais.

### CA-13 — notificação remota sanitizada

**Dado** um relatório local com paths completos e nomes de arquivos  
**Quando** a notificação Telegram for montada  
**Então** ela MUST conter somente `run_id`, estado, percentuais, bytes agregados e
contagem de ações; MUST NOT conter paths, conteúdo de arquivo, token ou IP.

## 19. Matriz de rastreabilidade

| Requisito | Critérios que o comprovam |
|---|---|
| RF-01 | CA-01 |
| RF-02 | CA-02 |
| RF-03 | CA-01, CA-11 |
| RF-04 | CA-11 |
| RF-05 | CA-02, CA-10 |
| RF-06 | CA-04, CA-09 |
| RF-07 | CA-05, CA-06 |
| RF-08 | CA-05, CA-07 |
| RF-09 | CA-08 |
| RF-10 | CA-12 |
| RF-11 | CA-13 |
| RF-12 | CA-10 |

## 20. Estratégia de testes

- Unitários para cada collector com saídas de comandos simuladas.
- Property tests para thresholds, ordenação de ações e cálculo de espaço.
- Testes de schema e permissões dos artefatos locais.
- Testes do executor com subprocess fake: sucesso, drift, interrupção e rollback.
- Teste de migração usando dois diretórios temporários em filesystems distintos
  quando o ambiente permitir; fallback com mock explícito.
- Testes Docker nunca removem imagens reais.
- Teste de integração opt-in cria arquivos pequenos, serviço fake com healthcheck
  e symlinks temporários.
- Snapshot tests garantem que Telegram não contém `$HOME`, paths ou tokens.
- Teste do timer confirma `Persistent=true` e que o ExecStart chama somente
  `diagnose`, nunca `apply`.

## 21. Observabilidade

O log estruturado por ação inclui:

- timestamp UTC e `run_id`;
- `action_id`, tipo e risco;
- estado anterior e atual;
- duração;
- bytes estimados e reais;
- exit code sem capturar segredo;
- rollback tentado/concluído;
- saúde final do serviço.

O relatório semanal apresenta tendência das últimas oito execuções: percentual
de uso, crescimento líquido por semana, bytes recuperados e erro da estimativa.
Com quatro pontos ou mais, projeta “dias até atingir `red`” por regressão linear
simples; essa projeção é informativa e nunca autoriza ação.

## 22. Dependências e riscos

| Item | Tipo | Mitigação |
|---|---|---|
| `/mnt/models` indisponível | dependência | bloquear migração; alertar `critical` se links existentes quebrarem |
| Disco secundário mais lento | trade-off | manter modelos quentes no NVMe; mostrar impacto no cartão |
| `du` demorado | performance | limites de profundidade; cache de diagnóstico; timeout por collector |
| Docker socket indisponível | permissão | collector parcial; não sugerir remoção Docker sem evidência completa |
| sudo interativo | operação | agrupar comandos; reportar `pending-manual`; nunca armazenar senha |
| Relatório com paths pessoais | privacidade | XDG state `0600`; notificação remota sanitizada |
| Falha durante cutover | integridade | rename atômico, backup local e rollback testado |
| Estimativa Docker imprecisa | exatidão | tratar como limite; medir `df` real após execução |

## 23. Fases de implementação para a próxima sessão

### Fase 1 — diagnóstico e relatório

- Criar layout, config, schemas e armazenamento XDG.
- Implementar collectors de filesystem, caches, journal e Docker.
- Gerar relatório e classificação, sem executor.
- Adicionar testes e README para execução manual.

### Fase 2 — planner e revisão

- Implementar políticas, ações estruturadas e os três planos.
- Implementar CLI `review`/`approve`, TTL e sanitização de notificações.
- Garantir que nenhuma ação é executada nesta fase.

### Fase 3 — executor de baixo risco

- Implementar cache pip/uv, APT, journal, snap disabled e Docker seletivo.
- Adicionar revalidação, meta de parada, idempotência e relatório before/after.
- Tratar sudo indisponível como `pending-manual`.

### Fase 4 — migração e deduplicação

- Implementar cópia retomável, hash, cutover, healthcheck e rollback.
- Validar caminhos dentro do container.
- Adicionar testes de falhas em cada etapa.

### Fase 5 — agendamento e notificações

- Adicionar timer/service de usuário e `run-with-notify.sh`.
- Reutilizar o helper Telegram existente sem duplicar segredos.
- Fazer smoke test manual e documentar instalação/desinstalação.

## 24. Definition of Done

- [ ] Todos os RFs e CAs possuem testes rastreáveis.
- [ ] `diagnose` é comprovadamente read-only fora do XDG state.
- [ ] Nenhum comando destrutivo usa glob, path não resolvido ou shell arbitrário.
- [ ] Migração e deduplicação possuem testes de rollback por etapa.
- [ ] Notificações remotas não contêm paths pessoais, IPs, tokens ou conteúdo de
      arquivos.
- [ ] Timer instalado executa somente diagnóstico.
- [ ] Execução manual conservadora e equilibrada foi testada em dry-run.
- [ ] Um smoke test real pequeno confirma copy/hash/symlink/health/rollback.
- [ ] README documenta instalar, revisar, aplicar, verificar e desinstalar.
- [ ] `python3 -m pytest -q agents/weekly-disk-guardian/tests` passa.
- [ ] `pre-commit run --all-files` passa antes de qualquer commit.
- [ ] O repositório não contém relatórios operacionais, `.env`, tokens, IPs
      internos ou caminhos pessoais materializados.
