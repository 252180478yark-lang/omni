from __future__ import annotations


def normalize_optional_text(value: object) -> str:
    """Return a trimmed string while treating null or non-string config as unset."""

    if not isinstance(value, str):
        return ""
    return value.strip()
