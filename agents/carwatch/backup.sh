#!/usr/bin/env bash
# Dump do banco do CarWatch, com cópia local rotacionada e envio para um remote rclone.
#
# `raw_items` e `launch_events` o pipeline reconstrói com o tempo; `llm_usage`
# (histórico de custo), `sources` e `source_metrics` (curadoria acumulada) não.
# É por isso que este script existe.
#
# Uso:
#   ./backup.sh
#
# Ambiente:
#   CARWATCH_BACKUP_DIR     destino local (default: $HOME/.local/state/carwatch/backups)
#   CARWATCH_BACKUP_REMOTE  remote rclone; vazio desliga o envio
#                           (default: gdrive:carwatch-backups/)
#   CARWATCH_BACKUP_KEEP    quantas cópias manter de cada lado (default: 8)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DEST="${CARWATCH_BACKUP_DIR:-$HOME/.local/state/carwatch/backups}"
REMOTE="${CARWATCH_BACKUP_REMOTE-gdrive:carwatch-backups/}"
KEEP="${CARWATCH_BACKUP_KEEP:-8}"
MIN_BYTES=1000

mkdir -p "$DEST"

ts="$(date +%Y%m%d-%H%M%S)"
tmp="$DEST/.carwatch-$ts.dump.partial"
final="$DEST/carwatch-$ts.dump"

# Dumpa para um arquivo temporário e só promove no sucesso. Com redirecionamento,
# um pg_dump que falha no meio deixa um arquivo truncado que parece um backup bom —
# e um backup que parece bom é pior que backup nenhum, porque ninguém procura outro.
if ! docker compose exec -T db pg_dump -U carwatch -Fc carwatch > "$tmp"; then
    rm -f "$tmp"
    echo "backup.sh: pg_dump falhou" >&2
    exit 1
fi

size="$(stat -c%s "$tmp")"
if [ "$size" -lt "$MIN_BYTES" ]; then
    rm -f "$tmp"
    echo "backup.sh: dump suspeito, $size bytes (mínimo $MIN_BYTES)" >&2
    exit 1
fi

mv "$tmp" "$final"
echo "backup.sh: $final ($size bytes)"

# Rotação local. Os nomes são carwatch-YYYYMMDD-HHMMSS.dump, então ordem
# alfabética é ordem cronológica.
ls -1 "$DEST"/carwatch-*.dump 2>/dev/null | sort | head -n "-$KEEP" | while read -r old; do
    rm -f "$old"
    echo "backup.sh: rotacionado $old"
done

# A partir daqui nada pode derrubar o script: o dump local já existe e já vale.
# Falha de rede não é motivo para o run semanal terminar em erro.
if [ -z "$REMOTE" ]; then
    echo "backup.sh: CARWATCH_BACKUP_REMOTE vazio, envio remoto desligado"
    exit 0
fi

if ! command -v rclone >/dev/null 2>&1; then
    echo "backup.sh: rclone não instalado, cópia só local" >&2
    exit 0
fi

# 1,4 MB levaram ~56s na banda de subida deste host (medido em 2026-08-29), e o
# dump cresce. Timeout curto derrubaria o envio à toa.
if timeout 600 rclone copy "$DEST" "$REMOTE" --include "carwatch-*.dump"; then
    echo "backup.sh: enviado para $REMOTE"
    timeout 120 rclone lsf "$REMOTE" --include "carwatch-*.dump" 2>/dev/null \
        | sort | head -n "-$KEEP" | while read -r old; do
        timeout 60 rclone delete "$REMOTE$old" && echo "backup.sh: rotacionado remoto $old"
    done
else
    echo "backup.sh: envio para $REMOTE falhou; cópia local preservada em $final" >&2
fi

exit 0
