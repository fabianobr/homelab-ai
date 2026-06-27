#!/usr/bin/env bash
# Deterministic interactive SDLC runner with 3 approval gates.
#
# Usage: ./sdlc-hybrid-interactive.sh "<product idea>"
set -euo pipefail

IDEA="${*:-}"

if [ -z "$IDEA" ]; then
  echo "Uso: $0 <descrição do produto>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
SPEC_FILE="/tmp/sdlc-spec-$TIMESTAMP.md"
TEST_FILE="/tmp/sdlc-tests-$TIMESTAMP.py"
OUTPUT_DIR="/tmp/sdlc-output-$TIMESTAMP"
SPEC_REFINEMENTS=0
FIX_LOOPS=0
FINAL_PYTEST="não executado"

ask() {
  local prompt="$1"
  local answer
  printf "%s " "$prompt"
  read -r answer
  printf "%s" "$answer"
}

show_file() {
  local title="$1"
  local file="$2"
  echo ""
  echo "===== $title: $file ====="
  cat "$file"
  echo "===== fim de $title ====="
  echo ""
}

precheck() {
  echo "[pré-check]"
  local failed=0
  curl -sf http://localhost:5678/healthz >/dev/null && echo "n8n:ok" || { echo "n8n:OFFLINE"; failed=1; }
  curl -sf http://localhost:4000/ >/dev/null && echo "litellm:ok" || { echo "litellm:OFFLINE"; failed=1; }
  curl -sf http://localhost:11434/api/tags >/dev/null && echo "ollama:ok" || { echo "ollama:OFFLINE"; failed=1; }
  if [ "$failed" -ne 0 ]; then
    echo "Pré-check falhou. Encerrando."
    exit 1
  fi
}

gate_spec() {
  "$SCRIPT_DIR/generate-spec.sh" "$IDEA" "$SPEC_FILE"
  while true; do
    show_file "SPEC" "$SPEC_FILE"

    echo "Spec gerada. O que você quer fazer?"
    echo "[A] Aprovar e gerar testes"
    echo "[R] Refinar (me diga o que mudar)"
    echo "[C] Cancelar"
    echo ""
    echo "Aguardo sua decisão antes de prosseguir."

    decision="$(ask "> ")"
    case "${decision,,}" in
      a|aprovar*)
        return 0
        ;;
      r|refinar*)
        refinement="$(ask "Refinamento: ")"
        "$SCRIPT_DIR/generate-spec.sh" "$IDEA" "$SPEC_FILE" "$refinement" "$SPEC_FILE"
        SPEC_REFINEMENTS=$((SPEC_REFINEMENTS + 1))
        ;;
      c|cancelar*)
        echo "Cancelado no Gate 1."
        exit 0
        ;;
      *)
        echo "Resposta inválida. Use A, R ou C."
        ;;
    esac
  done
}

gate_tests() {
  "$SCRIPT_DIR/generate-tests.sh" "$SPEC_FILE" "$TEST_FILE"
  while true; do
    show_file "test_main.py" "$TEST_FILE"
    test_count="$(grep -c '^def test_' "$TEST_FILE" || true)"

    echo "Contrato de testes gerado ($test_count testes). O que você quer fazer?"
    echo "[A] Aprovar e gerar código"
    echo "[E] Editar testes manualmente"
    echo "[C] Cancelar"
    echo ""
    echo "Aguardo sua decisão antes de prosseguir."

    decision="$(ask "> ")"
    case "${decision,,}" in
      a|aprovar*)
        return 0
        ;;
      e|editar*)
        echo "Edite manualmente: $TEST_FILE"
        ready="$(ask "Quando terminar, digite OK para revisar novamente: ")"
        if [ -n "$ready" ]; then
          show_file "test_main.py editado" "$TEST_FILE"
        fi
        ;;
      c|cancelar*)
        echo "Cancelado no Gate 2."
        exit 0
        ;;
      *)
        echo "Resposta inválida. Use A, E ou C."
        ;;
    esac
  done
}

gate_code() {
  mkdir -p "$OUTPUT_DIR"
  while true; do
    set +e
    "$SCRIPT_DIR/generate-codegen.sh" "$SPEC_FILE" "$TEST_FILE" "$OUTPUT_DIR"
    codegen_exit=$?
    set -e

    echo ""
    echo "Arquivos gerados:"
    wc -l "$OUTPUT_DIR"/*.py || true

    if [ "$codegen_exit" -eq 0 ]; then
      FINAL_PYTEST="passou"
      echo "Todos os testes passaram. Aceitar resultado?"
      echo "[A] Aceitar"
      echo "[C] Cancelar"
      echo ""
      echo "Aguardo sua decisão antes de prosseguir."

      decision="$(ask "> ")"
      case "${decision,,}" in
        a|aceitar*) return 0 ;;
        c|cancelar*) echo "Cancelado no Gate 3."; exit 0 ;;
        *) echo "Resposta inválida. Use A ou C." ;;
      esac
    else
      FINAL_PYTEST="falhou"
      failed="$(cd "$OUTPUT_DIR" && python3 -m pytest test_main.py -q 2>/dev/null | grep -oE '[0-9]+ failed' | head -1 || true)"
      failed="${failed:-testes falharam}"
      echo "$failed. O que você quer fazer?"
      echo "[F] Rodar fix loop automático (WF4, até 3 tentativas)"
      echo "[M] Aceitar assim — vou corrigir manualmente"
      echo "[C] Cancelar"
      echo ""
      echo "Aguardo sua decisão antes de prosseguir."

      decision="$(ask "> ")"
      case "${decision,,}" in
        f|fix*)
          FIX_LOOPS=$((FIX_LOOPS + 1))
          set +e
          bash "$SCRIPT_DIR/fix-loop.sh" "$OUTPUT_DIR" "$SPEC_FILE" 3
          fix_exit=$?
          set -e
          if [ "$fix_exit" -eq 0 ]; then
            FINAL_PYTEST="passou após fix"
          fi
          ;;
        m|manual*|aceitar*)
          return 0
          ;;
        c|cancelar*)
          echo "Cancelado no Gate 3."
          exit 0
          ;;
        *)
          echo "Resposta inválida. Use F, M ou C."
          ;;
      esac
    fi
  done
}

report() {
  echo ""
  echo "## Resultado do Pipeline SDLC Híbrido"
  echo ""
  echo "### Artefatos"
  echo "- Spec: $SPEC_FILE"
  echo "- Testes: $TEST_FILE"
  echo "- Output: $OUTPUT_DIR"
  echo ""
  echo "### Código gerado"
  wc -l "$OUTPUT_DIR"/*.py || true
  echo ""
  echo "### Gates"
  echo "- Refinamentos de spec: $SPEC_REFINEMENTS"
  echo "- Fix loops executados: $FIX_LOOPS"
  echo "- Pytest final: $FINAL_PYTEST"
}

cd "$SCRIPT_DIR"
precheck
gate_spec
gate_tests
gate_code
report
