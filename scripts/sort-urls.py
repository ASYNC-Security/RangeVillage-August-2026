#!/usr/bin/env python3
"""Build fair Nuclei targets and prioritised JavaScript candidates from crawl output."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

STATIC_EXTENSIONS = {
    ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".avi",
    ".mov", ".pdf", ".webp", ".bmp", ".map",
}

MAIN_JS_NAME_RE = re.compile(
    r"^(?:main|app|application|client|bundle|index)(?:[._-].*)?(?:\.js)?$",
    re.IGNORECASE,
)
FEATURE_TERMS = (
    "auth", "login", "account", "admin", "checkout", "payment",
    "profile", "user", "api", "cart", "product",
)
VENDOR_TERMS = (
    "vendor", "jquery", "bootstrap", "react", "angular", "polyfill",
    "require", "analytics", "tracking", "recaptcha",
)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]


def normalize_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def has_backslash_artifact(path: str) -> bool:
    lowered = path.lower()
    return "\\" in path or "%5c" in lowered


def javascript_priority(url: str) -> tuple[int, int]:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    name = path.rsplit("/", 1)[-1]

    if any(term in path for term in VENDOR_TERMS):
        category = 3
    elif MAIN_JS_NAME_RE.match(name):
        category = 0
    elif any(term in path for term in FEATURE_TERMS):
        category = 1
    else:
        category = 2

    extensionless = 1 if extension(parsed.path) == "" else 0
    return category, extensionless


def write_lines(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", default="output/live-urls.txt")
    parser.add_argument("--discovered", default="output/discovered-urls.txt")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--max-javascript-candidates-per-host", type=int, default=10)
    args = parser.parse_args()

    live_urls: list[str] = []
    live_hosts: list[str] = []
    live_url_for_host: dict[str, str] = {}

    for raw in read_lines(Path(args.live)):
        url = normalize_url(raw)
        if not url:
            continue
        host = (urlsplit(url).hostname or "").lower()
        if host and host not in live_url_for_host:
            live_url_for_host[host] = url
            live_hosts.append(host)
            live_urls.append(url)

    allowed_hosts = set(live_hosts)
    candidates_by_host: dict[str, list[tuple[int, str]]] = defaultdict(list)
    seen_candidates: set[str] = set()
    ignored: list[str] = []

    for discovery_order, raw in enumerate(read_lines(Path(args.discovered))):
        url = normalize_url(raw)
        if not url:
            ignored.append(f"{raw}\tinvalid or non-HTTP URL")
            continue

        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host not in allowed_hosts:
            ignored.append(f"{url}\toutside the live FQDN list")
            continue

        if has_backslash_artifact(parsed.path):
            ignored.append(f"{url}\tmalformed backslash crawl artifact")
            continue

        ext = extension(parsed.path)
        if ext in STATIC_EXTENSIONS:
            ignored.append(f"{url}\tstatic file")
            continue

        if url in seen_candidates:
            continue

        if ext == ".js" or ext == "":
            seen_candidates.add(url)
            candidates_by_host[host].append((discovery_order, url))
        else:
            ignored.append(f"{url}\tnot a JavaScript candidate")

    javascript: list[str] = []
    per_host_selected: dict[str, int] = {}
    limit = max(0, args.max_javascript_candidates_per_host)

    for host in live_hosts:
        ranked = sorted(
            candidates_by_host[host],
            key=lambda item: (*javascript_priority(item[1]), item[0]),
        )
        selected = ranked[:limit]
        javascript.extend(url for _, url in selected)
        per_host_selected[host] = len(selected)
        for _, url in ranked[limit:]:
            ignored.append(f"{url}\tnot selected for JavaScript review: per-host candidate limit reached")

    output_dir = Path(args.output_dir)
    write_lines(output_dir / "nuclei-targets.txt", live_urls)
    write_lines(output_dir / "javascript-urls.txt", javascript)
    write_lines(output_dir / "ignored-urls.txt", ignored)

    summary = {
        "status": "success",
        "allowed_fqdns": len(allowed_hosts),
        "nuclei_targets": len(live_urls),
        "nuclei_policy": "one live URL per FQDN",
        "javascript_candidates": len(javascript),
        "javascript_candidate_limit_per_host": limit,
        "javascript_priority": "main/application, feature, other, vendor/framework",
        "hosts_with_javascript_candidates": sum(1 for value in per_host_selected.values() if value),
        "ignored_urls": len(ignored),
        "files": {
            "nuclei": str(output_dir / "nuclei-targets.txt"),
            "javascript": str(output_dir / "javascript-urls.txt"),
            "ignored": str(output_dir / "ignored-urls.txt"),
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
