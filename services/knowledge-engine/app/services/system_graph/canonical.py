"""Canonical IDs, serialization, repository coordinates and hashes."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.schemas.system_graph import EvidenceRef


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_route(value: str) -> str:
    route = value.strip().replace("\\", "/").split("?", 1)[0].split("#", 1)[0]
    route = re.sub(r"\$\{[^}]+\}", "{dynamic}", route)
    route = re.sub(r"//+", "/", route)
    if not route.startswith("/"):
        route = "/" + route
    return route.rstrip("/") or "/"


def make_node_id(kind: str, key: str) -> str:
    normalized = key.strip().replace("\\", "/")
    if kind in {"ui_route", "bff_operation", "rest_operation"}:
        if ":" in normalized and normalized.split(":", 1)[0].upper() in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
            "HEAD",
        }:
            method, route = normalized.split(":", 1)
            normalized = f"{method.upper()}:{normalize_route(route)}"
        else:
            normalized = normalize_route(normalized)
    return f"{kind}:{normalized}"


def make_edge_id(relation: str, source: str, target: str) -> str:
    digest = hashlib.sha256(f"{relation}\0{source}\0{target}".encode("utf-8")).hexdigest()
    return f"edge:{relation}:{digest[:24]}"


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=10,
    )
    return result.stdout.strip()


def resolve_commit(repo: Path, ref: str = "HEAD") -> str:
    return git_output(repo, "rev-parse", f"{ref}^{{commit}}")


def repo_relative(repo: Path, path: Path) -> str:
    resolved_repo = repo.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_repo)
    except ValueError as exc:
        raise ValueError(f"evidence path escapes repository: {path}") from exc
    return relative.as_posix()


def blob_id(repo: Path, path: Path) -> str:
    return git_output(repo, "hash-object", "--no-filters", str(path.resolve()))


def evidence_ref(repo: Path, path: Path, line: int, symbol: str = "") -> EvidenceRef:
    return EvidenceRef(
        path=repo_relative(repo, path),
        line=max(1, line),
        symbol=symbol,
        blob=blob_id(repo, path),
    )
