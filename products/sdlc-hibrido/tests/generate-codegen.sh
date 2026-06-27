#!/usr/bin/env bash
# Codegen stage for the interactive SDLC flow.
#
# Receives an approved spec and an approved test file, then runs only the
# implementation stage from generate-tdd.sh: WF3 for models.py/routes.py/main.py
# with test_main.py as initial context, followed by pytest.
#
# Usage: ./generate-codegen.sh <spec-file> <test-file> [output-dir]
# Example: ./generate-codegen.sh /tmp/spec.md /tmp/test_main.py /tmp/sdlc-output
set -euo pipefail

SPEC_FILE="${1:-}"
TEST_FILE="${2:-}"
OUTPUT_DIR="${3:-./tdd-output}"

WF3="http://localhost:5678/webhook/sdlc-poc-spec-to-file"   # Code Agent

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

if [ -z "$SPEC_FILE" ] || [ -z "$TEST_FILE" ] || [ ! -f "$SPEC_FILE" ] || [ ! -f "$TEST_FILE" ]; then
  echo "Uso: $0 <spec-file> <test-file> [output-dir]"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
TOTAL_START=$(date +%s)

echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          Codegen — Testes aprovados → Código    ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Spec:   $SPEC_FILE"
echo -e "  Tests:  $TEST_FILE"
echo -e "  Output: $OUTPUT_DIR"
echo ""

cp "$TEST_FILE" "$OUTPUT_DIR/test_main.py"

ALL_FILES=(models.py routes.py main.py test_main.py)
ALL_FILES_JSON=$(python3 -c "import json, sys; print(json.dumps(sys.argv[1:]))" "${ALL_FILES[@]}")

CONTEXT_JSON=$(python3 - "$OUTPUT_DIR/test_main.py" << 'PYEOF'
import json
import sys

test_file = sys.argv[1]
with open(test_file) as f:
    content = f.read()
print(json.dumps([{"filename": "test_main.py", "content": content}]))
PYEOF
)

echo -e "${YELLOW}[1/2] Code Agent → implementação (testes como contexto inicial)${NC}"
T1=$(date +%s)

IMPL_FILES=(models.py routes.py main.py)

for filename in "${IMPL_FILES[@]}"; do
  echo "  Gerando $filename..."
  FILE_START=$(date +%s)

  TMPFILE=$(mktemp /tmp/wf3-codegen-payload-XXXXXX.json)
  python3 - "$SPEC_FILE" "$filename" "$ALL_FILES_JSON" "$CONTEXT_JSON" "$TMPFILE" << 'PYEOF'
import json
import sys

spec_file, filename, all_files_json, context_json, out_file = sys.argv[1:]
payload = {
    "spec": open(spec_file).read(),
    "filename": filename,
    "all_files": json.loads(all_files_json),
    "context": json.loads(context_json),
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
import json
import sys

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

T1_END=$(date +%s)
echo ""

echo -e "${YELLOW}[2/2] pytest${NC}"
cd "$OUTPUT_DIR"
PYTEST_OUT=$(python3 -m pytest test_main.py -v --tb=short 2>&1) || PYTEST_EXIT=$?
PYTEST_EXIT=${PYTEST_EXIT:-0}
echo "$PYTEST_OUT"

TOTAL_END=$(date +%s)
TOTAL=$((TOTAL_END - TOTAL_START))
CODEGEN_TIME=$((T1_END - T1))

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                 Resumo Codegen                  ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════╣${NC}"

PASSED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= passed)' || echo "0")
FAILED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= failed)' || echo "0")

echo -e "${CYAN}║${NC}  Modo:    Codegen com contrato de testes aprovado"
if [ "$PYTEST_EXIT" -eq 0 ]; then
  echo -e "${CYAN}║${NC}  Testes:  ${GREEN}${PASSED} passando ✓${NC}"
else
  echo -e "${CYAN}║${NC}  Testes:  ${GREEN}${PASSED} passando${NC} / ${RED}${FAILED} falhando ✗${NC}"
fi
echo -e "${CYAN}║${NC}  Codegen: ${CODEGEN_TIME}s"
echo -e "${CYAN}║${NC}  Total:   ${TOTAL}s (~$((TOTAL / 60))min)"
echo -e "${CYAN}║${NC}  Output:  $OUTPUT_DIR"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"

exit "$PYTEST_EXIT"
