#!/usr/bin/env bash
# Crawl live URLs and save one consolidated URL list.
set -Eeuo pipefail

INPUT="${1:-output/live-urls.txt}"
OUTPUT="${2:-output/discovered-urls.txt}"

mkdir -p "$(dirname "$OUTPUT")"
: > "$OUTPUT"

if [[ ! -s "$INPUT" ]]; then
  printf '{"status":"success","message":"No live URLs supplied","results":0,"output":"%s"}\n' "$OUTPUT"
  exit 0
fi

command -v katana >/dev/null 2>&1 || {
  echo "katana was not found. Run ./setup.sh first." >&2
  exit 1
}

katana \
  -list "$INPUT" \
  -silent \
  -depth 2 \
  -js-crawl \
  -field-scope fqdn \
  -max-domain-pages 10 \
  -rate-limit 5 \
  -output "$OUTPUT" \
  </dev/null

python3 - "$OUTPUT" <<'PY'
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
lines = [x.strip() for x in path.read_text(errors='replace').splitlines() if x.strip()]
unique = list(dict.fromkeys(lines))
path.write_text('\n'.join(unique) + ('\n' if unique else ''), encoding='utf-8')
print(json.dumps({"status":"success","discovered_urls":len(unique),"output":str(path)}, indent=2))
PY
