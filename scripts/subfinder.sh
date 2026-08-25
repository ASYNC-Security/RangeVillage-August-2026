#!/usr/bin/env bash
# Run Subfinder only against wildcard scope entries.
set -Eeuo pipefail

INPUT="${1:-output/wildcard-domains.txt}"
OUTPUT="${2:-output/subdomains.txt}"
TMP="${OUTPUT}.raw"

mkdir -p "$(dirname "$OUTPUT")"
: > "$OUTPUT"

if [[ ! -s "$INPUT" ]]; then
  printf '{"status":"success","message":"No wildcard domains supplied","results":0,"output":"%s"}\n' "$OUTPUT"
  exit 0
fi

command -v subfinder >/dev/null 2>&1 || {
  echo "subfinder was not found. Run ./setup.sh first." >&2
  exit 1
}

subfinder -dL "$INPUT" -silent -o "$TMP" </dev/null

python3 - "$INPUT" "$TMP" "$OUTPUT" <<'PY'
from pathlib import Path
import json
import sys

bases_path, raw_path, output_path = map(Path, sys.argv[1:])
bases = [x.strip().lower().rstrip('.') for x in bases_path.read_text().splitlines() if x.strip()]
seen = set()
kept = []
for line in raw_path.read_text(errors='replace').splitlines():
    host = line.strip().lower().rstrip('.')
    if not host or host in seen:
        continue
    if any(host == base or host.endswith('.' + base) for base in bases):
        seen.add(host)
        kept.append(host)
output_path.write_text('\n'.join(kept) + ('\n' if kept else ''), encoding='utf-8')
print(json.dumps({"status":"success","results":len(kept),"output":str(output_path)}, indent=2))
PY

rm -f "$TMP"
