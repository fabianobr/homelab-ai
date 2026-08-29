# Handoff — Weekly Disk Guardian

## Estado atual

As cinco fases de `SPEC.md` foram implementadas no agente local. O fluxo é
`Scout → Proposal → Approval → Apply → Proof`, com coletores reais de host,
Docker e modelos, manifests versionados, state privado, executor fail-closed,
relatórios/tendência, notificação sanitizada e timer systemd do usuário.

O timer chama somente `diagnose --notify`. Telegram permanece desabilitado no
config público. Nenhuma credencial, relatório operacional ou override local deve
ser versionado.

## Decisões de segurança preservadas

1. LLM não decide exclusões.
2. Evidência parcial nunca gera ação destrutiva.
3. Docker remove somente image ID revalidado; não há prune global nem volume
   prune.
4. Sudo é interativo e vira `pending-manual` quando indisponível.
5. Migração/deduplicação usa copy, SHA-256, cutover, healthcheck e rollback.
6. Candidatos de modelos são evidência; ações não são geradas automaticamente
   sem escolha operacional explícita de canônico/destino/janela.
7. O executor para de iniciar ações quando as duas metas de espaço são atingidas.

## Retomar em outra sessão

```text
Continue o Weekly Disk Guardian em agents/weekly-disk-guardian.

Leia CLAUDE.md, agents/weekly-disk-guardian/SPEC.md, README.md e HANDOFF.md até o
fim. Preserve alterações não relacionadas do worktree e trate a spec como
contrato de segurança. Antes de mudar código, rode a suíte focada. Depois da
mudança, faça um diagnóstico somente leitura com --state-dir temporário, audite
os RFs/CAs e execute pre-commit run --all-files antes de qualquer commit.

Não habilite apply no timer, não use LLM para decidir exclusões, não introduza
prune global/NOPASSWD e não versione state, paths materializados, IPs, tokens ou
.env. Para evoluir ações de modelos, exija escolha explícita do operador e
preserve copy/hash/cutover/healthcheck/rollback.
```

## Verificação rápida

```bash
python3 -m pytest -q agents/weekly-disk-guardian/tests
ruff check agents/weekly-disk-guardian
bash -n agents/weekly-disk-guardian/run.sh agents/weekly-disk-guardian/run-with-notify.sh
git status --short
```
