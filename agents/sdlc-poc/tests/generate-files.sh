#!/usr/bin/env bash
# Generate implementation files one at a time from a spec.
# Usage: ./generate-files.sh <spec-file> [output-dir] [file1 file2 ...]
# Example: ./generate-files.sh spec.md ./output models.py routes.py main.py test_main.py
set -euo pipefail

SPEC_FILE="${1:-}"
OUTPUT_DIR="${2:-./generated}"
shift 2 2>/dev/null || true
FILES=("${@:-models.py routes.py main.py test_main.py}")

WEBHOOK="http://localhost:5678/webhook/sdlc-poc-spec-to-file"

if [ -z "$SPEC_FILE" ] || [ ! -f "$SPEC_FILE" ]; then
  echo "Usage: $0 <spec-file> [output-dir] [file1 file2 ...]"
  echo "Example: $0 spec.md ./output models.py routes.py main.py test_main.py"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
SPEC=$(cat "$SPEC_FILE")
ALL_FILES_JSON=$(printf '"%s",' "${FILES[@]}" | sed 's/,$//')

echo "=== Spec to Files ==="
echo "Spec: $SPEC_FILE"
echo "Output: $OUTPUT_DIR"
echo "Files: ${FILES[*]}"
echo ""

TOTAL_START=$(date +%s)

for filename in "${FILES[@]}"; do
  echo "Generating $filename..."
  FILE_START=$(date +%s)

  PAYLOAD=$(python3 -c "
import json, sys
spec = open('$SPEC_FILE').read()
payload = {
  'spec': spec,
  'filename': '$filename',
  'all_files': [$(echo "$ALL_FILES_JSON" | sed 's/,$//' | tr ',' '\n' | sed 's/^/\"/' | sed 's/$/\"/' | tr '\n' ',' | sed 's/,$//')]
}
print(json.dumps(payload))
")

  RESPONSE=$(curl -s -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    --max-time 1300)

  FILE_END=$(date +%s)
  ELAPSED=$((FILE_END - FILE_START))

  if echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); open('$OUTPUT_DIR/$filename','w').write(d['content']); print(f'  OK: {d[\"lines\"]} lines in ${ELAPSED}s')" 2>/dev/null; then
    :
  else
    echo "  ERROR after ${ELAPSED}s: $(echo "$RESPONSE" | head -c 200)"
  fi
done

TOTAL_END=$(date +%s)
echo ""
echo "=== Done in $((TOTAL_END - TOTAL_START))s ==="
echo "Files written to: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
