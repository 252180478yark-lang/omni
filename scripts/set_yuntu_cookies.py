#!/usr/bin/env python3
"""Import Yuntu cookies into the local Knowledge Engine from a secret file.

Only an absolute file path outside the repository is accepted.  Cookie values
are never accepted as CLI arguments and never appear in command output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import httpx


COOKIE_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}$")
DEFAULT_BASE_URL = "http://localhost:8002/api/v1/knowledge"


class CookieImportError(ValueError):
    """Cookie import input is unsafe or invalid."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def external_secret_file(value: str | os.PathLike[str]) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise CookieImportError("secret-file path must be absolute")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(repository_root())
    except ValueError:
        pass
    else:
        raise CookieImportError("secret-file path must be outside the repository")
    if not resolved.is_file() or resolved.stat().st_size > 1_000_000:
        raise CookieImportError("secret-file is missing or exceeds the size limit")
    return resolved


def local_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise CookieImportError("Knowledge Engine URL must resolve to the local host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CookieImportError("Knowledge Engine URL must not contain credentials or query data")
    return value.rstrip("/")


def _cookie(name: str, value: str, domain: str = ".oceanengine.com", path: str = "/") -> dict[str, str]:
    if not COOKIE_NAME.fullmatch(name) or not value or any(char in value for char in "\r\n"):
        raise CookieImportError("secret-file contains an invalid cookie")
    if not domain.startswith(".") or any(char in domain for char in "\r\n/\\"):
        raise CookieImportError("secret-file contains an invalid cookie domain")
    if not path.startswith("/") or any(char in path for char in "\r\n"):
        raise CookieImportError("secret-file contains an invalid cookie path")
    return {"name": name, "value": value, "domain": domain, "path": path}


def parse_cookie_secret(text: str) -> list[dict[str, str]]:
    stripped = text.strip()
    if not stripped:
        raise CookieImportError("secret-file is empty")
    try:
        decoded: Any = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, Mapping):
        decoded = decoded.get("cookies")
    if isinstance(decoded, Sequence) and not isinstance(decoded, (str, bytes)):
        cookies = [
            _cookie(
                str(item.get("name") or ""),
                str(item.get("value") or ""),
                str(item.get("domain") or ".oceanengine.com"),
                str(item.get("path") or "/"),
            )
            for item in decoded
            if isinstance(item, Mapping)
        ]
        if len(cookies) != len(decoded) or not cookies:
            raise CookieImportError("cookie JSON must contain cookie objects")
        return cookies
    cookies = []
    for pair in stripped.split(";"):
        if not pair.strip():
            continue
        if "=" not in pair:
            raise CookieImportError("cookie header contains a malformed pair")
        name, value = pair.split("=", 1)
        cookies.append(_cookie(name.strip(), value.strip()))
    if not cookies:
        raise CookieImportError("cookie header contains no cookies")
    return cookies


async def send_cookie_reference(secret_file: Path, base_url: str, *, timeout_seconds: float = 10.0) -> int:
    cookies = parse_cookie_secret(secret_file.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
        response = await client.post(f"{base_url}/harvester/save-auth", json={"cookies": cookies})
        response.raise_for_status()
    return len(cookies)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-file", default=os.getenv("OMNI_COOKIE_SECRET_FILE"))
    parser.add_argument("--base-url", default=os.getenv("KNOWLEDGE_ENGINE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    if not args.secret_file:
        raise SystemExit("cookie secret-file reference is required")
    if not 0 < args.timeout_seconds <= 30:
        raise SystemExit("timeout-seconds must be between 0 and 30")
    try:
        secret_file = external_secret_file(args.secret_file)
        base_url = local_base_url(args.base_url)
        count = await send_cookie_reference(secret_file, base_url, timeout_seconds=args.timeout_seconds)
    except (CookieImportError, OSError, UnicodeError, httpx.HTTPError) as exc:
        raise SystemExit(f"cookie import refused: {type(exc).__name__}") from None
    print(f"Imported {count} cookies from an external secret reference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
