#!/usr/bin/env python3
"""Group reviewed Nuclei JSONL findings by FQDN for AI analysis."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit


def normalise_host(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    candidate = text if "://" in text else f"//{text}"
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").lower()
    if host:
        return host

    return text.split("/", 1)[0].split(":", 1)[0].lower()


def finding_host(finding: dict[str, object]) -> str:
    for key in ("host", "matched-at", "matched", "url"):
        host = normalise_host(finding.get(key))
        if host:
            return host

    request = finding.get("request")
    if isinstance(request, dict):
        host = normalise_host(request.get("url"))
        if host:
            return host

    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="results/nuclei-findings.jsonl")
    args = parser.parse_args()

    path = Path(args.input)
    groups: dict[str, list[str]] = defaultdict(list)

    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                finding = json.loads(line)
            except json.JSONDecodeError:
                groups["unknown"].append(line)
                continue
            if not isinstance(finding, dict):
                groups["unknown"].append(line)
                continue
            groups[finding_host(finding)].append(line)

    if not groups:
        print(json.dumps({
            "host": "__no_findings__",
            "nuclei_results": '{"status":"no_findings","message":"No reviewed Nuclei findings remain."}',
        }))
        return 0

    for host, lines in groups.items():
        print(json.dumps({"host": host, "nuclei_results": "\n".join(lines)}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
