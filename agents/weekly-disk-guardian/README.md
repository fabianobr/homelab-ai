# Weekly Disk Guardian

Rotina semanal para diagnosticar pressão de disco, produzir sugestões
determinísticas e executar somente um manifesto revisado e aprovado. A interação
é `Scout → Proposal → Approval → Apply → Proof`: o timer termina em `Proposal` e
nunca chama `apply`.

## O que o diagnóstico consulta

- bytes, inodes, flags e reservas dos filesystems configurados;
- caches allowlisted de pip/uv, cache APT, journal, snaps desabilitados e arquivos
  apagados ainda abertos;
- imagens, containers, volumes e referências de todos os profiles do Compose;
- modelos grandes, symlinks, duplicatas candidatas e referências textuais com
  limites de tempo e bytes.

Falha ou permissão insuficiente vira evidência `partial`; nunca vira autorização
para remover algo. Ausência de referência textual também não autoriza exclusão.
O diagnóstico grava apenas no state privado e não usa sudo.

## Executar manualmente

```bash
cd ~/homelab-ai/agents/weekly-disk-guardian

# Diagnóstico somente leitura
./run.sh diagnose

# Inspecionar a proposta
./run.sh review --run latest
./run.sh report --run latest

# Congelar uma aprovação por 48 horas, sem executar
./run.sh approve --run <run_id> --plan conservative

# Executar somente os IDs congelados (exige confirmação APLICAR <run_id>)
./run.sh apply --run <run_id>

# Verificar o manifesto e symlinks de migrações
./run.sh verify --run latest
```

Use `--config /caminho/config.yaml` antes do subcomando para testar outro perfil,
e `--state-dir /tmp/disk-guardian-smoke` para um smoke test isolado. A opção
`apply --yes` existe para automação deliberada, mas ainda exige `--run`, `--plan`
e uma aprovação válida correspondente.

O plano `conservative` contém somente operações de baixo risco. O `balanced`
pode incluir imagem Docker elegível ou migração já descrita no manifesto. Não há
`docker image prune -a`, volume prune, glob destrutivo, limpeza de dados pessoais
ou decisão de exclusão por LLM.

Operações APT, journal e snap podem terminar como `pending-manual` quando sudo
interativo não está disponível. Nesse caso, o relatório mostra o argv literal
para o operador executar; senha e regra `NOPASSWD` nunca são armazenadas.

## Estado e relatórios

Os artefatos ficam com diretório `0700` e arquivos `0600` em
`$XDG_STATE_HOME/homelab-ai/disk-guardian`, ou
`~/.local/state/homelab-ai/disk-guardian`:

```text
runs/<run_id>/diagnosis.json
runs/<run_id>/proposal.json
runs/<run_id>/manifest.json
runs/<run_id>/approval.json
runs/<run_id>/execution.json
reports/<run_id>.md
```

O relatório inclui até oito execuções, crescimento líquido, bytes recuperados,
erro da estimativa e, com quatro pontos ou mais, uma projeção informativa até o
limiar vermelho. A projeção nunca autoriza ação.

## Instalar o timer semanal

É um timer do usuário; não exige sudo. A unidade fornecida pressupõe o clone em
`~/homelab-ai` e agenda domingo às 18h, com atraso aleatório de até dois minutos.

```bash
mkdir -p ~/.config/systemd/user
install -m 0644 systemd/weekly-disk-guardian.service ~/.config/systemd/user/
install -m 0644 systemd/weekly-disk-guardian.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now weekly-disk-guardian.timer
systemctl --user list-timers weekly-disk-guardian.timer
```

O serviço chama explicitamente `run.sh diagnose --notify`; nunca chama `apply`.
`Persistent=true` recupera uma execução perdida quando a sessão do usuário volta.

Para desinstalar:

```bash
systemctl --user disable --now weekly-disk-guardian.timer
rm ~/.config/systemd/user/weekly-disk-guardian.timer
rm ~/.config/systemd/user/weekly-disk-guardian.service
systemctl --user daemon-reload
```

## Notificações

`diagnose --notify` envia somente o resumo agregado criado por uma allowlist:
run ID, estado, percentual, bytes disponíveis/recuperáveis e número de ações.
Paths, IPs, conteúdo de arquivos e tokens não entram nessa mensagem.

Desktop está habilitado e Telegram desabilitado no `config.yaml` público. Para
uma execução manual com Telegram, habilite-o apenas em um override local e
exporte as credenciais já usadas pelo Hermes antes de chamar
`./run-with-notify.sh`. O helper compartilhado lê
`TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`/`TELEGRAM_ALLOWED_USERS`; este diretório
não contém nem copia `.env`.

## Migração e deduplicação

O executor possui transações copy → SHA-256 → rename → symlink → healthcheck →
rollback. Elas só podem existir em manifesto explícito e aprovado. O diagnóstico
atual registra candidatos e referências de modelos como evidência, mas não cria
automaticamente uma ação de migração/deduplicação: escolher canônico, destino e
janela do serviço ainda é uma decisão operacional deliberada.

## Validar o agente

```bash
python3 -m pytest -q tests
ruff check .
python3 -m compileall -q .
bash -n run.sh run-with-notify.sh
```

Antes de commit neste repositório público, execute na raiz:

```bash
pre-commit run --all-files
```

Contrato completo e critérios de segurança: [`SPEC.md`](SPEC.md).
