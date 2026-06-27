#!/usr/bin/env bash
# TDD Invertido: gera test_main.py PRIMEIRO (QA Agent, vê só a spec),
# depois gera os arquivos de implementação com os testes como contexto inicial.
# Isso elimina a circularidade: o Code Agent é forçado a satisfazer testes
# escritos independentemente.
#
# Uso: ./generate-tdd.sh <spec-file> [output-dir]
# Exemplo: ./generate-tdd.sh spec.md /tmp/tdd-output
set -euo pipefail

SPEC_FILE="${1:-}"
OUTPUT_DIR="${2:-./tdd-output}"

WF5="http://localhost:5678/webhook/sdlc-poc-spec-to-tests"  # Test Agent
WF3="http://localhost:5678/webhook/sdlc-poc-spec-to-file"   # Code Agent

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

if [ -z "$SPEC_FILE" ] || [ ! -f "$SPEC_FILE" ]; then
  echo "Uso: $0 <spec-file> [output-dir]"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
TOTAL_START=$(date +%s)

echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       TDD Invertido — Spec → Testes → Código     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Spec:   $SPEC_FILE"
echo -e "  Output: $OUTPUT_DIR"
echo ""

ALL_FILES=(models.py routes.py main.py test_main.py)
ALL_FILES_JSON=$(python3 -c "import json, sys; print(json.dumps(sys.argv[1:]))" "${ALL_FILES[@]}")

# ─────────────────────────────────────────────────────
# ETAPA 1: Gerar test_main.py (QA Agent — vê só a spec)
# ─────────────────────────────────────────────────────
echo -e "${YELLOW}[1/2] QA Agent → test_main.py (spec only, sem ver código)${NC}"
T1=$(date +%s)

TMPFILE=$(mktemp /tmp/wf5-payload-XXXXXX.json)
python3 - "$SPEC_FILE" "$ALL_FILES_JSON" "$TMPFILE" << 'PYEOF'
import json, sys
spec_file, all_files_json, out_file = sys.argv[1:]
payload = {
    "spec": open(spec_file).read(),
    "all_files": json.loads(all_files_json)
}
with open(out_file, "w") as f:
    json.dump(payload, f)
PYEOF

RESPONSE=$(curl -s -X POST "$WF5" \
  -H "Content-Type: application/json" \
  -d @"$TMPFILE" \
  --max-time 1300)
rm -f "$TMPFILE"

T1_END=$(date +%s)

CONTEXT_JSON=$(python3 - "$RESPONSE" "$OUTPUT_DIR/test_main.py" "$((T1_END - T1))" << 'PYEOF'
import json, sys
response_str, out_path, elapsed = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.loads(response_str)
    content = d.get("content", "")
    if not content:
        print(f"  ERROR after {elapsed}s: empty content. Response: {response_str[:200]}", file=sys.stderr)
        sys.exit(1)
    with open(out_path, "w") as f:
        f.write(content)
    print(f"  OK: {d.get('lines','?')} linhas em {elapsed}s", file=sys.stderr)
    # Retorna contexto inicial com os testes já gerados
    print(json.dumps([{"filename": "test_main.py", "content": content}]))
except Exception as e:
    print(f"  ERROR after {elapsed}s: {e}. Response: {response_str[:200]}", file=sys.stderr)
    sys.exit(1)
PYEOF
)

echo ""

# ─────────────────────────────────────────────────────
# ETAPA 2: Gerar implementação (Code Agent — vê testes + contexto progressivo)
# ─────────────────────────────────────────────────────
echo -e "${YELLOW}[2/2] Code Agent → implementação (testes como contexto inicial)${NC}"
T2=$(date +%s)

IMPL_FILES=(models.py routes.py main.py)

for filename in "${IMPL_FILES[@]}"; do
  echo "  Gerando $filename..."
  FILE_START=$(date +%s)

  TMPFILE=$(mktemp /tmp/wf3-tdd-payload-XXXXXX.json)
  python3 - "$SPEC_FILE" "$filename" "$ALL_FILES_JSON" "$CONTEXT_JSON" "$TMPFILE" << 'PYEOF'
import json, sys
spec_file, filename, all_files_json, context_json, out_file = sys.argv[1:]
payload = {
    "spec": open(spec_file).read(),
    "filename": filename,
    "all_files": json.loads(all_files_json),
    "context": json.loads(context_json)
}
with open(out_file, "w") as f:
    json.dump(payload, f)
PYEOF

  RESPONSE=$(curl -s -X POST "$WF3" \
    -H "Content-Type: application/json" \
    -d @"$TMPFILE" \
    --max-time 1300)
  rm -f "$TMPFILE"

  FILE_END=$(date +%s)
  ELAPSED=$((FILE_END - FILE_START))

  CONTEXT_JSON=$(python3 - "$RESPONSE" "$OUTPUT_DIR/$filename" "$ELAPSED" "$filename" "$CONTEXT_JSON" << 'PYEOF'
import json, sys
response_str, out_path, elapsed, filename, context_json = sys.argv[1:]
try:
    d = json.loads(response_str)
    content = d.get("content", "")
    if not content:
        print(f"  ERROR after {elapsed}s: empty content. Response: {response_str[:200]}", file=sys.stderr)
        sys.exit(1)
    with open(out_path, "w") as f:
        f.write(content)
    print(f"  OK: {d.get('lines','?')} linhas em {elapsed}s", file=sys.stderr)
    context = json.loads(context_json)
    context.append({"filename": filename, "content": content})
    print(json.dumps(context))
except Exception as e:
    print(f"  ERROR after {elapsed}s: {e}. Response: {response_str[:200]}", file=sys.stderr)
    sys.exit(1)
PYEOF
)
done

T2_END=$(date +%s)
TOTAL_END=$(date +%s)
TOTAL=$((TOTAL_END - TOTAL_START))

echo ""

# ─────────────────────────────────────────────────────
# ETAPA 3: pytest
# ─────────────────────────────────────────────────────
echo -e "${YELLOW}[pytest] Validando...${NC}"
cd "$OUTPUT_DIR"
PYTEST_OUT=$(python3 -m pytest test_main.py -v --tb=short 2>&1) || PYTEST_EXIT=$?
PYTEST_EXIT=${PYTEST_EXIT:-0}
echo "$PYTEST_OUT"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                   Resumo TDD                    ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════╣${NC}"

PASSED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= passed)' || echo "0")
FAILED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= failed)' || echo "0")

echo -e "${CYAN}║${NC}  Modo:    TDD Invertido (testes gerados antes do código)"
if [ "$PYTEST_EXIT" -eq 0 ]; then
  echo -e "${CYAN}║${NC}  Testes:  ${GREEN}${PASSED} passando ✓${NC}"
else
  echo -e "${CYAN}║${NC}  Testes:  ${GREEN}${PASSED} passando${NC} / ${RED}${FAILED} falhando ✗${NC}"
fi
echo -e "${CYAN}║${NC}  Tempo total: ${TOTAL}s (~$((TOTAL / 60))min)"
echo -e "${CYAN}║${NC}  LLM externo: 0 chamadas"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"

exit $PYTEST_EXIT
