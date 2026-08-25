#!/usr/bin/env python3
"""Package downloaded JavaScript fairly across hosts for AI analysis."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_sources(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    shortened = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return shortened, True


def build_block(source: dict[str, object], content: str, truncated: bool) -> str:
    name = str(source.get("file", ""))
    host = str(source.get("host", "unknown"))
    source_url = str(source.get("source_url", "unknown"))
    final_url = str(source.get("final_url", source_url))
    digest = str(source.get("sha256", "unknown"))
    reported_bytes = int(source.get("bytes", 0))
    captured_bytes = int(source.get("captured_bytes", reported_bytes))
    download_truncated = bool(source.get("download_truncated", False))
    packaged_bytes = len(content.encode("utf-8"))

    header = (
        f"===== FILE: {name} =====\n"
        f"HOST: {host}\n"
        f"SOURCE: {source_url}\n"
    )
    if final_url != source_url:
        header += f"FINAL URL: {final_url}\n"
    header += (
        f"SHA256: {digest}\n"
        f"REPORTED BYTES: {reported_bytes}\n"
        f"CAPTURED BYTES: {captured_bytes}\n"
        f"PACKAGED BYTES: {packaged_bytes}\n"
    )
    if download_truncated:
        header += "DOWNLOAD: TRUNCATED DURING CAPTURE\n"
    if truncated:
        header += "CONTENT: TRUNCATED FOR REVIEW PACKAGE\n"
    return f"{header}\n{content}\n\n"


def fit_block(source: dict[str, object], text: str, max_content_bytes: int, max_block_bytes: int) -> tuple[str, bool] | None:
    content, truncated = truncate_utf8(text, min(max_content_bytes, max_block_bytes))
    block = build_block(source, content, truncated)

    while len(block.encode("utf-8")) > max_block_bytes and content:
        excess = len(block.encode("utf-8")) - max_block_bytes
        current = len(content.encode("utf-8"))
        next_limit = max(0, current - excess - 32)
        content, was_truncated = truncate_utf8(content, next_limit)
        truncated = truncated or was_truncated or next_limit < current
        block = build_block(source, content, truncated)

    if len(block.encode("utf-8")) > max_block_bytes:
        return None
    return block, truncated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="output/js")
    parser.add_argument("--output", default="output/js-review.txt")
    parser.add_argument("--max-total-bytes", type=int, default=500_000)
    parser.add_argument("--max-file-bytes", type=int, default=200_000)
    parser.add_argument("--emit-host-jsonl", action="store_true")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = load_sources(input_dir / "sources.json")

    host_order: list[str] = []
    sources_by_host: dict[str, list[dict[str, object]]] = defaultdict(list)
    notes: list[str] = []

    for source in sources:
        name = str(source.get("file", ""))
        if not name:
            continue
        path = input_dir / name
        if not path.is_file():
            notes.append(f"{name}\tfile missing")
            continue
        host = str(source.get("host", "unknown"))
        if host not in sources_by_host:
            host_order.append(host)
        sources_by_host[host].append(source)

    parts: list[str] = []
    host_parts: dict[str, list[str]] = defaultdict(list)
    total = 0
    host_count = len(host_order)
    host_budget = args.max_total_bytes // host_count if host_count else 0

    for host in host_order:
        remaining_host_budget = host_budget
        for source in sources_by_host[host]:
            name = str(source.get("file", ""))
            if not name:
                continue
            path = input_dir / name
            if remaining_host_budget <= 0:
                notes.append(f"{name}\tomitted because the per-host package share was reached")
                continue

            text = path.read_text(encoding="utf-8", errors="replace")
            fitted = fit_block(source, text, args.max_file_bytes, remaining_host_budget)
            if fitted is None:
                notes.append(f"{name}\tomitted because the remaining per-host package share was too small")
                continue

            block, truncated = fitted
            size = len(block.encode("utf-8"))
            if total + size > args.max_total_bytes:
                notes.append(f"{name}\tomitted because total package size limit was reached")
                continue

            if truncated:
                notes.append(f"{name}\tcontent truncated for the host-fair review package")
            parts.append(block)
            host_parts[host].append(block)
            total += size
            remaining_host_budget -= size

    packaged = "".join(parts)
    output.write_text(packaged, encoding="utf-8")
    notes_path = input_dir / "package-notes.txt"
    notes_path.write_text("\n".join(notes) + ("\n" if notes else ""), encoding="utf-8")

    if args.emit_host_jsonl:
        for host in host_order:
            host_package = "".join(host_parts.get(host, []))
            if host_package:
                print(json.dumps({"host": host, "javascript": host_package}))
    elif packaged:
        print(packaged, end="")
    else:
        print("No JavaScript files were packaged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
