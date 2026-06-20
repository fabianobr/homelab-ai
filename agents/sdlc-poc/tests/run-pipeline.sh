#!/usr/bin/env bash
# Pipeline agêntico completo: Discovery → Spec → Code → Pytest
# Todos os LLMs rodam localmente via Ollama. Zero chamadas externas.
#
# Uso:
#   ./run-pipeline.sh <discovery-file> <output-dir>
#
# Exemplo:
#   ./run-pipeline.sh ../../../docs/sdlc-agentico/input/chat-discovery.txt /tmp/meu-modulo
set -euo pipefail

DISCOVERY_FILE="${1:-}"
OUTPUT_DIR="${2:-/tmp/pipeline-output}"

WF1="http://localhost:5678/webhook/sdlc-poc-chat"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

if [ -z "$DISCOVERY_FILE" ] || [ ! -f "$DISCOVERY_FILE" ]; then
  echo "Uso: $0 <discovery-file> [output-dir]"
  echo "Exemplo: $0 docs/sdlc-agentico/input/chat-discovery.txt /tmp/output"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
TOTAL_START=$(date +%s)

echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Pipeline Agêntico Local — n8n + Ollama       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Input:  ${DISCOVERY_FILE}"
echo -e "  Output: ${OUTPUT_DIR}"
echo ""

# ─────────────────────────────────────────────
# ETAPA 1: Discovery → PM Agent (WF1, turno 1)
# ─────────────────────────────────────────────
echo -e "${YELLOW}[1/3] Discovery → PM Agent (qwen3-coder:30b)${NC}"
T1=$(date +%s)

python3 - "$DISCOVERY_FILE" /tmp/_pp_p1.json << 'PYEOF'
import json, sys
chat_input = open(sys.argv[1]).read().strip()
json.dump({"messages": [], "chatInput": chat_input}, open(sys.argv[2], "w"))
PYEOF

curl -s -X POST "$WF1" \
  -H "Content-Type: application/json" \
  -d @/tmp/_pp_p1.json \
  --max-time 180 > /tmp/_pp_r1.json

# ─────────────────────────────────────────────
# ETAPA 1b: "gerar spec" — turno 2
# ─────────────────────────────────────────────
python3 - "$DISCOVERY_FILE" /tmp/_pp_r1.json /tmp/_pp_p2.json << 'PYEOF'
import json, sys
first_msg = open(sys.argv[1]).read().strip()
first_reply = json.load(open(sys.argv[2])).get("output", "")
history = [
    {"role": "user", "content": first_msg},
    {"role": "assistant", "content": first_reply}
]
json.dump({"messages": history, "chatInput": "gerar spec"}, open(sys.argv[3], "w"))
PYEOF

curl -s -X POST "$WF1" \
  -H "Content-Type: application/json" \
  -d @/tmp/_pp_p2.json \
  --max-time 180 > /tmp/_pp_r2.json

SPEC_FILE="$OUTPUT_DIR/spec.md"
SPEC_RESULT=$(python3 - /tmp/_pp_r2.json "$SPEC_FILE" << 'PYEOF'
import json, re, sys
d = json.load(open(sys.argv[1]))
output = d.get("output", "")
m = re.search(r'---SPEC-START---(.*?)---SPEC-END---', output, re.DOTALL)
if m:
    spec = m.group(1).strip()
    open(sys.argv[2], "w").write(spec)
    lines = len(spec.splitlines())
    print(f"OK:{lines}")
else:
    print("ERR")
PYEOF
)

T1_END=$(date +%s)
if [[ "$SPEC_RESULT" == ERR* ]]; then
  echo -e "  ${RED}✗ Spec não encontrada na resposta do PM Agent${NC}"
  echo -e "  Resposta bruta:"
  python3 -c "import json; print(json.load(open('/tmp/_pp_r2.json')).get('output','')[:500])"
  exit 1
fi

SPEC_LINES="${SPEC_RESULT#OK:}"
echo -e "  ${GREEN}✓ Spec gerada${NC} — ${SPEC_LINES} linhas → ${SPEC_FILE} ($(( T1_END - T1 ))s)"
echo ""

# ─────────────────────────────────────────────
# ETAPA 2: Spec → Arquivos (WF3 × 4)
# ─────────────────────────────────────────────
echo -e "${YELLOW}[2/3] Spec → Código (qwen2.5-coder:32b, contexto progressivo)${NC}"
T2=$(date +%s)

bash "$SCRIPT_DIR/generate-files.sh" "$SPEC_FILE" "$OUTPUT_DIR"

T2_END=$(date +%s)
echo -e "  ${GREEN}✓ Arquivos gerados${NC} ($(( T2_END - T2 ))s)"
echo ""

# ─────────────────────────────────────────────
# ETAPA 3: pytest
# ─────────────────────────────────────────────
echo -e "${YELLOW}[3/3] Pytest${NC}"
T3=$(date +%s)

cd "$OUTPUT_DIR"
PYTEST_OUT=$(python3 -m pytest test_main.py -v --tb=short 2>&1)
PYTEST_EXIT=$?
T3_END=$(date +%s)

echo "$PYTEST_OUT"

# ─────────────────────────────────────────────
# ETAPA 4 (opcional): Auto-fix loop
# ─────────────────────────────────────────────
AUTO_FIXES=0
if [ "$PYTEST_EXIT" -ne 0 ]; then
  echo ""
  echo -e "${YELLOW}[4/4] Auto-fix loop (WF4 — qwen2.5-coder:32b)${NC}"
  if bash "$SCRIPT_DIR/fix-loop.sh" "$OUTPUT_DIR" "$SPEC_FILE" 3; then
    PYTEST_EXIT=0
    AUTO_FIXES=$(grep -c "Corrigido:" /dev/stdin 2>/dev/null || true)
    # Re-capture final pytest output for the summary
    PYTEST_OUT=$(cd "$OUTPUT_DIR" && python3 -m pytest test_main.py -v --tb=short 2>&1) || true
  fi
fi

# ─────────────────────────────────────────────
# Resumo final
# ─────────────────────────────────────────────
TOTAL_END=$(date +%s)
TOTAL=$(( TOTAL_END - TOTAL_START ))

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                   Resumo                        ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  Spec:    ${SPEC_FILE}"
echo -e "${CYAN}║${NC}  Código:  ${OUTPUT_DIR}"

PASSED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= passed)' || echo "0")
FAILED=$(echo "$PYTEST_OUT" | grep -oP '\d+(?= failed)' || echo "0")

if [ "$PYTEST_EXIT" -eq 0 ]; then
  echo -e "${CYAN}║${NC}  Testes:  ${GREEN}${PASSED} passando ✓${NC}"
else
  echo -e "${CYAN}║${NC}  Testes:  ${GREEN}${PASSED} passando${NC} / ${RED}${FAILED} falhando ✗${NC}"
fi

if [ "$AUTO_FIXES" -gt 0 ]; then
  echo -e "${CYAN}║${NC}  Auto-fixes: ${YELLOW}${AUTO_FIXES} arquivo(s) corrigido(s) pelo Fix Agent${NC}"
fi

echo -e "${CYAN}║${NC}  Tempo total: ${TOTAL}s (~$(( TOTAL / 60 ))min)"
echo -e "${CYAN}║${NC}  LLM externo: 0 chamadas"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"

# limpar temporários
rm -f /tmp/_pp_p1.json /tmp/_pp_p2.json /tmp/_pp_r1.json /tmp/_pp_r2.json

exit $PYTEST_EXIT
