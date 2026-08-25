#!/usr/bin/env python3
"""Combine discovered subdomains and direct targets into one list."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subdomains", default="output/subdomains.txt")
    parser.add_argument("--direct", default="output/direct-targets.txt")
    parser.add_argument("--output", default="output/targets.txt")
    args = parser.parse_args()

    def dedupe_key(value: str) -> str:
        if value.lower().startswith(("http://", "https://")):
            parsed = urlsplit(value)
            return urlunsplit((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.query,
                parsed.fragment,
            ))
        return value.lower()

    seen: set[str] = set()
    targets: list[str] = []
    for value in read_lines(Path(args.subdomains)) + read_lines(Path(args.direct)):
        key = dedupe_key(value)
        if key not in seen:
            seen.add(key)
            targets.append(value)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(targets) + ("\n" if targets else ""), encoding="utf-8")

    print(json.dumps({"status": "success", "targets": len(targets), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
