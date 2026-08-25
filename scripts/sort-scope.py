#!/usr/bin/env python3
"""Sort copied scope entries into wildcard, direct, and unsupported lists."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)
HOST_PORT_RE = re.compile(r"^(.+?):(\d{1,5})$")
BULLET_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s+")


def clean_line(raw: str) -> str:
    value = raw.strip().strip("`\"'")
    value = BULLET_RE.sub("", value)
    return value.strip()


def normalize_domain(value: str) -> str | None:
    value = value.strip().lower().rstrip(".")
    if not value or not DOMAIN_RE.fullmatch(value):
        return None
    return value


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def classify(value: str) -> tuple[str, str, str | None]:
    """Return (category, normalized_value, reason)."""
    lowered = value.lower()

    if any(lowered.startswith(prefix) for prefix in ("out of scope", "excluded", "not eligible")):
        return "unsupported", value, "scope note was not parsed automatically"

    try:
        network = ipaddress.ip_network(value, strict=False)
        if "/" in value:
            return "unsupported", str(network), "CIDR ranges are not used in this workshop"
    except ValueError:
        pass

    # Full URLs, including wildcard URLs copied from some platforms.
    if lowered.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        host = parsed.hostname
        if not host:
            return "unsupported", value, "URL has no valid hostname"

        if host.startswith("*."):
            if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                return "unsupported", value, "wildcard URL contains a path, query, or fragment"
            domain = normalize_domain(host[2:])
            if domain:
                return "wildcard", domain, None
            return "unsupported", value, "invalid wildcard domain"

        host_is_ip = is_ip(host)
        if host_is_ip:
            normalized_host = str(ipaddress.ip_address(host))
        else:
            normalized_host = normalize_domain(host)
            if not normalized_host:
                return "unsupported", value, "URL hostname is not a valid domain or IP"

        try:
            port = parsed.port
        except ValueError:
            return "unsupported", value, "URL contains an invalid port"

        display_host = f"[{normalized_host}]" if host_is_ip and ":" in normalized_host else normalized_host
        netloc = display_host if port is None else f"{display_host}:{port}"
        normalized = urlunsplit(
            (parsed.scheme.lower(), netloc, parsed.path or "", parsed.query, parsed.fragment)
        )
        return "direct", normalized, None

    if value.startswith("*."):
        domain = normalize_domain(value[2:])
        if domain:
            return "wildcard", domain, None
        return "unsupported", value, "invalid wildcard domain"

    if any(ch in value for ch in ("/", "?", "#")):
        return "unsupported", value, "path-like entry requires http:// or https://"

    if is_ip(value):
        return "direct", str(ipaddress.ip_address(value)), None

    # Scheme-less host with an explicit port.
    match = HOST_PORT_RE.fullmatch(value)
    if match:
        host, port_text = match.groups()
        port = int(port_text)
        if not 1 <= port <= 65535:
            return "unsupported", value, "port is outside 1-65535"
        if is_ip(host):
            return "direct", f"{ipaddress.ip_address(host)}:{port}", None
        domain = normalize_domain(host)
        if domain:
            return "direct", f"{domain}:{port}", None
        return "unsupported", value, "invalid hostname before port"

    domain = normalize_domain(value)
    if domain:
        return "direct", domain, None

    return "unsupported", value, "unsupported or malformed scope entry"


def write_lines(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(values)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="input/scope.txt", help="scope text file")
    parser.add_argument("--output-dir", default="output", help="output directory")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    if not input_path.is_file():
        raise SystemExit(f"Scope file not found: {input_path}")

    wildcard: list[str] = []
    direct: list[str] = []
    unsupported: list[str] = []
    seen_wildcard: set[str] = set()
    seen_direct: set[str] = set()

    total_lines = 0
    ignored_lines = 0

    for raw in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
        total_lines += 1
        value = clean_line(raw)
        if not value or value.startswith("#"):
            ignored_lines += 1
            continue

        category, normalized, reason = classify(value)
        if category == "wildcard":
            if normalized not in seen_wildcard:
                seen_wildcard.add(normalized)
                wildcard.append(normalized)
        elif category == "direct":
            if normalized not in seen_direct:
                seen_direct.add(normalized)
                direct.append(normalized)
        else:
            unsupported.append(f"{value}\t{reason}")

    write_lines(output_dir / "wildcard-domains.txt", wildcard)
    write_lines(output_dir / "direct-targets.txt", direct)
    write_lines(output_dir / "unsupported-scope.txt", unsupported)

    summary = {
        "status": "success_with_warnings" if unsupported else "success",
        "input_file": str(input_path),
        "total_lines": total_lines,
        "ignored_blank_or_comment_lines": ignored_lines,
        "wildcard_domains": len(wildcard),
        "direct_targets": len(direct),
        "unsupported_entries": len(unsupported),
        "files": {
            "wildcard": str(output_dir / "wildcard-domains.txt"),
            "direct": str(output_dir / "direct-targets.txt"),
            "unsupported": str(output_dir / "unsupported-scope.txt"),
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
