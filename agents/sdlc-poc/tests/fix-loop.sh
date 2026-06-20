#!/usr/bin/env bash
# Auto-fix loop: roda pytest, manda falhas ao Fix Agent (WF4), re-testa.
# Repete até passar ou atingir MAX_RETRIES.
#
# Uso:  ./fix-loop.sh <output-dir> <spec-file> [max-retries=3]
# Chamado automaticamente por run-pipeline.sh quando pytest falha.
set -euo pipefail

OUTPUT_DIR="${1:-}"
SPEC_FILE="${2:-}"
MAX_RETRIES="${3:-3}"

WEBHOOK="http://localhost:5678/webhook/sdlc-poc-fix"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

if [ -z "$OUTPUT_DIR" ] || [ -z "$SPEC_FILE" ]; then
  echo "Uso: $0 <output-dir> <spec-file> [max-retries]"
  exit 1
fi

cd "$OUTPUT_DIR"
FIXES_APPLIED=0

for attempt in $(seq 1 "$MAX_RETRIES"); do
  echo -e "  ${YELLOW}Tentativa $attempt/$MAX_RETRIES — rodando pytest...${NC}"

  PYTEST_OUT=$(python3 -m pytest test_main.py -v --tb=short 2>&1) || true
  PYTEST_EXIT=$?

  if [ "$PYTEST_EXIT" -eq 0 ]; then
    echo -e "  ${GREEN}✓ Todos os testes passando após $FIXES_APPLIED fix(es) automático(s)${NC}"
    exit 0
  fi

  FAILED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= failed)' || echo "?")
  echo -e "  ${RED}✗ $FAILED teste(s) falhando${NC}"

  if [ "$attempt" -eq "$MAX_RETRIES" ]; then
    echo -e "  ${RED}Limite de tentativas atingido. Falhas restantes:${NC}"
    echo "$PYTEST_OUT" | grep -E "^FAILED|^ERROR" || true
    exit 1
  fi

  echo -e "  Enviando falhas ao Fix Agent (qwen2.5-coder:32b)..."
  FIX_START=$(date +%s)

  # Monta payload em arquivo temp (evita quoting hell — mesma abordagem do generate-files.sh)
  TMPFILE=$(mktemp /tmp/wf4-payload-XXXXXX.json)
  python3 - "$SPEC_FILE" "$OUTPUT_DIR" "$PYTEST_OUT" "$TMPFILE" << 'PYEOF'
import json, sys, os, glob
spec_file, output_dir, pytest_out, tmp_out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

spec = open(spec_file).read()

# Collect all .py files in the output dir
files = []
for path in sorted(glob.glob(os.path.join(output_dir, "*.py"))):
    fname = os.path.basename(path)
    content = open(path).read()
    files.append({"filename": fname, "content": content})

payload = {
    "spec": spec,
    "pytest_output": pytest_out,
    "files": files
}
with open(tmp_out, "w") as f:
    json.dump(payload, f)
PYEOF

  RESPONSE=$(curl -s -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d @"$TMPFILE" \
    --max-time 1300)
  rm -f "$TMPFILE"

  FIX_END=$(date +%s)
  ELAPSED=$(( FIX_END - FIX_START ))

  # Grava o arquivo corrigido e confirma
  python3 - "$RESPONSE" "$OUTPUT_DIR" "$ELAPSED" << 'PYEOF'
import json, sys, os, glob
response_str, output_dir, elapsed = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.loads(response_str)
    filename = d.get("filename", "")
    content = d.get("content", "")

    # Guard: se o modelo não prefixou com # FILE:, tentamos inferir do conteúdo
    if not filename or filename == "unknown.py":
        known = [os.path.basename(p) for p in glob.glob(os.path.join(output_dir, "*.py"))]
        for candidate in known:
            if f"# FILE: {candidate}" in content or f"router = APIRouter" in content and "routes" in candidate:
                filename = candidate
                break
        if not filename or filename == "unknown.py":
            print(f"  ⚠ Fix Agent não identificou o arquivo (retornou '{filename}'). Pulando esta tentativa.", file=sys.stderr)
            sys.exit(0)  # não abortar — vai tentar de novo no próximo loop

    if not content:
        print(f"  ⚠ Fix Agent retornou conteúdo vazio. Response: {response_str[:200]}", file=sys.stderr)
        sys.exit(0)

    # Só grava se é um arquivo que existe no projeto (não criar arquivos novos inesperados)
    out_path = os.path.join(output_dir, filename)
    if not os.path.exists(out_path):
        print(f"  ⚠ Fix Agent quer criar '{filename}' que não existe no output. Pulando.", file=sys.stderr)
        sys.exit(0)

    with open(out_path, "w") as f:
        f.write(content)
    print(f"  → Corrigido: {filename} ({d.get('lines', '?')} linhas, {elapsed}s)")
except Exception as e:
    print(f"  ⚠ Erro ao processar resposta do Fix Agent: {e}", file=sys.stderr)
PYEOF

  FIXES_APPLIED=$(( FIXES_APPLIED + 1 ))
done

# Se chegou aqui, saiu do loop sem passar — já tratado dentro do loop
exit 1
