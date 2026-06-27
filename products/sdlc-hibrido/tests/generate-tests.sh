#!/usr/bin/env bash
# Generate test_main.py from an approved spec through WF5.
#
# Usage: ./generate-tests.sh <spec-file> <test-file>
set -euo pipefail

SPEC_FILE="${1:-}"
TEST_FILE="${2:-}"

WF5="http://localhost:5678/webhook/sdlc-poc-spec-to-tests"

if [ -z "$SPEC_FILE" ] || [ -z "$TEST_FILE" ] || [ ! -f "$SPEC_FILE" ]; then
  echo "Uso: $0 <spec-file> <test-file>"
  exit 1
fi

python3 - "$SPEC_FILE" "$TEST_FILE" "$WF5" << 'PYEOF'
import json
import subprocess
import sys
import time

spec_file, test_file, wf5 = sys.argv[1:]
payload = {
    "spec": open(spec_file).read(),
    "all_files": ["models.py", "routes.py", "main.py", "test_main.py"],
}

start = time.time()
result = subprocess.run(
    [
        "curl", "-s", "-X", "POST", wf5,
        "-H", "Content-Type: application/json",
        "--max-time", "1300",
        "--data", json.dumps(payload),
    ],
    capture_output=True,
    text=True,
    timeout=1310,
)

if result.returncode != 0:
    print(f"ERRO curl: {result.stderr}", file=sys.stderr)
    sys.exit(1)

d = json.loads(result.stdout)
content = d.get("content", "")
if not content:
    print(f"ERRO: WF5 retornou conteúdo vazio. Response: {result.stdout[:300]}", file=sys.stderr)
    sys.exit(1)

with open(test_file, "w") as f:
    f.write(content)

test_count = sum(1 for line in content.splitlines() if line.startswith("def test_"))
print(f"TEST_FILE={test_file}")
print(f"TEST_GEN_SECONDS={int(time.time() - start)}")
print(f"TEST_COUNT={test_count}")
print("\n--- TEST_MAIN APROVAVEL ---\n")
print(content)
PYEOF
