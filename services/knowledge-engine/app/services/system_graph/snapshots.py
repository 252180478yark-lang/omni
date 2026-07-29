"""Immutable file snapshot storage and evidence verification."""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.system_graph import GraphSnapshot
from app.services.system_graph.canonical import blob_id, canonical_json, sha256_value


def snapshot_filename(snapshot: GraphSnapshot) -> str:
    return snapshot.content_hash.replace(":", "-") + ".json"


def snapshot_text(snapshot: GraphSnapshot) -> str:
    return json.dumps(
        snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def read_snapshot(path: Path) -> GraphSnapshot:
    snapshot = GraphSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    actual = sha256_value(snapshot.content.model_dump(mode="json"))
    if actual != snapshot.content_hash:
        raise ValueError(f"snapshot content hash mismatch: {path}")
    return snapshot


def write_snapshot(snapshot: GraphSnapshot, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / snapshot_filename(snapshot)
    if path.exists():
        existing = read_snapshot(path)
        if canonical_json(existing.content.model_dump(mode="json")) != canonical_json(
            snapshot.content.model_dump(mode="json")
        ):
            raise ValueError(f"immutable snapshot collision: {path}")
        return path
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(snapshot_text(snapshot))
    except FileExistsError:
        return write_snapshot(snapshot, directory)
    return path


def verify_evidence(snapshot: GraphSnapshot, repo: Path) -> list[str]:
    errors: list[str] = []
    coordinates = []
    for node in snapshot.content.nodes:
        coordinates.extend(node.evidence)
    for edge in snapshot.content.edges:
        coordinates.extend(edge.evidence)
    for diagnostic in snapshot.content.diagnostics:
        coordinates.extend(diagnostic.evidence)
    seen: set[tuple[str, int, str, str]] = set()
    for evidence in coordinates:
        key = (evidence.path, evidence.line, evidence.symbol, evidence.blob)
        if key in seen:
            continue
        seen.add(key)
        path = (repo / evidence.path).resolve()
        try:
            path.relative_to(repo.resolve())
        except ValueError:
            errors.append(f"evidence escapes repository: {evidence.path}")
            continue
        if not path.is_file():
            errors.append(f"evidence file missing: {evidence.path}")
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            errors.append(f"evidence is not readable UTF-8: {evidence.path}")
            continue
        if evidence.line > max(1, len(lines)):
            errors.append(f"evidence line out of range: {evidence.path}:{evidence.line}")
        if blob_id(repo, path) != evidence.blob:
            errors.append(f"evidence blob mismatch: {evidence.path}")
    return sorted(errors)
