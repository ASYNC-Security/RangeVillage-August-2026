#!/usr/bin/env python3
"""Download a bounded, host-fair set of prioritised JavaScript files with source metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
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
PRIORITY_LABELS = {
    0: "main/application JavaScript",
    1: "application feature JavaScript",
    2: "other verified JavaScript",
    3: "common vendor/framework JavaScript",
}


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]


def make_name(index: int, url: str) -> str:
    original = Path(urlsplit(url).path).name or "script.js"
    if not original.lower().endswith(".js"):
        original += ".js"
    original = SAFE_NAME_RE.sub("_", original)[:80]
    return f"js-{index:03d}-{original}"


def javascript_priority(url: str) -> int:
    path = urlsplit(url).path.lower()
    name = path.rsplit("/", 1)[-1]

    if any(term in path for term in VENDOR_TERMS):
        return 3
    if MAIN_JS_NAME_RE.match(name):
        return 0
    if any(term in path for term in FEATURE_TERMS):
        return 1
    return 2


class SameHostRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_host: str):
        super().__init__()
        self.allowed_host = allowed_host.lower()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        absolute = urljoin(req.full_url, newurl)
        new_host = (urlsplit(absolute).hostname or "").lower()
        if new_host != self.allowed_host:
            raise HTTPError(
                req.full_url,
                code,
                f"redirect outside original FQDN to {new_host or '<unknown>'}",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="output/javascript-urls.txt")
    parser.add_argument("--output-dir", default="output/js")
    parser.add_argument("--max-files-per-host", type=int, default=3)
    parser.add_argument("--max-attempts-per-host", type=int, default=10)
    parser.add_argument("--max-bytes", type=int, default=500_000)
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for path in output_dir.glob("*.js"):
        path.unlink()
    for name in ("sources.json", "skipped-downloads.json", "package-notes.txt"):
        (output_dir / name).unlink(missing_ok=True)

    sources: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    hashes: dict[str, str] = {}
    input_urls = read_lines(Path(args.input))

    host_order: list[str] = []
    urls_by_host: dict[str, list[str]] = defaultdict(list)
    for url in input_urls:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            skipped.append({"url": url, "host": host, "reason": "invalid HTTP(S) URL"})
            continue
        if host not in urls_by_host:
            host_order.append(host)
        urls_by_host[host].append(url)

    attempted_downloads = 0
    per_host_summary: dict[str, dict[str, int]] = {}

    for host in host_order:
        urls = urls_by_host[host]
        verified: list[dict[str, object]] = []
        host_hashes: set[str] = set()
        attempts = 0

        for index, url in enumerate(urls):
            if attempts >= args.max_attempts_per_host:
                for remaining_url in urls[index:]:
                    skipped.append({
                        "url": remaining_url,
                        "host": host,
                        "reason": "per-host download attempt limit reached",
                    })
                break

            attempts += 1
            attempted_downloads += 1

            try:
                opener = build_opener(SameHostRedirectHandler(host))
                request = Request(url, headers={"User-Agent": "RV-Engineering-Workshop/1.0"})
                with opener.open(request, timeout=args.timeout) as response:
                    final_url = response.geturl()
                    final_host = (urlsplit(final_url).hostname or "").lower()
                    if final_host != host:
                        raise ValueError(f"redirect outside original FQDN to {final_host or '<unknown>'}")
                    data = response.read(args.max_bytes + 1)
                    content_type = response.headers.get("Content-Type", "")
                    content_length = response.headers.get("Content-Length", "")
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                skipped.append({"url": url, "host": host, "reason": str(exc)})
                continue

            download_truncated = len(data) > args.max_bytes
            if download_truncated:
                data = data[: args.max_bytes]

            try:
                reported_bytes = int(content_length) if content_length else len(data)
            except ValueError:
                reported_bytes = len(data)

            content_type_lower = content_type.lower()
            is_javascript_type = "javascript" in content_type_lower or "ecmascript" in content_type_lower
            if not is_javascript_type and not urlsplit(final_url).path.lower().endswith(".js"):
                skipped.append({
                    "url": url,
                    "host": host,
                    "reason": f"unexpected content type: {content_type}",
                })
                continue

            digest = hashlib.sha256(data).hexdigest()
            if digest in host_hashes or digest in hashes:
                skipped.append({
                    "url": url,
                    "host": host,
                    "reason": "duplicate file content",
                    "duplicate_of": hashes.get(digest, "another verified candidate on this host"),
                })
                continue

            host_hashes.add(digest)
            verified.append({
                "url": url,
                "host": host,
                "final_url": final_url,
                "data": data,
                "sha256": digest,
                "bytes": reported_bytes,
                "captured_bytes": len(data),
                "download_truncated": download_truncated,
                "priority": javascript_priority(final_url),
                "input_order": index,
            })

        verified.sort(key=lambda item: (int(item["priority"]), int(item["input_order"])))
        selected = verified[: max(0, args.max_files_per_host)]
        not_selected = verified[max(0, args.max_files_per_host):]

        for item in selected:
            final_url = str(item["final_url"])
            digest = str(item["sha256"])
            name = make_name(len(sources) + 1, final_url)
            (output_dir / name).write_bytes(bytes(item["data"]))
            hashes[digest] = name
            sources.append({
                "file": name,
                "host": host,
                "source_url": str(item["url"]),
                "final_url": final_url,
                "sha256": digest,
                "bytes": int(item["bytes"]),
                "captured_bytes": int(item["captured_bytes"]),
                "download_truncated": bool(item["download_truncated"]),
                "selection_category": PRIORITY_LABELS[int(item["priority"])],
            })

        for item in not_selected:
            skipped.append({
                "url": str(item["url"]),
                "host": host,
                "reason": "verified JavaScript ranked below the per-host file limit",
                "selection_category": PRIORITY_LABELS[int(item["priority"])],
            })

        per_host_summary[host] = {
            "input_urls": len(urls),
            "download_attempts": attempts,
            "verified_unique": len(verified),
            "downloaded_unique": len(selected),
        }

    (output_dir / "sources.json").write_text(
        json.dumps(sources, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "skipped-downloads.json").write_text(
        json.dumps(skipped, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "status": "success",
        "input_urls": len(input_urls),
        "hosts": len(host_order),
        "download_attempts": attempted_downloads,
        "downloaded_unique": len(sources),
        "max_attempts_per_host": args.max_attempts_per_host,
        "max_files_per_host": args.max_files_per_host,
        "selection_priority": "main/application, feature, other, vendor/framework",
        "skipped": len(skipped),
        "per_host": per_host_summary,
        "output_dir": str(output_dir),
        "sources": str(output_dir / "sources.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
