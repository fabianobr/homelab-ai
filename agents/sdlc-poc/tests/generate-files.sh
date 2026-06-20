#!/usr/bin/env bash
# Generate implementation files one at a time from a spec, with progressive context.
# Each generated file is passed as context to subsequent generations, ensuring consistent
# field names, class names, and import paths across all files.
#
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
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "=== Spec to Files (with progressive context) ==="
echo "Spec: $SPEC_FILE"
echo "Output: $OUTPUT_DIR"
echo "Files: ${FILES[*]}"
echo ""

TOTAL_START=$(date +%s)

# Build all_files JSON array once
ALL_FILES_JSON=$(python3 -c "import json, sys; print(json.dumps(sys.argv[1:]))" "${FILES[@]}")

# Context accumulates as files are generated: [{filename, content}, ...]
CONTEXT_JSON="[]"

for filename in "${FILES[@]}"; do
  echo "Generating $filename..."
  FILE_START=$(date +%s)

  # Write payload to temp file to avoid shell quoting issues
  TMPFILE=$(mktemp /tmp/wf3-payload-XXXXXX.json)
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

  RESPONSE=$(curl -s -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d @"$TMPFILE" \
    --max-time 1300)
  rm -f "$TMPFILE"

  FILE_END=$(date +%s)
  ELAPSED=$((FILE_END - FILE_START))

  # Save file and update context for next iteration
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
    print(f"  OK: {d.get('lines', '?')} lines in {elapsed}s", file=sys.stderr)
    # Append this file to context for next generation
    context = json.loads(context_json)
    context.append({"filename": filename, "content": content})
    print(json.dumps(context))
except Exception as e:
    print(f"  ERROR after {elapsed}s: {e}. Response: {response_str[:200]}", file=sys.stderr)
    sys.exit(1)
PYEOF
)
done

TOTAL_END=$(date +%s)
echo ""
echo "=== Done in $((TOTAL_END - TOTAL_START))s ==="
echo "Files written to: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
