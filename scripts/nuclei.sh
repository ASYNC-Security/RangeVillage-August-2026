#!/usr/bin/env bash
# Run the workshop Nuclei pass against the prepared target list.
set -Eeuo pipefail

INPUT="${1:-output/nuclei-targets.txt}"
OUTPUT="${2:-results/nuclei-findings.jsonl}"

mkdir -p "$(dirname "$OUTPUT")"
: > "$OUTPUT"

if [[ ! -s "$INPUT" ]]; then
  echo '{"status":"no_targets","message":"No Nuclei targets were supplied."}'
  exit 0
fi

command -v nuclei >/dev/null 2>&1 || {
  echo "nuclei was not found. Run ./setup.sh first." >&2
  exit 1
}

nuclei \
  -list "$INPUT" \
  -tags cve,exposure,misconfig \
  -severity low,medium,high,critical \
  -exclude-tags fuzz,dos,bruteforce \
  -no-stdin \
  -rate-limit 50 \
  -timeout 5 \
  -retries 0 \
  -omit-raw \
  -omit-template \
  -jsonl-export "$OUTPUT" \
  >/dev/null

if [[ -s "$OUTPUT" ]]; then
  cat "$OUTPUT"
else
  echo '{"status":"no_findings","message":"Nuclei completed without findings."}'
fi
