#!/usr/bin/env python3
"""Create Playwright auth state from an external cookie secret file.

The secret itself must never live in the repository or on the command line.
Pass an absolute, repository-external file path with ``--secret-file`` or the
``OMNI_COOKIE_SECRET_FILE`` environment variable.  The helper logs only the
number of imported cookies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


COOKIE_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}$")


def default_output() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir())
        return base / "Omni" / "secrets" / "harvester_auth.json"
    return Path("/app/data/harvester_auth.json")


class SecretReferenceError(ValueError):
    """A secret reference is unsafe or malformed."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def external_file(value: str | os.PathLike[str], *, purpose: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise SecretReferenceError(f"{purpose} path must be absolute")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(repository_root())
    except ValueError:
        pass
    else:
        raise SecretReferenceError(f"{purpose} path must be outside the repository")
    return resolved


def _cookie(name: str, value: str, domain: str = ".oceanengine.com", path: str = "/") -> dict[str, Any]:
    if not COOKIE_NAME.fullmatch(name) or not value or any(char in value for char in "\r\n"):
        raise SecretReferenceError("cookie secret file contains an invalid cookie")
    if not domain.startswith(".") or any(char in domain for char in "\r\n/\\"):
        raise SecretReferenceError("cookie secret file contains an invalid domain")
    if not path.startswith("/") or any(char in path for char in "\r\n"):
        raise SecretReferenceError("cookie secret file contains an invalid path")
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "httpOnly": False,
        "secure": True,
        "sameSite": "None",
    }


def parse_cookie_secret(text: str) -> list[dict[str, Any]]:
    """Accept a Cookie header or JSON cookie list without returning raw text."""

    stripped = text.strip()
    if not stripped:
        raise SecretReferenceError("cookie secret file is empty")
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, Mapping):
        decoded = decoded.get("cookies")
    if isinstance(decoded, Sequence) and not isinstance(decoded, (str, bytes)):
        cookies: list[dict[str, Any]] = []
        for item in decoded:
            if not isinstance(item, Mapping):
                raise SecretReferenceError("cookie JSON must contain objects")
            cookies.append(
                _cookie(
                    str(item.get("name") or ""),
                    str(item.get("value") or ""),
                    str(item.get("domain") or ".oceanengine.com"),
                    str(item.get("path") or "/"),
                )
            )
        if not cookies:
            raise SecretReferenceError("cookie JSON contains no cookies")
        return cookies

    cookies = []
    for pair in stripped.split(";"):
        if not pair.strip():
            continue
        if "=" not in pair:
            raise SecretReferenceError("cookie header contains a malformed pair")
        name, value = pair.split("=", 1)
        cookies.append(_cookie(name.strip(), value.strip()))
    if not cookies:
        raise SecretReferenceError("cookie header contains no cookies")
    return cookies


def read_secret_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SecretReferenceError("cookie secret file does not exist")
    if path.stat().st_size > 1_000_000:
        raise SecretReferenceError("cookie secret file exceeds the size limit")
    return parse_cookie_secret(path.read_text(encoding="utf-8"))


def write_auth_state(path: Path, cookies: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".harvester-auth-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"cookies": list(cookies), "origins": []}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-file", default=os.getenv("OMNI_COOKIE_SECRET_FILE"))
    parser.add_argument(
        "--output",
        default=os.getenv("OMNI_HARVESTER_AUTH_STATE", str(default_output())),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.secret_file:
        raise SystemExit("cookie secret-file reference is required")
    try:
        source = external_file(args.secret_file, purpose="secret-file")
        output = external_file(args.output, purpose="output")
        cookies = read_secret_file(source)
        write_auth_state(output, cookies)
    except (OSError, UnicodeError, SecretReferenceError) as exc:
        raise SystemExit(f"cookie import refused: {exc}") from None
    print(f"Imported {len(cookies)} cookies from an external secret reference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
