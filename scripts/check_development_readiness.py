#!/usr/bin/env python3
"""Report the repository facts a Codex task must know before development.

This command is deliberately read-only.  It distinguishes the checkout, Git
index, and immutable HEAD instead of treating a staged file as delivered.  The
SessionStart hook uses the same report as advisory context; CI remains the
authority for delivery.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

try:
    import yaml
except ModuleNotFoundError:  # SessionStart must degrade to advisory JSON on a bare Python.
    yaml = None  # type: ignore[assignment]


CRITICAL_ASSETS = (
    "AGENTS.md",
    ".codex/hooks.json",
    ".agents/skills/omni-feature-development/SKILL.md",
    ".agents/skills/omni-feature-development/scripts/dev_contract.py",
    "scripts/check_agent_policy.py",
    "scripts/check_feature_contracts.py",
    "scripts/check_development_readiness.py",
    "scripts/development_policy.py",
    "scripts/generate_implementation_status.py",
    "scripts/workspace_ownership.py",
    "config/runtime-manifest.yaml",
    "scripts/runtime_guard.py",
    ".github/workflows/ci.yml",
)


class ReadinessInputError(ValueError):
    """The checkout cannot be inspected deterministically."""


def hook_trust_facts(root: Path) -> dict[str, Any]:
    """Report hook configuration facts without inventing host-side user trust."""

    path = root / ".codex" / "hooks.json"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        digest = None
    return {
        "status": "review_required",
        "user_confirmation": "unknown",
        "config_present": path.is_file(),
        "config_sha256": digest,
        "confirmation_surface": "/hooks",
        "reason": "repository hook configuration does not prove current-user host trust",
        "auto_inference_allowed": False,
    }


@dataclass(frozen=True)
class AssetFact:
    path: str
    worktree: bool
    index: bool
    head: bool
    worktree_matches_index: bool | None
    index_matches_head: bool | None
    state: str


@dataclass(frozen=True)
class GitStatusFacts:
    expanded_entries: int
    staged_entries: int
    unstaged_entries: int
    untracked_entries: int


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 10,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReadinessInputError(f"cannot run {' '.join(command)}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ReadinessInputError(
            f"command failed ({result.returncode}): {' '.join(command)}: {detail}"
        )
    return result


def repository_root(candidate: Path | None = None) -> Path:
    start = (candidate or Path.cwd()).resolve()
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=start, check=True)
    return Path(result.stdout.strip()).resolve()


def _git_object_exists(root: Path, object_name: str) -> bool:
    result = _run(["git", "cat-file", "-e", object_name], cwd=root)
    return result.returncode == 0


def _git_object_id(root: Path, object_name: str) -> str | None:
    result = _run(["git", "rev-parse", "--verify", object_name], cwd=root)
    return result.stdout.strip() if result.returncode == 0 else None


def _worktree_object_id(root: Path, relative: str) -> str | None:
    if not (root / relative).is_file():
        return None
    result = _run(["git", "hash-object", "--", relative], cwd=root)
    return result.stdout.strip() if result.returncode == 0 else None


def asset_facts(root: Path) -> list[AssetFact]:
    facts: list[AssetFact] = []
    for relative in CRITICAL_ASSETS:
        in_worktree = (root / relative).is_file()
        in_index = _git_object_exists(root, f":{relative}")
        in_head = _git_object_exists(root, f"HEAD:{relative}")
        worktree_id = _worktree_object_id(root, relative)
        index_id = _git_object_id(root, f":{relative}") if in_index else None
        head_id = _git_object_id(root, f"HEAD:{relative}") if in_head else None
        worktree_matches_index = (
            worktree_id == index_id if worktree_id is not None and index_id is not None else None
        )
        index_matches_head = (
            index_id == head_id if index_id is not None and head_id is not None else None
        )
        if not in_worktree:
            state = "missing"
        elif not in_index:
            state = "worktree_only"
        elif not in_head:
            state = (
                "index_candidate"
                if worktree_matches_index is True
                else "candidate_modified_after_index"
            )
        elif index_matches_head is False:
            state = (
                "staged_candidate"
                if worktree_matches_index is True
                else "candidate_modified_after_index"
            )
        elif worktree_matches_index is False:
            state = "worktree_modified"
        else:
            state = "delivered_in_head"
        facts.append(
            AssetFact(
                relative,
                in_worktree,
                in_index,
                in_head,
                worktree_matches_index,
                index_matches_head,
                state,
            )
        )
    return facts


def git_status_facts(root: Path) -> GitStatusFacts:
    result = _run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "-uall"],
        cwd=root,
        check=True,
    )
    records = [record for record in result.stdout.split("\0") if record]
    entries: list[str] = []
    skip_rename_target = False
    for record in records:
        if skip_rename_target:
            skip_rename_target = False
            continue
        if len(record) < 3:
            continue
        entries.append(record)
        if record[0] in {"R", "C"} or record[1] in {"R", "C"}:
            skip_rename_target = True
    staged = sum(1 for entry in entries if entry[0] not in {" ", "?"})
    unstaged = sum(1 for entry in entries if entry[1] not in {" ", "?"})
    untracked = sum(1 for entry in entries if entry.startswith("??"))
    return GitStatusFacts(len(entries), staged, unstaged, untracked)


def _load_impact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if yaml is None:
        return None, "PyYAML is unavailable; contract state cannot be inspected"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"cannot read contract: {exc}"
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"invalid YAML: {exc}"
    if not isinstance(value, dict):
        return None, "contract root must be a YAML mapping"
    return value, None


def _normalized_pattern(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _glob_tokens(pattern: str) -> tuple[tuple[str, str | None], ...]:
    """Tokenize the same *, ** and ? language used by dev_contract.path_matches."""

    normalized = _normalized_pattern(pattern)
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


def _tokens_can_share_character(
    left: tuple[str, str | None], right: tuple[str, str | None]
) -> bool:
    left_kind, left_value = left
    right_kind, right_value = right
    if left_kind == "literal" and right_kind == "literal":
        return left_value == right_value
    if left_kind == "literal":
        return left_value != "/" or right_kind == "many_any"
    if right_kind == "literal":
        return right_value != "/" or left_kind == "many_any"
    # All wildcard token classes share at least one non-slash character.
    return True


def contract_patterns_overlap(left: str, right: str) -> bool:
    """Return whether two contract globs can match at least one common path.

    This is a product-automaton intersection over the canonical contract glob
    language, so a subtree glob such as ``services/**`` overlaps a concrete
    child path even when their declarations are not textually identical.
    """

    return bool(_load_development_policy().glob_patterns_overlap(left, right))


@lru_cache(maxsize=1)
def _load_development_policy() -> ModuleType:
    path = Path(__file__).resolve().with_name("development_policy.py")
    spec = importlib.util.spec_from_file_location("omni_development_policy_readiness", path)
    if spec is None or spec.loader is None:
        raise ReadinessInputError(f"cannot load development policy: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def contract_facts(
    root: Path,
    *,
    delivered_contract_ids: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    active: list[dict[str, Any]] = []
    all_contracts: list[dict[str, Any]] = []
    patterns_by_contract: dict[str, set[str]] = {}
    errors: list[str] = []
    change_root = root / "docs" / "dev-changes"
    if yaml is None:
        errors.append("contract scan unavailable: PyYAML is not installed")
        return active, all_contracts, [], errors
    if not change_root.is_dir():
        return active, all_contracts, [], errors

    delivered = set(delivered_contract_ids)
    for impact_path in sorted(change_root.glob("*/impact.yaml")):
        impact, load_error = _load_impact(impact_path)
        if impact is None:
            relative = impact_path.relative_to(root).as_posix()
            change_id = impact_path.parent.name
            error = f"{relative}: {load_error or 'contract could not be parsed'}"
            errors.append(error)
            item = {
                "change_id": change_id,
                "state": "unknown",
                "schema_version": None,
                "risk_level": None,
                "path": relative,
                "error": load_error or "contract could not be parsed",
            }
            all_contracts.append(item)
            active.append(item)
            continue
        change_id = str(impact.get("change_id") or impact_path.parent.name)
        state = str(impact.get("state") or "unknown")
        risk = impact.get("risk")
        risk_level = risk.get("level") if isinstance(risk, dict) else None
        item = {
            "change_id": change_id,
            "state": state,
            "effective_state": "COMPLETE" if change_id in delivered else state,
            "schema_version": impact.get("schema_version"),
            "risk_level": risk_level,
            "path": impact_path.relative_to(root).as_posix(),
        }
        all_contracts.append(item)
        if state != "COMPLETE" and change_id not in delivered:
            active.append(item)
            patterns: set[str] = set()
            for planned in impact.get("planned_changes") or []:
                if not isinstance(planned, dict):
                    continue
                patterns.update(
                    str(value).strip().replace("\\", "/")
                    for value in planned.get("paths") or []
                    if str(value).strip()
                )
            patterns.update(
                str(value).strip().replace("\\", "/")
                for value in impact.get("allowed_unplanned_paths") or []
                if str(value).strip()
            )
            patterns_by_contract[change_id] = patterns

    overlaps: set[str] = set()
    contract_ids = sorted(patterns_by_contract)
    for index, left_id in enumerate(contract_ids):
        for right_id in contract_ids[index + 1 :]:
            for left_pattern in sorted(patterns_by_contract[left_id]):
                for right_pattern in sorted(patterns_by_contract[right_id]):
                    if not contract_patterns_overlap(left_pattern, right_pattern):
                        continue
                    if left_pattern == right_pattern:
                        label = left_pattern
                    else:
                        label = f"{left_pattern} <-> {right_pattern}"
                    overlaps.add(f"{label}: {left_id}, {right_id}")
    return active, all_contracts, sorted(overlaps), errors


def latest_ready_prd(root: Path) -> dict[str, Any] | None:
    catalog_path = root / "docs" / "prds" / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    candidates = [
        item
        for item in catalog.get("items", [])
        if isinstance(item, dict) and item.get("status") == "READY"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (str(item.get("date") or ""), str(item.get("version") or "")),
        reverse=True,
    )
    return candidates[0]


def runtime_facts(root: Path) -> dict[str, Any] | None:
    guard = root / "scripts" / "runtime_guard.py"
    if not guard.is_file():
        return None
    result = _run([sys.executable, "-B", str(guard), "audit", "--json"], cwd=root, timeout=15)
    if result.returncode not in {0, 1}:
        return {"status": "unknown", "issues": ["runtime guard could not complete"]}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "unknown", "issues": ["runtime guard returned invalid JSON"]}
    return value if isinstance(value, dict) else None


def _load_workspace_ownership(root: Path) -> ModuleType:
    path = root / "scripts" / "workspace_ownership.py"
    if not path.is_file():
        raise ReadinessInputError(f"workspace ownership tool does not exist: {path}")
    spec = importlib.util.spec_from_file_location("omni_workspace_ownership_readiness", path)
    if spec is None or spec.loader is None:
        raise ReadinessInputError(f"cannot load workspace ownership tool: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_report(
    root: Path,
    *,
    include_runtime: bool = False,
    attestation_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    head = _run(["git", "rev-parse", "HEAD"], cwd=root, check=True).stdout.strip()
    branch_result = _run(["git", "branch", "--show-current"], cwd=root)
    branch = branch_result.stdout.strip() or "DETACHED"
    assets = asset_facts(root)
    status = git_status_facts(root)
    ownership_module = _load_workspace_ownership(root)
    ownership_error: str | None = None
    try:
        ownership = ownership_module.inventory_workspace(
            root,
            include_primary=True,
            attestation_paths=attestation_paths,
            secret_scope="tracked",
        )
    except ValueError as exc:
        # SessionStart is an advisory surface.  Preserve a malformed ownership
        # input as explicit unknown evidence so contract_facts can still report
        # the precise invalid contract instead of crashing before the report.
        ownership_error = str(exc)
        ownership = {
            "status": "unknown",
            "counts": {},
            "delivered_contracts": [],
            "secret_scan": {"status": "unknown", "finding_count": 0},
            "errors": [ownership_error],
        }
    delivered_ids = [
        str(item.get("change_id"))
        for item in ownership.get("delivered_contracts", [])
        if isinstance(item, dict) and item.get("change_id")
    ]
    active, contracts, overlaps, contract_errors = contract_facts(
        root,
        delivered_contract_ids=delivered_ids,
    )
    latest_prd = latest_ready_prd(root)
    runtime = runtime_facts(root) if include_runtime else None
    hook_trust = hook_trust_facts(root)

    missing = [fact.path for fact in assets if not fact.worktree]
    not_delivered = [
        fact.path for fact in assets if fact.worktree and fact.state != "delivered_in_head"
    ]
    warnings: list[str] = []
    if missing:
        warnings.append("critical development assets missing from checkout")
    if not_delivered:
        warnings.append("critical development assets are candidates but absent from HEAD")
    if overlaps:
        warnings.append("active contracts declare overlapping path scopes")
    if contract_errors:
        warnings.append("one or more contracts have unknown or invalid state")
    if ownership_error:
        warnings.append("workspace ownership inventory is unavailable")
    ownership_counts = ownership.get("counts", {})
    if any(
        ownership_counts.get(key)
        for key in ("conflict", "scope_conflict", "lease_conflict", "unassigned")
    ):
        warnings.append("dirty linked-worktree paths have conflicting or missing ownership")
    secret_scan = ownership.get("secret_scan", {})
    if secret_scan.get("status") != "passed":
        warnings.append("tracked-baseline secret scan found redacted candidate(s)")
    if hook_trust["status"] != "confirmed":
        warnings.append("current-user hook trust requires explicit review in /hooks")
    runtime_issues: list[Any] = []
    if isinstance(runtime, dict):
        candidate = runtime.get("blocking_issues", runtime.get("issues", []))
        if isinstance(candidate, list):
            runtime_issues = candidate
        if runtime_issues:
            warnings.append("runtime ownership or source identity conflicts are present")

    if missing:
        critical_assets_status = "missing"
    elif not_delivered:
        critical_assets_status = "candidate_not_delivered"
    else:
        critical_assets_status = "delivered_in_head"
    if contract_errors:
        contracts_status = "unknown"
    elif overlaps:
        contracts_status = "overlap"
    elif active:
        contracts_status = "in_progress"
    else:
        contracts_status = "clear"
    if not include_runtime:
        runtime_status = "not_checked"
    elif not isinstance(runtime, dict) or runtime.get("status") == "unknown":
        runtime_status = "unknown"
    elif runtime_issues:
        runtime_status = "conflict"
    else:
        runtime_status = "clear"

    if missing:
        readiness = "blocked"
    elif not_delivered:
        readiness = "candidate_not_delivered"
    elif contract_errors:
        readiness = "contract_state_unknown"
    elif active:
        readiness = "development_in_progress"
    elif runtime_issues:
        readiness = "runtime_conflict"
    else:
        readiness = "ready"

    return {
        "schema_version": 1,
        "readiness": readiness,
        "readiness_scope": "advisory_development_context_not_delivery_proof",
        "strict_gate_scope": "critical_assets_only",
        "checks": {
            "critical_assets": critical_assets_status,
            "contracts": contracts_status,
            "runtime": runtime_status,
            "prd": "ready" if latest_prd is not None else "not_found",
            "ownership": (
                "unknown"
                if ownership_error
                else "conflict"
                if any(
                    ownership_counts.get(key)
                    for key in ("conflict", "scope_conflict", "lease_conflict")
                )
                else "unassigned"
                if ownership_counts.get("unassigned")
                else "clear"
            ),
            "secret_scan": secret_scan.get("status", "unknown"),
            "hook_trust": hook_trust["status"],
        },
        "repository": {
            "root": str(root),
            "head": head,
            "branch": branch,
        },
        "git_status": asdict(status),
        "critical_assets": [asdict(fact) for fact in assets],
        "missing_from_worktree": missing,
        "missing_from_head": not_delivered,
        "active_contracts": active,
        "contract_count": len(contracts),
        "overlapping_active_patterns": overlaps,
        "contract_errors": contract_errors,
        "latest_ready_prd": latest_prd,
        "runtime": runtime,
        "ownership": ownership,
        "hook_trust": hook_trust,
        "warnings": warnings,
    }


def render_context(report: dict[str, Any]) -> str:
    repository = report["repository"]
    git_status = report["git_status"]
    lines = [
        "Omni 开发上下文事实（只读；不是全面就绪或交付证明）：",
        f"- context_status={report['readiness']} branch={repository['branch']} head={repository['head'][:12]}",
        "- strict gate scope=critical_assets_only；合同、运行态与 PRD 为独立 advisory 维度。",
        "- dimensions: "
        f"critical_assets={report['checks']['critical_assets']} "
        f"contracts={report['checks']['contracts']} "
        f"runtime={report['checks']['runtime']} prd={report['checks']['prd']}",
        f"- hook_trust={report['checks']['hook_trust']}（仓库文件不等于当前用户已信任；请在 /hooks 确认）",
        "- Git: "
        f"expanded={git_status['expanded_entries']} staged={git_status['staged_entries']} "
        f"unstaged={git_status['unstaged_entries']} untracked={git_status['untracked_entries']}",
    ]
    prd = report.get("latest_ready_prd")
    if isinstance(prd, dict):
        lines.append(
            f"- 当前 READY PRD: {prd.get('prd_id')} {prd.get('version')} ({prd.get('markdown')})"
        )
    active = report.get("active_contracts") or []
    if active:
        rendered = ", ".join(
            f"{item['change_id']}[{item['state']}]" for item in active[:8]
        )
        lines.append(f"- 活跃实施合同: {rendered}")
    missing_head = report.get("missing_from_head") or []
    if missing_head:
        lines.append("- 未进入 HEAD 的关键资产: " + ", ".join(missing_head))
        lines.append("- 当前只能视为候选实现；新工作树/CI 不一定能读取，不能宣称已交付。")
    overlaps = report.get("overlapping_active_patterns") or []
    if overlaps:
        lines.append("- 合同路径重叠: " + " | ".join(overlaps[:5]))
    contract_errors = report.get("contract_errors") or []
    if contract_errors:
        lines.append("- 合同状态未知/错误: " + " | ".join(contract_errors[:5]))
    runtime = report.get("runtime")
    if isinstance(runtime, dict):
        issues = runtime.get("blocking_issues", runtime.get("issues", []))
        if isinstance(issues, list) and issues:
            lines.append(f"- 运行资源冲突: {len(issues)} 项；先查看 runtime_guard audit。")
    ownership = report.get("ownership") or {}
    counts = ownership.get("counts") or {}
    lines.append(
        "- 路径归属: "
        f"active={counts.get('active_change', 0)} preserved_external_user={counts.get('preserved_external_user', 0)} "
        f"unassigned={counts.get('unassigned', 0)} conflict={counts.get('conflict', 0)} "
        f"archive_candidate={counts.get('archive_candidate', 0)}"
    )
    secret_scan = ownership.get("secret_scan") or {}
    lines.append(
        f"- Secret scan({secret_scan.get('scope', 'changed')}): {secret_scan.get('status', 'unknown')} "
        f"findings={secret_scan.get('finding_count', 0)}（仅 path/rule/fingerprint）"
    )
    lines.extend(
        [
            "- 开发前先读 READY PRD 与实施进度；按 R0/R1/R2/R3 选择流程。",
            "- 本地/暂存验证只表示 candidate；只有不可变提交通过 CI delivery attestation 才表示 delivered。",
        ]
    )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="repository root; defaults to current Git root")
    parser.add_argument("--json", action="store_true", help="emit the complete JSON report")
    parser.add_argument("--hook", action="store_true", help="emit SessionStart hook JSON")
    parser.add_argument("--runtime", action="store_true", help="include read-only Docker runtime audit")
    parser.add_argument(
        "--attestation",
        type=Path,
        action="append",
        default=[],
        help="external delivery receipt; shared Git common-dir cache is also consulted",
    )
    parser.add_argument(
        "--strict-critical-assets",
        "--strict",
        dest="strict_critical_assets",
        action="store_true",
        help=(
            "fail only when critical assets are absent from the checkout or immutable HEAD; "
            "this is not a full development-readiness or delivery gate"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Hook JSON must be UTF-8 even when Windows inherited a legacy console code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv)
    try:
        root = repository_root(args.root)
        report = build_report(
            root,
            include_runtime=args.runtime,
            attestation_paths=args.attestation,
        )
    except ReadinessInputError as exc:
        if args.hook:
            print(
                json.dumps(
                    {
                        "systemMessage": f"Omni development readiness unavailable: {exc}",
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": "开发启动检查失败；不要把未知状态当成已交付。",
                        },
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"[development-readiness] ERROR: {exc}", file=sys.stderr)
        return 0 if args.hook else 2

    if args.hook:
        # Consume hook input when present so malformed transport cannot leak into output.
        try:
            if not sys.stdin.isatty():
                json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            pass
        context = render_context(report)
        output: dict[str, Any] = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        if report["warnings"]:
            output["systemMessage"] = (
                "Omni 开发上下文存在未收口或未知项；这不是全面就绪或已交付证明。"
            )
        print(json.dumps(output, ensure_ascii=False))
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_context(report))

    if args.strict_critical_assets and (
        report["missing_from_worktree"] or report["missing_from_head"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
