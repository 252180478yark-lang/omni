"""Fail-closed redaction for graph attributes and collector diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "<redacted>"
_SECRET_KEY = re.compile(
    r"(?:authorization|cookie|passphrase|password|secret|token|api[_-]?key|dsn|credential)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}")
_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|passphrase|password|secret|token|api[_-]?key|dsn)\s*[:=]\s*[^\s,;]+"
)
_URL_CREDENTIAL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:token|secret|password|passphrase|api[_-]?key|authorization)=)[^&#\s]+"
)


def redact_text(value: str) -> str:
    value = _BEARER.sub(REDACTED, value)
    value = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    value = _URL_CREDENTIAL.sub(lambda match: f"{match.group(1)}{REDACTED}@", value)
    value = _QUERY_SECRET.sub(lambda match: f"{match.group(1)}{REDACTED}", value)
    return value


def redact(value: Any, *, key: str = "") -> Any:
    if key and _SECRET_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(item_key): redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))
