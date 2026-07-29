#!/usr/bin/env python3
"""Require changed COMPLETE feature contracts for protected repository diffs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Iterable, Mapping, Sequence


CONTRACT_FILE_RE = re.compile(
    r"^docs/dev-changes/(?P<change_id>[^/]+)/"
    r"(?P<filename>impact|completion)\.yaml$"
)
CHANGE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
ROOT_DOCUMENT_NAMES = {
    "changelog.md",
    "code_of_conduct.md",
    "contributing.md",
    "license",
    "license.md",
    "readme.md",
    "security.md",
}
INDEX_EVALUATION_REF = ":"
VALIDATION_MODES = {"legacy", "worktree", "index", "commit"}
RISK_LEVELS = ("R0", "R1", "R2", "R3")
GOVERNANCE_PREFIXES = (
    ".agents/",
    ".codex/",
    ".github/",
)


@lru_cache(maxsize=1)
def load_development_policy() -> ModuleType:
    """Load the one risk-policy implementation used by hooks and CI."""

    script_path = Path(__file__).resolve().with_name("development_policy.py")
    if not script_path.is_file():
        raise GateInputError(f"development policy does not exist: {script_path}")
    spec = importlib.util.spec_from_file_location("omni_development_policy", script_path)
    if spec is None or spec.loader is None:
        raise GateInputError(f"cannot load development policy: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GateInputError(ValueError):
    """The diff source or repository input cannot be evaluated deterministically."""


@dataclass(frozen=True)
class GateReport:
    changed_files: tuple[str, ...]
    protected_files: tuple[str, ...]
    changed_contract_ids: tuple[str, ...]
    valid_contract_ids: tuple[str, ...]
    errors: tuple[str, ...]
    validation_mode: str = "legacy"
    validated_contracts: tuple["ValidatedContract", ...] = ()

    @property
    def skipped(self) -> bool:
        return not self.protected_files and not self.changed_contract_ids


@dataclass(frozen=True)
class ValidatedContract:
    change_id: str
    schema_version: int
    risk_level: str | None
    base_commit: str | None
    actual_paths: tuple[str, ...]
    impact_sha256: str
    completion_sha256: str


@dataclass(frozen=True)
class EvaluationInputs:
    mode: str
    changed_files: tuple[str, ...]
    head_ref: str
    evaluation_ref: str | None
    base_ref: str | None


def normalize_changed_path(value: str) -> str:
    try:
        return str(load_development_policy().normalize_path(value))
    except ValueError as exc:
        raise GateInputError(str(exc)) from exc


def normalize_changed_files(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({normalize_changed_path(value) for value in values if value.strip()}))


def read_changed_files(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise GateInputError(f"changed-files list does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GateInputError(f"changed-files list must be UTF-8: {path}: {exc}") from exc
    return normalize_changed_files(text.splitlines())


def _validate_git_ref(value: str, label: str) -> str:
    if (
        not value
        or value.startswith("-")
        or "\x00" in value
        or any(char.isspace() for char in value)
    ):
        raise GateInputError(f"invalid {label} git revision: {value!r}")
    return value


def _validate_evaluation_ref(value: str, label: str) -> str:
    if value == INDEX_EVALUATION_REF:
        return value
    return _validate_git_ref(value, label)


def _evaluation_source_label(ref: str | None) -> str:
    if ref is None:
        return "checkout"
    if ref == INDEX_EVALUATION_REF:
        return "evaluation index"
    return f"evaluation head {ref}"


def git_changed_files(root: Path, base: str, head: str) -> tuple[str, ...]:
    base = _validate_git_ref(base, "base")
    head = _validate_git_ref(head, "head")
    command = [
        "git",
        "-C",
        str(root),
        "-c",
        "core.quotepath=false",
        "diff",
        "--name-only",
        "--diff-filter=ACMRTD",
        "-z",
        f"{base}...{head}",
        "--",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError as exc:
        raise GateInputError(f"cannot execute git diff: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateInputError(f"git diff failed ({result.returncode}): {detail}")
    try:
        names = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise GateInputError("git diff returned a non-UTF-8 repository path") from exc
    return normalize_changed_files(names)


def _git_name_list(root: Path, command: list[str], label: str) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=false", *command],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise GateInputError(f"cannot execute {label}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateInputError(f"{label} failed ({result.returncode}): {detail}")
    try:
        names = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise GateInputError(f"{label} returned a non-UTF-8 repository path") from exc
    return normalize_changed_files(names)


def git_index_changed_files(root: Path) -> tuple[str, ...]:
    """Read the complete staged candidate directly from Git's index."""

    return _git_name_list(
        root,
        ["diff", "--cached", "--name-only", "--diff-filter=ACMRTD", "-z", "HEAD", "--"],
        "git index diff",
    )


def git_worktree_changed_files(root: Path) -> tuple[str, ...]:
    """Read tracked and untracked worktree changes without trusting a caller list."""

    tracked = _git_name_list(
        root,
        ["diff", "--name-only", "--diff-filter=ACMRTD", "-z", "HEAD", "--"],
        "git worktree diff",
    )
    untracked = _git_name_list(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--"],
        "git untracked-file scan",
    )
    return normalize_changed_files((*tracked, *untracked))


def git_resolve_commit(root: Path, ref: str) -> str:
    ref = _validate_git_ref(ref, "commit")
    command = ["git", "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip()
        raise GateInputError(f"cannot resolve Git commit {ref!r}: {detail}")
    commit = result.stdout.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise GateInputError(f"Git returned an invalid commit id for {ref!r}: {commit!r}")
    return commit


def git_commit_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
    )
    if result.returncode not in {0, 1}:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateInputError(f"cannot evaluate Git ancestry: {detail}")
    return result.returncode == 0


def git_tree_hash(root: Path, commit: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{commit}^{{tree}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GateInputError(f"cannot resolve tree for delivered commit {commit}")
    return result.stdout.strip().lower()


def git_tracked_files(root: Path, ref: str) -> frozenset[str]:
    """Return file paths from an evaluation tree or index, or no paths on failure.

    Historical contract artifacts are allowed to refer to an implementation that
    has already landed, but only when Git can prove that the exact path is part
    of the immutable evaluation tree.  A missing repository or unavailable ref
    therefore deliberately receives no exception and retains the strict diff
    check.
    """

    ref = _validate_evaluation_ref(ref, "evaluation head")
    if ref == INDEX_EVALUATION_REF:
        command = [
            "git",
            "-C",
            str(root),
            "-c",
            "core.quotepath=false",
            "ls-files",
            "--cached",
            "-z",
            "--",
        ]
    else:
        command = [
            "git",
            "-C",
            str(root),
            "-c",
            "core.quotepath=false",
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            "--full-tree",
            ref,
            "--",
        ]
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError:
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    try:
        names = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    except UnicodeDecodeError:
        return frozenset()
    return frozenset(normalize_changed_files(names))


def git_file_text(root: Path, ref: str, relative_path: str) -> str | None:
    """Read one UTF-8 file from a Git tree or the index; return None when absent."""

    ref = _validate_evaluation_ref(ref, "evaluation source")
    relative_path = normalize_changed_path(relative_path)
    object_name = (
        f":{relative_path}"
        if ref == INDEX_EVALUATION_REF
        else f"{ref}:{relative_path}"
    )
    command = ["git", "-C", str(root), "show", object_name]
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError as exc:
        raise GateInputError(f"cannot execute git show: {exc}") from exc
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateInputError(
            f"contract file is not UTF-8 in {_evaluation_source_label(ref)}: {relative_path}"
        ) from exc


def is_documentation_path(path: str) -> bool:
    parts = path.split("/")
    if parts[0].casefold() == "docs":
        return True
    if len(parts) != 1:
        return False
    name = parts[0].casefold()
    return name in ROOT_DOCUMENT_NAMES or name.startswith("readme.")


def is_test_path(path: str) -> bool:
    parts = [part.casefold() for part in path.split("/")]
    if "tests" in parts or "__tests__" in parts:
        return True
    name = parts[-1]
    return (
        name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or bool(re.search(r"_test\.[^.]+$", name))
    )


def requires_feature_contract(path: str) -> bool:
    return not is_documentation_path(path) and not is_test_path(path)


def load_contract_validator(root: Path) -> ModuleType:
    script_path = (
        root
        / ".agents"
        / "skills"
        / "omni-feature-development"
        / "scripts"
        / "dev_contract.py"
    )
    if not script_path.is_file():
        raise GateInputError(f"feature-contract validator does not exist: {script_path}")
    spec = importlib.util.spec_from_file_location("omni_feature_contract_validator", script_path)
    if spec is None or spec.loader is None:
        raise GateInputError(f"cannot load feature-contract validator: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_pattern(value: object) -> str:
    pattern = str(value).strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    return pattern


def _impact_patterns(impact: dict) -> set[str]:
    patterns: set[str] = set()
    for item in impact.get("planned_changes") or []:
        if not isinstance(item, dict):
            continue
        for path in item.get("paths") or []:
            pattern = _normalize_pattern(path)
            if pattern:
                patterns.add(pattern)
    for path in impact.get("allowed_unplanned_paths") or []:
        pattern = _normalize_pattern(path)
        if pattern:
            patterns.add(pattern)
    return patterns


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_boundary(path: str) -> str:
    return str(load_development_policy().path_boundary(path))


def derive_risk_floor(paths: Iterable[str], impact: dict | None = None) -> str:
    """Derive the minimum risk through the shared development policy."""

    return str(load_development_policy().derive_risk_floor(paths, impact))


def evaluate_debt_ratchet(
    baseline: Iterable[object],
    current: Iterable[object],
    *,
    changed_paths: Iterable[str] = (),
) -> object:
    """Compatibility entry point for CI callers using the feature gate module."""

    return load_development_policy().evaluate_debt_ratchet(
        baseline,
        current,
        changed_paths=changed_paths,
    )


def _risk_at_least(declared: str, required: str) -> bool:
    if declared not in RISK_LEVELS or required not in RISK_LEVELS:
        return False
    return RISK_LEVELS.index(declared) >= RISK_LEVELS.index(required)


def _changed_contract_files(changed_files: Iterable[str]) -> dict[str, set[str]]:
    contracts: dict[str, set[str]] = {}
    for path in changed_files:
        match = CONTRACT_FILE_RE.fullmatch(path)
        if match is None:
            continue
        contracts.setdefault(match.group("change_id"), set()).add(
            f"{match.group('filename')}.yaml"
        )
    return contracts


def check_feature_contracts(
    root: Path,
    changed_files: Iterable[str],
    *,
    validator: ModuleType | None = None,
    head_ref: str = "HEAD",
    evaluation_ref: str | None = None,
    validation_mode: str = "legacy",
    base_ref: str | None = None,
) -> GateReport:
    root = root.resolve()
    if validation_mode not in VALIDATION_MODES:
        raise GateInputError(f"unsupported validation mode: {validation_mode!r}")
    head_ref = _validate_evaluation_ref(head_ref, "evaluation head")
    if evaluation_ref is not None:
        evaluation_ref = _validate_evaluation_ref(evaluation_ref, "evaluation source")
    if base_ref is not None:
        base_ref = _validate_git_ref(base_ref, "base")
    archival_ref = evaluation_ref if evaluation_ref is not None else head_ref
    changed = normalize_changed_files(changed_files)
    protected = tuple(path for path in changed if requires_feature_contract(path))
    contract_files = _changed_contract_files(changed)
    changed_contract_ids = tuple(sorted(contract_files))
    if not protected and not contract_files:
        return GateReport(
            changed,
            protected,
            changed_contract_ids,
            (),
            (),
            validation_mode=validation_mode,
        )

    errors: list[str] = []
    if not contract_files:
        errors.append(
            "protected changes require impact.yaml and completion.yaml from at least one "
            "docs/dev-changes/<change-id>/ directory in this diff"
        )

    contract_validator = validator or load_contract_validator(root)
    coverage_by_contract: dict[str, set[str]] = {}
    actual_by_contract: dict[str, set[str]] = {}
    valid_contract_ids: list[str] = []
    validated_contracts: list[ValidatedContract] = []
    required_pair = {"impact.yaml", "completion.yaml"}

    for change_id in changed_contract_ids:
        present = contract_files[change_id]
        if CHANGE_ID_RE.fullmatch(change_id) is None:
            errors.append(
                f"[{change_id}] contract directory must use 3-64 lowercase letters, "
                "digits, or hyphens"
            )
        missing_from_diff = sorted(required_pair - present)
        if missing_from_diff:
            errors.append(
                f"[{change_id}] contract pair is incomplete in this diff; missing: "
                f"{', '.join(missing_from_diff)}"
            )
            continue

        impact_relative = f"docs/dev-changes/{change_id}/impact.yaml"
        completion_relative = f"docs/dev-changes/{change_id}/completion.yaml"
        if evaluation_ref is None:
            impact_path = root / impact_relative
            completion_path = root / completion_relative
            missing_on_disk = [
                path.relative_to(root).as_posix()
                for path in (impact_path, completion_path)
                if not path.is_file()
            ]
            if missing_on_disk:
                errors.append(
                    f"[{change_id}] changed contract file is missing from the checkout: "
                    f"{', '.join(missing_on_disk)}"
                )
                continue
            try:
                impact_text = impact_path.read_text(encoding="utf-8")
                completion_text = completion_path.read_text(encoding="utf-8")
                impact = contract_validator.read_yaml_text(impact_text, str(impact_path))
                completion = contract_validator.read_yaml_text(
                    completion_text, str(completion_path)
                )
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"[{change_id}] {exc}")
                continue
        else:
            impact_text = git_file_text(root, evaluation_ref, impact_relative)
            completion_text = git_file_text(root, evaluation_ref, completion_relative)
            missing_from_source = [
                path
                for path, text in (
                    (impact_relative, impact_text),
                    (completion_relative, completion_text),
                )
                if text is None
            ]
            if missing_from_source:
                errors.append(
                    f"[{change_id}] changed contract file is missing from "
                    f"{_evaluation_source_label(evaluation_ref)}: "
                    f"{', '.join(missing_from_source)}"
                )
                continue
            try:
                impact = contract_validator.read_yaml_text(
                    impact_text,
                    f"{_evaluation_source_label(evaluation_ref)}:{impact_relative}",
                )
                completion = contract_validator.read_yaml_text(
                    completion_text,
                    f"{_evaluation_source_label(evaluation_ref)}:{completion_relative}",
                )
            except ValueError as exc:
                errors.append(f"[{change_id}] {exc}")
                continue

        if impact.get("change_id") != change_id:
            errors.append(
                f"[{change_id}] impact.change_id must match its directory name, "
                f"found {impact.get('change_id')!r}"
            )
            continue

        schema_version = impact.get("schema_version")
        expected_state = "GRAPH_DIFF_READY" if schema_version == 3 else "COMPLETE"
        strict_errors = contract_validator.run_validation(
            impact,
            completion,
            expect_state=expected_state,
            strict=True,
            changed_files_file=None,
        )
        local_errors = list(strict_errors)
        actual_paths: set[str] = set()
        path_actions: dict[str, str] = {}
        planned_by_id = {
            item.get("id"): item
            for item in impact.get("planned_changes") or []
            if isinstance(item, dict)
        }
        for actual_change in completion.get("actual_changes") or []:
            if not isinstance(actual_change, dict):
                continue
            planned = planned_by_id.get(actual_change.get("planned_change_id")) or {}
            action = str(planned.get("action", "modify"))
            for actual_path in actual_change.get("paths") or []:
                try:
                    normalized_actual = normalize_changed_path(str(actual_path))
                except GateInputError as exc:
                    local_errors.append(
                        f"invalid completion.actual_changes path {actual_path!r}: {exc}"
                    )
                    continue
                actual_paths.add(normalized_actual)
                path_actions[normalized_actual] = action

        base_commit: str | None = None
        delivery_changed: set[str] | None = None
        if schema_version == 3 and validation_mode == "commit":
            risk = impact.get("risk") or {}
            if risk.get("level") == "R3":
                local_errors.append(
                    "R3 candidates cannot receive a delivery attestation until an "
                    "external gate verifier validates impact.risk.approval.gate_ref"
                )
            delivery = impact.get("delivery") or {}
            declared_base = str(delivery.get("base_commit", "")).strip().lower()
            try:
                base_commit = git_resolve_commit(root, declared_base)
                delivered_commit = git_resolve_commit(root, head_ref)
                if base_commit != declared_base:
                    local_errors.append(
                        "impact.delivery.base_commit must be the immutable full commit SHA"
                    )
                elif not git_commit_is_ancestor(root, base_commit, delivered_commit):
                    local_errors.append(
                        "impact.delivery.base_commit is not an ancestor of the delivered commit"
                    )
                else:
                    delivery_changed = set(git_changed_files(root, base_commit, delivered_commit))
            except GateInputError as exc:
                local_errors.append(str(exc))

        if schema_version == 3:
            if delivery_changed is not None:
                source_paths = delivery_changed
            else:
                source_paths = set(changed)
            tracked_at_source = (
                git_tracked_files(root, archival_ref)
                if evaluation_ref is not None
                else frozenset(
                    path
                    for path in actual_paths
                    if (root / path).is_file()
                )
            )
            for path in sorted(actual_paths):
                if path in source_paths:
                    continue
                if path_actions.get(path) == "reuse" and path in tracked_at_source:
                    continue
                local_errors.append(
                    "completion.actual_changes path is not changed between the declared "
                    f"delivery baseline and candidate: {path}"
                )

        if local_errors:
            errors.extend(f"[{change_id}] {error}" for error in local_errors)
            continue

        valid_contract_ids.append(change_id)
        coverage_by_contract[change_id] = _impact_patterns(impact)
        actual_by_contract[change_id] = actual_paths
        risk = impact.get("risk") or {}
        validated_contracts.append(
            ValidatedContract(
                change_id=change_id,
                schema_version=int(schema_version),
                risk_level=str(risk.get("level")) if schema_version == 3 else None,
                base_commit=base_commit
                or (
                    str((impact.get("delivery") or {}).get("base_commit", "")).lower()
                    if schema_version == 3
                    else None
                ),
                actual_paths=tuple(sorted(actual_paths)),
                impact_sha256=_sha256_text(impact_text),
                completion_sha256=_sha256_text(completion_text),
            )
        )

    records_by_id = {record.change_id: record for record in validated_contracts}
    owners_by_path: dict[str, tuple[str, ...]] = {}
    for path in protected:
        matching = tuple(
            sorted(
                change_id
                for change_id, patterns in coverage_by_contract.items()
                if any(contract_validator.path_matches(path, pattern) for pattern in patterns)
            )
        )
        v3_owners = tuple(
            owner
            for owner in matching
            if records_by_id[owner].schema_version == 3
        )
        # Historical v1/v2 contracts used union coverage. Preserve that behavior,
        # while every new v3 path must have one unambiguous v3 owner.
        owners = v3_owners if v3_owners else matching
        owners_by_path[path] = owners
        if not owners:
            errors.append(f"protected changed file is outside changed contract scope: {path}")
            errors.append(
                f"protected changed file is missing from completion.actual_changes: {path}"
            )
        elif len(v3_owners) > 1:
            errors.append(
                "protected changed file must have exactly one contract owner: "
                f"{path} (owners: {', '.join(v3_owners)})"
            )
        elif not any(path in actual_by_contract.get(owner, set()) for owner in owners):
            errors.append(
                f"protected changed file is missing from completion.actual_changes: {path}"
            )

    for change_id in valid_contract_ids:
        record = records_by_id[change_id]
        owned_paths = [
            path for path, owners in owners_by_path.items() if owners == (change_id,)
        ]
        if record.schema_version == 3:
            impact_relative = f"docs/dev-changes/{change_id}/impact.yaml"
            if evaluation_ref is None:
                impact = contract_validator.read_yaml(root / impact_relative)
            else:
                impact = contract_validator.read_yaml_text(
                    git_file_text(root, evaluation_ref, impact_relative) or "",
                    f"{_evaluation_source_label(evaluation_ref)}:{impact_relative}",
                )
            required_risk = derive_risk_floor(owned_paths, impact)
            declared_risk = record.risk_level or ""
            if not _risk_at_least(declared_risk, required_risk):
                errors.append(
                    f"[{change_id}] declared risk {declared_risk or '<missing>'} is below "
                    f"derived minimum {required_risk}"
                )
            continue

        head_tracked = git_tracked_files(root, archival_ref)
        not_delivered = sorted(set(record.actual_paths) - set(changed) - head_tracked)
        errors.extend(
            "completion.actual_changes path is neither in the current diff nor tracked "
            f"at {_evaluation_source_label(archival_ref)}: {path}"
            for path in not_delivered
        )

    return GateReport(
        changed_files=changed,
        protected_files=protected,
        changed_contract_ids=changed_contract_ids,
        valid_contract_ids=tuple(valid_contract_ids),
        errors=tuple(errors),
        validation_mode=validation_mode,
        validated_contracts=tuple(validated_contracts),
    )


def build_delivery_attestation(
    root: Path,
    report: GateReport,
    delivered_ref: str,
    *,
    attestor: str = "ci",
    run_id: str = "",
    target_ref: str = "refs/heads/main",
    repository: str = "",
    required_checks: Mapping[str, str] | None = None,
    evidence_artifact_name: str = "",
    evidence_artifact_digest: str = "",
    migration_gate_verified: bool = False,
) -> dict[str, object]:
    """Build an external seal for one immutable commit after commit-mode validation."""

    if report.validation_mode != "commit":
        raise GateInputError("delivery attestation is available only in commit mode")
    if report.errors:
        raise GateInputError("delivery attestation cannot be created for a failing report")
    v3_contracts = [
        contract for contract in report.validated_contracts if contract.schema_version == 3
    ]
    if not v3_contracts:
        raise GateInputError("delivery attestation requires at least one validated schema v3 contract")
    r3_contracts = [
        contract.change_id for contract in v3_contracts if contract.risk_level == "R3"
    ]
    if r3_contracts:
        raise GateInputError(
            "R3 delivery attestation is fail-closed until an external gate verifier is "
            f"available: {', '.join(r3_contracts)}"
        )
    database_paths = sorted(
        {
            path
            for contract in v3_contracts
            for path in contract.actual_paths
            if _path_boundary(path) == "database"
        }
        | {
            path
            for path in report.protected_files
            if _path_boundary(path) == "database"
        }
    )
    if database_paths and not migration_gate_verified:
        raise GateInputError(
            "database/migration delivery attestation requires the S1.5 blocking "
            "migration gate (parity): "
            + ", ".join(database_paths)
        )

    delivered_commit = git_resolve_commit(root, delivered_ref)
    contracts: list[dict[str, object]] = []
    for contract in v3_contracts:
        if not contract.base_commit:
            raise GateInputError(f"[{contract.change_id}] delivery base commit is missing")
        changed_paths = git_changed_files(root, contract.base_commit, delivered_commit)
        changed_digest = _sha256_text("\n".join(changed_paths) + ("\n" if changed_paths else ""))
        contracts.append(
            {
                "change_id": contract.change_id,
                "base_commit": contract.base_commit,
                "risk_level": contract.risk_level,
                "actual_paths": list(contract.actual_paths),
                "changed_paths_sha256": changed_digest,
                "impact_sha256": contract.impact_sha256,
                "completion_sha256": contract.completion_sha256,
            }
        )

    if target_ref != "refs/heads/main":
        raise GateInputError("delivery attestation target_ref must be refs/heads/main")
    repository = repository.strip() or git_repository_identity(root)
    if not repository:
        raise GateInputError("delivery attestation requires repository identity")
    if not run_id or not str(run_id).isdigit():
        raise GateInputError("delivery attestation requires a numeric CI workflow run id")
    checks = dict(required_checks or {})
    if not checks or not all(str(value).casefold() in {"passed", "success"} for value in checks.values()):
        raise GateInputError("delivery attestation requires explicit passed required checks")
    if not evidence_artifact_name or not evidence_artifact_digest.startswith("sha256:"):
        raise GateInputError("delivery attestation requires a content-addressed evidence artifact")
    return {
        "schema_version": 2,
        "authority": "ci_attestation",
        "status": "COMPLETE",
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "attestor": attestor,
        "workflow_run_id": str(run_id),
        "repository": repository,
        "target_ref": target_ref,
        "head_sha": delivered_commit,
        "reachable": True,
        "required_checks": checks,
        "attestation_artifact_name": f"delivery-attestation-{delivered_commit}",
        "evidence_artifact": {
            "name": evidence_artifact_name,
            "digest": evidence_artifact_digest,
        },
        "subject_commit": delivered_commit,
        "delivered_commit": delivered_commit,
        "delivered_tree": git_tree_hash(root, delivered_commit),
        "contracts": contracts,
    }


def write_delivery_attestation(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise GateInputError(f"refusing to overwrite immutable delivery attestation: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


def git_repository_identity(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    value = result.stdout.strip().removesuffix(".git")
    match = re.search(r"(?:github\.com[:/])([^/]+)/([^/]+)$", value, re.IGNORECASE)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def _parse_required_checks(values: Iterable[str]) -> dict[str, str]:
    checks: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise GateInputError(f"required check must use name=status: {value!r}")
        name, status = value.split("=", 1)
        if not name or status.casefold() not in {"passed", "success"}:
            raise GateInputError(f"required check is not passed: {value!r}")
        checks[name] = status.casefold()
    return checks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument("--base", help="base git revision for a merge-base diff")
    parser.add_argument("--head", help="head git revision for a merge-base diff")
    parser.add_argument(
        "--mode",
        choices=("worktree", "index", "commit"),
        help="derive the candidate from Git worktree, index, or immutable commits",
    )
    parser.add_argument(
        "--changed-files-file",
        type=Path,
        help="UTF-8 file containing one repository-relative changed path per line",
    )
    parser.add_argument(
        "--attestation-out",
        type=Path,
        help="write an external delivery attestation (commit mode only)",
    )
    parser.add_argument("--attestor", default="ci", help="attestation issuer label")
    parser.add_argument("--target-ref", default=os.environ.get("GITHUB_REF", "refs/heads/main"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--evidence-artifact-name", default="")
    parser.add_argument("--evidence-artifact-digest", default="")
    parser.add_argument("--migration-gate-verified", action="store_true")
    parser.add_argument(
        "--ci-run-id",
        default=os.environ.get("GITHUB_RUN_ID", ""),
        help="CI workflow run identifier recorded in an external attestation",
    )
    return parser


def _resolve_evaluation_inputs(args: argparse.Namespace) -> EvaluationInputs:
    using_file = args.changed_files_file is not None
    using_refs = args.base is not None or args.head is not None
    if using_file and (using_refs or args.mode is not None):
        raise GateInputError("use either --changed-files-file or --base/--head, not both")
    if using_file:
        path = args.changed_files_file
        if not path.is_absolute():
            path = args.root / path
        return EvaluationInputs(
            mode="legacy",
            changed_files=read_changed_files(path),
            head_ref=INDEX_EVALUATION_REF,
            evaluation_ref=INDEX_EVALUATION_REF,
            base_ref=None,
        )

    mode = args.mode or ("commit" if using_refs else None)
    if mode is None:
        raise GateInputError(
            "provide --mode worktree/index/commit, --changed-files-file, or both --base and --head"
        )
    if mode == "worktree":
        if using_refs:
            raise GateInputError("worktree mode derives from HEAD and does not accept --base/--head")
        return EvaluationInputs(
            mode=mode,
            changed_files=git_worktree_changed_files(args.root),
            head_ref="HEAD",
            evaluation_ref=None,
            base_ref="HEAD",
        )
    if mode == "index":
        if using_refs:
            raise GateInputError("index mode derives from HEAD and does not accept --base/--head")
        return EvaluationInputs(
            mode=mode,
            changed_files=git_index_changed_files(args.root),
            head_ref=INDEX_EVALUATION_REF,
            evaluation_ref=INDEX_EVALUATION_REF,
            base_ref="HEAD",
        )
    if args.base is None or args.head is None:
        raise GateInputError("commit mode requires both --base and --head")
    return EvaluationInputs(
        mode=mode,
        changed_files=git_changed_files(args.root, args.base, args.head),
        head_ref=args.head,
        evaluation_ref=args.head,
        base_ref=args.base,
    )


def _resolve_changed_files(args: argparse.Namespace) -> tuple[str, ...]:
    """Backward-compatible helper retained for callers and older tests."""

    return _resolve_evaluation_inputs(args).changed_files


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.root = args.root.resolve()
    try:
        inputs = _resolve_evaluation_inputs(args)
        if args.attestation_out is not None and inputs.mode != "commit":
            raise GateInputError("--attestation-out is allowed only in commit mode")
        report = check_feature_contracts(
            args.root,
            inputs.changed_files,
            head_ref=inputs.head_ref,
            evaluation_ref=inputs.evaluation_ref,
            validation_mode=inputs.mode,
            base_ref=inputs.base_ref,
        )
    except GateInputError as exc:
        print(f"[feature-contracts] ERROR: {exc}", file=sys.stderr)
        return 2

    if report.errors:
        print(f"[feature-contracts] FAIL: {len(report.errors)} violation(s)", file=sys.stderr)
        for error in report.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if report.skipped:
        print(
            f"[feature-contracts] SKIP: {len(report.changed_files)} changed file(s) "
            "are documentation/tests only"
        )
        return 0

    if args.attestation_out is not None:
        try:
            payload = build_delivery_attestation(
                args.root,
                report,
                inputs.head_ref,
                attestor=args.attestor,
                run_id=args.ci_run_id,
                target_ref=args.target_ref,
                repository=args.repository,
                required_checks=_parse_required_checks(args.required_check),
                evidence_artifact_name=args.evidence_artifact_name,
                evidence_artifact_digest=args.evidence_artifact_digest,
                migration_gate_verified=args.migration_gate_verified,
            )
            output_path = args.attestation_out
            if not output_path.is_absolute():
                output_path = args.root / output_path
            write_delivery_attestation(output_path, payload)
        except GateInputError as exc:
            print(f"[feature-contracts] ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"[feature-contracts] ATTESTED: {output_path}")

    v3_count = sum(
        contract.schema_version == 3 for contract in report.validated_contracts
    )
    historical_count = len(report.validated_contracts) - v3_count
    contract_summary = []
    if v3_count:
        contract_summary.append(f"{v3_count} delivery-ready v3 candidate(s)")
    if historical_count:
        contract_summary.append(f"{historical_count} historical COMPLETE contract(s)")
    print(
        f"[feature-contracts] OK: {len(report.protected_files)} protected file(s) "
        f"covered by {', '.join(contract_summary) or 'validated contracts'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
