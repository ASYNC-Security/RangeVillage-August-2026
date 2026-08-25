#!/usr/bin/env bash
# Probe the combined target list and save live URLs.
set -Eeuo pipefail

INPUT="${1:-output/targets.txt}"
OUTPUT="${2:-output/live-urls.txt}"

mkdir -p "$(dirname "$OUTPUT")"
: > "$OUTPUT"

if [[ ! -s "$INPUT" ]]; then
  printf '{"status":"success","message":"No targets supplied","results":0,"output":"%s"}\n' "$OUTPUT"
  exit 0
fi

command -v httpx >/dev/null 2>&1 || {
  echo "ProjectDiscovery httpx was not found. Run ./setup.sh first." >&2
  exit 1
}

httpx \
  -l "$INPUT" \
  -silent \
  -no-stdin \
  -rate-limit 10 \
  -o "$OUTPUT"

python3 - "$OUTPUT" <<'PY'
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
lines = [x.strip() for x in path.read_text(errors='replace').splitlines() if x.strip()]
# Preserve order while removing duplicates.
unique = list(dict.fromkeys(lines))
path.write_text('\n'.join(unique) + ('\n' if unique else ''), encoding='utf-8')
print(json.dumps({"status":"success","live_urls":len(unique),"output":str(path)}, indent=2))
PY
