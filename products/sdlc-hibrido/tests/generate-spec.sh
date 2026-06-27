#!/usr/bin/env bash
# Generate or refine a PRD/spec through WF1.
#
# Usage:
#   ./generate-spec.sh <idea> <spec-file>
#   ./generate-spec.sh <idea> <spec-file> <refinement> <previous-spec-file>
set -euo pipefail

IDEA="${1:-}"
SPEC_FILE="${2:-}"
REFINEMENT="${3:-}"
PREVIOUS_SPEC_FILE="${4:-}"

WF1="http://localhost:5678/webhook/sdlc-poc-chat"

if [ -z "$IDEA" ] || [ -z "$SPEC_FILE" ]; then
  echo "Uso: $0 <idea> <spec-file> [refinement] [previous-spec-file]"
  exit 1
fi

python3 - "$IDEA" "$SPEC_FILE" "$REFINEMENT" "$PREVIOUS_SPEC_FILE" "$WF1" << 'PYEOF'
import json
import re
import subprocess
import sys
import time

idea, spec_file, refinement, previous_spec_file, wf1 = sys.argv[1:]

if refinement:
    previous = open(previous_spec_file).read() if previous_spec_file else ""
    messages = [
        {
            "role": "user",
            "content": (
                f"Ideia original: {idea}\n\n"
                f"Spec anterior:\n{previous}\n\n"
                f"Refinamento solicitado: {refinement}\n\n"
                "Não faça perguntas. Incorpore o refinamento e gere a spec completa."
            ),
        }
    ]
else:
    messages = [
        {
            "role": "user",
            "content": (
                f"Minha ideia: {idea}\n\n"
                "Não faça perguntas de descoberta. Assuma defaults razoáveis quando faltar detalhe. "
                "A próxima mensagem será o comando para gerar a spec."
            ),
        }
    ]

payload = {"chatInput": "gerar spec", "messages": messages}

start = time.time()
result = subprocess.run(
    [
        "curl", "-s", "-X", "POST", wf1,
        "-H", "Content-Type: application/json",
        "--max-time", "120",
        "--data", json.dumps(payload),
    ],
    capture_output=True,
    text=True,
    timeout=130,
)

if result.returncode != 0:
    print(f"ERRO curl: {result.stderr}", file=sys.stderr)
    sys.exit(1)

data = json.loads(result.stdout)
output = data.get("output", "")
match = re.search(r"---SPEC-START---\s*(.*?)\s*---SPEC-END---", output, re.S)
if not match:
    retry_payload = {
        "chatInput": (
            "gerar spec\n\n"
            "Você respondeu sem o bloco obrigatório. Agora gere a SPEC completa diretamente, "
            "sem perguntas, usando exatamente ---SPEC-START--- e ---SPEC-END---. "
            "Assuma defaults razoáveis para ambiguidades."
        ),
        "messages": messages + [{"role": "assistant", "content": output}],
    }
    retry = subprocess.run(
        [
            "curl", "-s", "-X", "POST", wf1,
            "-H", "Content-Type: application/json",
            "--max-time", "120",
            "--data", json.dumps(retry_payload),
        ],
        capture_output=True,
        text=True,
        timeout=130,
    )
    if retry.returncode != 0:
        print(f"ERRO curl retry: {retry.stderr}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(retry.stdout)
    output = data.get("output", "")
    match = re.search(r"---SPEC-START---\s*(.*?)\s*---SPEC-END---", output, re.S)

if not match:
    print(output)
    print("\nERRO: resposta sem bloco ---SPEC-START--- / ---SPEC-END---", file=sys.stderr)
    sys.exit(2)

spec = match.group(1).strip() + "\n"
with open(spec_file, "w") as f:
    f.write(spec)

rf_count = len(re.findall(r"^RF-\d+", spec, re.M))
print(f"SPEC_FILE={spec_file}")
print(f"DISCOVERY_SECONDS={int(time.time() - start)}")
print(f"RF_COUNT={rf_count}")
print("\n--- SPEC APROVAVEL ---\n")
print(spec)
PYEOF
