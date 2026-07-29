#!/usr/bin/env python3
"""Deterministic R0-R3 development policy for Omni changes.

The module intentionally has no repository write side effects.  Hooks, the
feature-contract gate and tests all consume the same classifier so a local
workflow cannot silently use a weaker risk interpretation than CI.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


RISK_LEVELS = ("R0", "R1", "R2", "R3")
RISK_INDEX = {level: index for index, level in enumerate(RISK_LEVELS)}
CONTRACT_PROFILES = {
    "R0": "none",
    "R1": "light",
    "R2": "full",
    "R3": "full_with_approval",
}

ROOT_DOCUMENT_NAMES = {
    "changelog.md",
    "code_of_conduct.md",
    "contributing.md",
    "license",
    "license.md",
    "readme.md",
    "security.md",
}
GOVERNANCE_PREFIXES = (".agents/", ".codex/", ".github/")
R3_EFFECT_KINDS = {
    "external_publish",
    "external_message",
    "paid_generation",
    "credential_access",
    "shared_database_migration",
    "production_database_migration",
    "hard_delete_user_data",
    "physical_client_retirement",
}
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class PolicyInputError(ValueError):
    """A policy input cannot be interpreted without guessing."""


@dataclass(frozen=True)
class RiskDecision:
    level: str
    contract_profile: str
    approval_required: bool
    reasons: tuple[str, ...]
    boundaries: tuple[str, ...]
    validation_scope: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["boundaries"] = list(self.boundaries)
        payload["validation_scope"] = list(self.validation_scope)
        return payload


@dataclass(frozen=True)
class ScopeDeltaDecision:
    action: str
    current_level: str
    required_level: str
    added_paths: tuple[str, ...]
    reason: str

    @property
    def blocked(self) -> bool:
        return self.action == "block_risk_escalation"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["added_paths"] = list(self.added_paths)
        payload["blocked"] = self.blocked
        return payload


@dataclass(frozen=True)
class DebtRatchet:
    passed: bool
    new_violations: tuple[str, ...]
    resolved_violations: tuple[str, ...]
    historical_violations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "new_violations": list(self.new_violations),
            "resolved_violations": list(self.resolved_violations),
            "historical_violations": list(self.historical_violations),
        }


def normalize_path(value: str) -> str:
    raw = str(value)
    if raw != raw.strip():
        raise PolicyInputError(f"path has leading or trailing whitespace: {value!r}")
    path = raw.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise PolicyInputError(f"path must be repository-relative: {value!r}")
    if path.endswith("/") or "//" in path or any(part == "." for part in path.split("/")):
        raise PolicyInputError(f"path contains an ambiguous separator or segment: {value!r}")
    parts = path.split("/")
    if not parts or any(part == ".." for part in parts) or "\x00" in path:
        raise PolicyInputError(f"path escapes the repository: {value!r}")
    for part in parts:
        if part.endswith((".", " ")) or ":" in part:
            raise PolicyInputError(f"path is not portable to Windows: {value!r}")
        base = part.split(".", 1)[0].casefold()
        if base in WINDOWS_RESERVED_NAMES:
            raise PolicyInputError(f"path uses a Windows reserved name: {value!r}")
    return "/".join(parts)


def path_collision_key(value: str) -> str:
    """Return the case-insensitive Windows collision identity."""

    return normalize_path(value).casefold()


@lru_cache(maxsize=4096)
def glob_pattern_to_regex(pattern: str) -> str:
    pattern = normalize_path(pattern)
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    pieces.append("(?:.*/)?")
                    index += 1
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1
    return "^" + "".join(pieces) + "$"


def path_matches(path: str, pattern: str) -> bool:
    return re.fullmatch(glob_pattern_to_regex(pattern), normalize_path(path)) is not None


def _glob_tokens(pattern: str) -> tuple[tuple[str, str | None], ...]:
    normalized = normalize_path(pattern)
    tokens: list[tuple[str, str | None]] = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char == "*":
            if index + 1 < len(normalized) and normalized[index + 1] == "*":
                tokens.append(("many_any", None))
                index += 2
                continue
            tokens.append(("many_segment", None))
        elif char == "?":
            tokens.append(("one_segment", None))
        else:
            tokens.append(("literal", char))
        index += 1
    return tuple(tokens)


def glob_patterns_overlap(left: str, right: str) -> bool:
    left_tokens, right_tokens = _glob_tokens(left), _glob_tokens(right)
    pending, visited = [(0, 0)], set()
    repeat = {"many_any", "many_segment"}
    while pending:
        li, ri = pending.pop()
        if (li, ri) in visited:
            continue
        visited.add((li, ri))
        if li == len(left_tokens) and ri == len(right_tokens):
            return True
        lt = left_tokens[li] if li < len(left_tokens) else None
        rt = right_tokens[ri] if ri < len(right_tokens) else None
        if lt is not None and lt[0] in repeat:
            pending.append((li + 1, ri))
        if rt is not None and rt[0] in repeat:
            pending.append((li, ri + 1))
        if lt is None or rt is None:
            continue
        lk, lv = lt
        rk, rv = rt
        shares = (
            lv == rv if lk == rk == "literal"
            else (lv != "/" or rk == "many_any") if lk == "literal"
            else (rv != "/" or lk == "many_any") if rk == "literal"
            else True
        )
        if not shares:
            continue
        next_state = (li if lk in repeat else li + 1, ri if rk in repeat else ri + 1)
        if next_state != (li, ri):
            pending.append(next_state)
    return False


def is_documentation_path(path: str) -> bool:
    normalized = normalize_path(path)
    parts = normalized.split("/")
    if parts[0].casefold() == "docs":
        return True
    if len(parts) != 1:
        return False
    name = parts[0].casefold()
    return name in ROOT_DOCUMENT_NAMES or name.startswith("readme.")


def is_test_path(path: str) -> bool:
    normalized = normalize_path(path)
    parts = [part.casefold() for part in normalized.split("/")]
    name = parts[-1]
    return (
        "tests" in parts
        or "__tests__" in parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or bool(re.search(r"_test\.[^.]+$", name))
    )


def path_boundary(path: str) -> str:
    normalized = normalize_path(path)
    folded = normalized.casefold()
    if is_documentation_path(normalized):
        return "documentation"
    if is_test_path(normalized):
        return "test"
    if folded == "agents.md" or folded.startswith(GOVERNANCE_PREFIXES):
        return "governance"
    if "migration" in folded or folded.endswith(".sql") or "/postgres/" in folded:
        return "database"
    name = folded.rsplit("/", 1)[-1]
    if (
        re.fullmatch(r"(?:docker-)?compose(?:\.[a-z0-9_-]+)?\.ya?ml", name)
        or name == "dockerfile"
        or folded == "dev-start.ps1"
        or folded.startswith("services/infra-core/")
        or folded == "config/runtime-manifest.yaml"
        or folded.startswith("config/schemas/runtime-")
        or folded in {"scripts/runtime_allocation.py", "scripts/runtime_guard.py"}
    ):
        return "infrastructure"
    if folded.startswith("frontend/src/app/api/") or "/routers/" in folded or "/api/" in folded:
        return "api"
    if "/mcp/" in folded:
        return "mcp"
    if folded.startswith("frontend/"):
        return "frontend"
    if folded.startswith("services/"):
        return "service"
    if folded.startswith("scripts/"):
        return "script"
    return "code"


def effect_kinds_from_impact(impact: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(impact, Mapping):
        return ()
    risk = impact.get("risk")
    if not isinstance(risk, Mapping):
        return ()
    kinds: list[str] = []
    for item in risk.get("external_effects") or []:
        if isinstance(item, Mapping) and item.get("kind"):
            kinds.append(str(item["kind"]))
    return tuple(kinds)


def _breaking_contract(impact: Mapping[str, Any] | None) -> bool:
    if not isinstance(impact, Mapping):
        return False
    compatibility = impact.get("compatibility")
    if isinstance(compatibility, Mapping) and any(
        isinstance(value, Mapping) and value.get("status") == "breaking"
        for value in compatibility.values()
    ):
        return True
    for change in impact.get("planned_changes") or []:
        if not isinstance(change, Mapping) or change.get("action") != "remove":
            continue
        if str(change.get("kind", "")).casefold() in {
            "database",
            "data_source",
            "security",
            "permission",
            "external_write",
        }:
            return True
    return False


def _validation_scope(level: str, paths: Sequence[str]) -> tuple[str, ...]:
    if level == "R0":
        return ("read_only_or_docs_tests",)
    checks = ["changed_paths", "targeted_tests", "external_delivery_attestation"]
    if level in {"R2", "R3"}:
        checks.extend(("full_contract", "compatibility", "graph_diff", "rollback"))
    if any(path_boundary(path) == "database" for path in paths):
        checks.extend(("migration_checksum", "disposable_database_parity"))
    if level == "R3":
        checks.extend(("frozen_target", "human_gate"))
    return tuple(dict.fromkeys(checks))


def classify_change(
    paths: Iterable[str] = (),
    *,
    impact: Mapping[str, Any] | None = None,
    effect_kinds: Iterable[str] = (),
    read_only: bool = False,
    uncertain: bool = False,
) -> RiskDecision:
    """Classify a change using only stable, auditable evidence.

    ``uncertain`` deliberately raises the floor by one tier (up to R3) and
    records why; callers can later lower it by supplying better evidence.
    """

    normalized = tuple(sorted({normalize_path(path) for path in paths if str(path).strip()}))
    effects = tuple(sorted({
        *(str(item).strip() for item in effect_kinds if str(item).strip()),
        *effect_kinds_from_impact(impact),
    }))
    unknown_effects = sorted(set(effects) - R3_EFFECT_KINDS)
    if unknown_effects:
        raise PolicyInputError("unknown effect kind(s): " + ", ".join(unknown_effects))

    boundaries = tuple(sorted({path_boundary(path) for path in normalized}))
    protected_boundaries = tuple(
        item for item in boundaries if item not in {"documentation", "test"}
    )
    reasons: list[str] = []
    if effects:
        level = "R3"
        reasons.append("explicit external, paid, credential, destructive, or shared-data effect")
    elif _breaking_contract(impact):
        level = "R2"
        reasons.append("breaking compatibility requires a full contract but has no R3 side effect")
    elif read_only or not normalized:
        level = "R0"
        reasons.append("read-only operation")
    elif not protected_boundaries:
        level = "R1"
        reasons.append("documentation/test write is local and recoverable")
    elif set(protected_boundaries) & {"governance", "infrastructure", "database", "api", "mcp"}:
        level = "R2"
        reasons.append("governance, infrastructure, database, API, or MCP contract boundary")
    elif len(protected_boundaries) > 1:
        level = "R2"
        reasons.append("change crosses implementation boundaries")
    else:
        level = "R1"
        reasons.append("local recoverable single-boundary change")

    if uncertain and level != "R3":
        level = RISK_LEVELS[RISK_INDEX[level] + 1]
        reasons.append("insufficient evidence; conservative one-tier escalation")

    return RiskDecision(
        level=level,
        contract_profile=CONTRACT_PROFILES[level],
        approval_required=level == "R3",
        reasons=tuple(reasons),
        boundaries=boundaries,
        validation_scope=_validation_scope(level, normalized),
    )


def derive_risk_floor(paths: Iterable[str], impact: Mapping[str, Any] | None = None) -> str:
    return classify_change(paths, impact=impact).level


def classify_scope_delta(
    current_level: str,
    existing_paths: Iterable[str],
    requested_paths: Iterable[str],
    *,
    impact: Mapping[str, Any] | None = None,
    effect_kinds: Iterable[str] = (),
) -> ScopeDeltaDecision:
    """Decide whether a deterministic scope delta is automatic or gated."""

    if current_level not in RISK_INDEX:
        raise PolicyInputError(f"unknown current risk level: {current_level!r}")
    existing = {normalize_path(path) for path in existing_paths if str(path).strip()}
    requested = {normalize_path(path) for path in requested_paths if str(path).strip()}
    added = tuple(sorted(path for path in requested if not any(path_matches(path, pattern) for pattern in existing)))
    decision = classify_change(existing | requested, impact=impact, effect_kinds=effect_kinds)
    if not added:
        action = "continue"
        reason = "requested paths are already covered"
    elif RISK_INDEX[decision.level] <= RISK_INDEX[current_level]:
        action = "auto_amend_contract"
        reason = "deterministic scope delta does not raise the declared risk tier"
    else:
        action = "block_risk_escalation"
        reason = f"scope delta raises risk from {current_level} to {decision.level}"
    return ScopeDeltaDecision(action, current_level, decision.level, added, reason)


def _fingerprint_violation(value: object) -> str:
    if isinstance(value, Mapping):
        path = str(value.get("path", "")).replace("\\", "/")
        rule = str(value.get("rule", value.get("code", "")))
        message = str(value.get("message", ""))
        return "|".join((path, rule, message))
    return str(value).strip()


def evaluate_debt_ratchet(
    baseline: Iterable[object],
    current: Iterable[object],
    *,
    changed_paths: Iterable[str] = (),
) -> DebtRatchet:
    """Allow historical debt while blocking newly introduced violations.

    When ``changed_paths`` is supplied, only new violations whose fingerprint
    begins with one of those repository-relative paths are considered in-scope.
    Existing violations remain visible in ``historical_violations``.
    """

    baseline_set = {_fingerprint_violation(item) for item in baseline if _fingerprint_violation(item)}
    current_set = {_fingerprint_violation(item) for item in current if _fingerprint_violation(item)}
    changed = tuple(sorted({normalize_path(path) for path in changed_paths if str(path).strip()}))
    new = current_set - baseline_set
    if changed:
        new = {
            item
            for item in new
            if any(item == path or item.startswith(path + "|") or item.startswith(path + ":") for path in changed)
        }
    return DebtRatchet(
        passed=not new,
        new_violations=tuple(sorted(new)),
        resolved_violations=tuple(sorted(baseline_set - current_set)),
        historical_violations=tuple(sorted(current_set & baseline_set)),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    classify = sub.add_parser("classify", help="classify repository-relative paths")
    classify.add_argument("paths", nargs="*")
    classify.add_argument("--effect", action="append", default=[])
    classify.add_argument("--read-only", action="store_true")
    classify.add_argument("--uncertain", action="store_true")
    classify.add_argument("--json", action="store_true")
    ratchet = sub.add_parser("ratchet", help="compare JSON violation arrays")
    ratchet.add_argument("--baseline", type=Path, required=True)
    ratchet.add_argument("--current", type=Path, required=True)
    ratchet.add_argument("--changed-path", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "classify":
        try:
            result = classify_change(
                args.paths,
                effect_kinds=args.effect,
                read_only=args.read_only,
                uncertain=args.uncertain,
            )
        except PolicyInputError as exc:
            print(f"[development-policy] ERROR: {exc}")
            return 2
        payload = result.to_dict()
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if args.json else f"{result.level} {result.contract_profile}: {'; '.join(result.reasons)}")
        return 0

    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        current = json.loads(args.current.read_text(encoding="utf-8"))
        if not isinstance(baseline, list) or not isinstance(current, list):
            raise PolicyInputError("ratchet inputs must be JSON arrays")
        result = evaluate_debt_ratchet(baseline, current, changed_paths=args.changed_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, PolicyInputError) as exc:
        print(f"[development-policy] ERROR: {exc}")
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
