#!/usr/bin/env python3
"""Generate the PRD implementation projection from contracts and receipts.

The output is evidence, never an authority.  A schema-v3 contract can become
``VERIFIED_NOT_DELIVERED`` locally, but only a valid external CI attestation for
an immutable, reachable commit can project ``COMPLETE``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import sys
import time
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence
from typing import Callable

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependency
    raise SystemExit("PyYAML is required: install package 'pyyaml'.") from exc


DEFAULT_PRD_ID = "2026-07-29-omni-fde-system-convergence-master-prd"
DEFAULT_STATUS_RELATIVE = f"docs/prds/{DEFAULT_PRD_ID}/implementation-status.yaml"
SLICE_ORDER = ("S0", "S0.5", "S1", "S1.5", "S2", "S2.5", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14")
SLICE_TITLES = {
    "S0": "安全与基线复核",
    "S0.5": "交付真值收口",
    "S1": "治理底座与风险分级",
    "S1.5": "并发运行隔离与Migration单路径",
    "S2": "风险感知本地过程闸门",
    "S2.5": "真健康、错误语义与非阻塞审批",
    "S3": "FeatureDefinition与静态图核心",
    "S4": "Planned/fact、Issue与CI warning",
    "S5": "候选功能接入共创",
    "S6": "真实小功能试点与block校准",
    "S7": "图谱API与统一系统中台静态面",
    "S8": "运行追踪事件脊柱",
    "S9": "执行微动画、中文解释与四层雷达",
    "S10": "Host Bridge与Agent合同",
    "S11": "前端收敛",
    "S12": "后端单真源",
    "S13": "兼容面与客户端退役",
    "S14": "全仓推广",
}


def hook_trust_facts(root: Path) -> dict[str, Any]:
    """Keep repository delivery separate from current-user hook trust."""

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
        "reason": "repository hook delivery cannot establish current-user host trust",
        "auto_inference_allowed": False,
    }
PROGRESS_RANK = {"NOT_STARTED": 0, "IN_PROGRESS": 1, "VERIFIED_NOT_DELIVERED": 2, "COMPLETE": 3}


class ProjectionInputError(ValueError):
    """Projection evidence is malformed or unavailable."""


ProvenanceVerifier = Callable[[Path, Mapping[str, Any], Path | None], Mapping[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command), cwd=cwd, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=max(0.05, timeout), check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectionInputError(f"cannot run {' '.join(command)}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ProjectionInputError(f"command failed ({result.returncode}): {' '.join(command)}: {detail}")
    return result


def repository_root(candidate: Path) -> Path:
    result = _run(("git", "rev-parse", "--show-toplevel"), cwd=candidate.resolve())
    return Path(result.stdout.strip()).resolve()


def git_common_dir(root: Path) -> Path:
    result = _run(("git", "rev-parse", "--git-common-dir"), cwd=root)
    value = Path(result.stdout.strip())
    return (root / value).resolve() if not value.is_absolute() else value.resolve()


def receipt_cache_dir(root: Path) -> Path:
    """Return the cross-worktree cache location (never a worktree-local .runtime)."""

    return git_common_dir(root) / "omni-delivery" / "verified-receipts"


def discover_receipt_paths(root: Path, explicit: Iterable[Path] = ()) -> tuple[Path, ...]:
    candidates = {path.resolve() for path in explicit if path.is_file()}
    cache = receipt_cache_dir(root)
    if cache.is_dir():
        candidates.update(path.resolve() for path in cache.glob("*.json") if path.is_file())
    return tuple(sorted(candidates, key=lambda item: str(item).casefold()))


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProjectionInputError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectionInputError(f"YAML root must be a mapping: {path}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionInputError(f"cannot read receipt {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectionInputError(f"receipt root must be a mapping: {path}")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_commit(root: Path, value: object) -> str | None:
    candidate = str(value or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        return None
    result = _run(("git", "rev-parse", "--verify", f"{candidate}^{{commit}}"), cwd=root, check=False)
    return result.stdout.strip().lower() if result.returncode == 0 else None


def _git_ancestor(root: Path, ancestor: str, descendant_ref: str) -> bool:
    result = _run(("git", "merge-base", "--is-ancestor", ancestor, descendant_ref), cwd=root, check=False)
    return result.returncode == 0


def _git_tree(root: Path, subject: str) -> str | None:
    result = _run(("git", "rev-parse", "--verify", f"{subject}^{{tree}}"), cwd=root, check=False)
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def _git_text(root: Path, commit: str, relative: str) -> str | None:
    result = _run(("git", "show", f"{commit}:{relative}"), cwd=root, check=False)
    return result.stdout if result.returncode == 0 else None


def _changed_paths(root: Path, base: str, subject: str) -> tuple[str, ...] | None:
    result = _run(
        ("git", "-c", "core.quotepath=false", "diff", "--name-only", "--diff-filter=ACMRTD", "-z", f"{base}...{subject}", "--"),
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        return None
    return tuple(sorted(item.replace("\\", "/") for item in result.stdout.split("\0") if item))


def _checks_passed(receipt: Mapping[str, Any]) -> bool:
    checks = receipt.get("required_checks", receipt.get("checks"))
    if checks is None:
        return False
    if isinstance(checks, Mapping):
        values = checks.values()
    elif isinstance(checks, list):
        values = checks
    else:
        return False
    normalized: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("status", value.get("conclusion", ""))
        normalized.append(str(value).casefold())
    return bool(normalized) and all(item in {"passed", "success", "successful", "completed"} for item in normalized)


def _remaining_timeout(deadline: float | None, cap: float) -> float:
    if deadline is None:
        return cap
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProjectionInputError("live provenance total deadline exhausted")
    return min(cap, remaining)


def repository_identity(root: Path, *, deadline: float | None = None) -> str | None:
    result = _run(
        ("git", "remote", "get-url", "origin"),
        cwd=root,
        check=False,
        timeout=_remaining_timeout(deadline, 5),
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip().removesuffix(".git")
    match = re.search(r"(?:github\.com[:/])([^/]+)/([^/]+)$", value, re.IGNORECASE)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _download_attestation_payload(
    root: Path,
    repository: str,
    artifact: Mapping[str, Any],
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    artifact_id = str(artifact.get("id") or "")
    if not artifact_id.isdigit():
        raise ProjectionInputError("GitHub artifact id is invalid")
    try:
        result = subprocess.run(
            ("gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"),
            cwd=root,
            capture_output=True,
            check=False,
            timeout=_remaining_timeout(deadline, 15),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectionInputError("GitHub artifact download failed") from exc
    if result.returncode != 0 or not result.stdout or len(result.stdout) > 5_000_000:
        raise ProjectionInputError("GitHub artifact download is unavailable or oversized")
    try:
        with zipfile.ZipFile(BytesIO(result.stdout)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > 10 or sum(item.file_size for item in infos) > 5_000_000:
                raise ProjectionInputError("delivery artifact archive violates size/count limits")
            receipts: list[zipfile.ZipInfo] = []
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                parts = [part for part in normalized.split("/") if part not in {"", "."}]
                mode = (info.external_attr >> 16) & 0o170000
                if (
                    normalized.startswith("/")
                    or re.match(r"^[A-Za-z]:", normalized)
                    or any(part == ".." for part in parts)
                    or mode == stat.S_IFLNK
                ):
                    raise ProjectionInputError("delivery artifact contains an unsafe archive member")
                if parts and parts[-1] == "delivery-attestation.json" and not info.is_dir():
                    receipts.append(info)
            if len(receipts) != 1:
                raise ProjectionInputError("delivery artifact must contain exactly one attestation")
            raw = archive.read(receipts[0])
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        if isinstance(exc, ProjectionInputError):
            raise
        raise ProjectionInputError("delivery artifact archive is invalid") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionInputError("delivery artifact attestation is invalid") from exc
    if not isinstance(payload, dict):
        raise ProjectionInputError("delivery artifact attestation root must be a mapping")
    return payload


def live_github_provenance(
    root: Path,
    receipt: Mapping[str, Any],
    receipt_path: Path | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Verify GitHub run and artifact metadata without trusting local JSON."""

    del receipt_path
    reasons: list[str] = []
    try:
        repository = repository_identity(root, deadline=deadline)
    except ProjectionInputError:
        return {"valid": False, "reasons": ["live_provenance_total_deadline_exhausted"]}
    if not repository:
        return {"valid": False, "reasons": ["repository_identity_unavailable"]}
    run_id = str(receipt.get("workflow_run_id", receipt.get("run_id", ""))).strip()
    subject = str(receipt.get("subject_commit", receipt.get("delivered_commit", ""))).strip().lower()
    if not run_id.isdigit():
        return {"valid": False, "reasons": ["workflow_run_id_missing"]}
    command = (
        "gh", "run", "view", run_id, "--repo", repository,
        "--json", "databaseId,headSha,headBranch,conclusion,event,status,url",
    )
    try:
        result = _run(
            command,
            cwd=root,
            check=False,
            timeout=_remaining_timeout(deadline, 10),
        )
    except ProjectionInputError:
        return {"valid": False, "reasons": ["live_provenance_total_deadline_exhausted"]}
    if result.returncode != 0:
        return {"valid": False, "reasons": ["github_run_unverifiable"]}
    try:
        run = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"valid": False, "reasons": ["github_run_metadata_invalid"]}
    if str(run.get("headSha", "")).lower() != subject:
        reasons.append("github_run_head_mismatch")
    if run.get("headBranch") != "main" or run.get("event") != "push":
        reasons.append("github_run_not_trusted_main_push")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        reasons.append("github_required_checks_not_successful")
    try:
        artifact_result = _run(
            ("gh", "api", f"repos/{repository}/actions/runs/{run_id}/artifacts"),
            cwd=root,
            check=False,
            timeout=_remaining_timeout(deadline, 10),
        )
    except ProjectionInputError:
        return {"valid": False, "reasons": ["live_provenance_total_deadline_exhausted"]}
    artifact: Mapping[str, Any] | None = None
    evidence_artifact: Mapping[str, Any] | None = None
    if artifact_result.returncode == 0:
        try:
            artifacts = json.loads(artifact_result.stdout).get("artifacts", [])
            expected_name = str(receipt.get("attestation_artifact_name") or f"delivery-attestation-{subject}")
            artifact = next(
                (item for item in artifacts if isinstance(item, Mapping) and item.get("name") == expected_name and not item.get("expired")),
                None,
            )
            evidence = receipt.get("evidence_artifact")
            if isinstance(evidence, Mapping):
                evidence_artifact = next(
                    (
                        item
                        for item in artifacts
                        if isinstance(item, Mapping)
                        and item.get("name") == evidence.get("name")
                        and not item.get("expired")
                    ),
                    None,
                )
        except (json.JSONDecodeError, AttributeError):
            artifact = None
    if artifact is None:
        reasons.append("github_delivery_artifact_missing")
    observed_digest = str((evidence_artifact or {}).get("digest") or "")
    if receipt.get("schema_version") == 2:
        evidence = receipt.get("evidence_artifact")
        if not isinstance(evidence, Mapping) or not evidence.get("name") or not evidence.get("digest"):
            reasons.append("evidence_artifact_missing")
        elif evidence_artifact is None:
            reasons.append("github_evidence_artifact_missing")
        elif not observed_digest or observed_digest != str(evidence.get("digest")):
            reasons.append("evidence_artifact_digest_mismatch")
    if artifact is not None:
        try:
            authoritative = _download_attestation_payload(
                root, repository, artifact, deadline=deadline
            )
            local_digest = _sha256_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            authoritative_digest = _sha256_text(json.dumps(authoritative, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            if local_digest != authoritative_digest:
                reasons.append("local_receipt_differs_from_signed_artifact")
        except ProjectionInputError:
            reasons.append("signed_artifact_content_unverifiable")
    declared_repo = str(receipt.get("repository") or "")
    if receipt.get("schema_version") == 2 and declared_repo != repository:
        reasons.append("repository_identity_mismatch")
    return {
        "valid": not reasons,
        "reasons": reasons,
        "repository": repository,
        "target_ref": "refs/heads/main",
        "head_sha": str(run.get("headSha", "")).lower(),
        "workflow_run_id": run_id,
        "attestation_artifact_name": (artifact or {}).get("name"),
        "evidence_artifact_name": (evidence_artifact or {}).get("name"),
        "evidence_artifact_digest": observed_digest or None,
        "checks_passed": run.get("conclusion") == "success",
    }


def offline_provenance(
    _root: Path,
    _receipt: Mapping[str, Any],
    _receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Fast default: never turn an unrefreshed local receipt into delivery proof."""

    return {
        "valid": False,
        "reasons": ["live_provenance_refresh_required"],
        "checks_passed": False,
    }


def bounded_live_provenance(total_timeout_seconds: float) -> ProvenanceVerifier:
    """Share one wall-clock deadline across every receipt in a projection."""

    if not 0 < total_timeout_seconds <= 60:
        raise ProjectionInputError("live provenance timeout must be within (0, 60] seconds")
    deadline = time.monotonic() + total_timeout_seconds

    def verify(
        root: Path,
        receipt: Mapping[str, Any],
        receipt_path: Path | None = None,
    ) -> Mapping[str, Any]:
        if time.monotonic() >= deadline:
            return {
                "valid": False,
                "reasons": ["live_provenance_total_deadline_exhausted"],
                "checks_passed": False,
            }
        return live_github_provenance(
            root, receipt, receipt_path, deadline=deadline
        )

    return verify


def verify_delivery_receipt(
    root: Path,
    receipt: Mapping[str, Any],
    change_id: str,
    *,
    receipt_path: Path | None = None,
    provenance_verifier: ProvenanceVerifier | None = None,
) -> dict[str, Any]:
    """Verify one immutable external receipt without trusting its status label."""

    reasons: list[str] = []
    schema_version = receipt.get("schema_version")
    if schema_version not in {1, 2}:
        reasons.append("unsupported_receipt_schema")
    if receipt.get("authority") != "ci_attestation":
        reasons.append("authority_not_ci_attestation")
    if str(receipt.get("status", "")).upper() != "COMPLETE":
        reasons.append("receipt_status_not_complete")
    subject = _git_commit(root, receipt.get("subject_commit", receipt.get("delivered_commit")))
    if subject is None:
        reasons.append("subject_commit_missing_or_unresolvable")
    target_ref = str(receipt.get("target_ref") or ("refs/heads/main" if schema_version == 1 else "")).strip()
    provenance: Mapping[str, Any] = {"valid": False, "reasons": ["trusted_provenance_not_verified"]}
    if provenance_verifier is not None:
        try:
            provenance = provenance_verifier(root, receipt, receipt_path)
        except Exception:
            provenance = {"valid": False, "reasons": ["trusted_provenance_verifier_failed"]}
    if provenance.get("valid") is not True:
        reasons.extend(str(item) for item in provenance.get("reasons", ["trusted_provenance_not_verified"]))
    if schema_version == 2:
        required_v2 = (
            "repository", "target_ref", "workflow_run_id", "head_sha",
            "attestation_artifact_name", "evidence_artifact", "required_checks", "delivered_tree",
        )
        reasons.extend(f"{field}_missing" for field in required_v2 if not receipt.get(field))
        if target_ref != "refs/heads/main":
            reasons.append("target_ref_not_trusted_default")
        if subject and str(receipt.get("head_sha", "")).lower() != subject:
            reasons.append("head_sha_mismatch")
        repo = repository_identity(root)
        if repo and receipt.get("repository") != repo:
            reasons.append("repository_identity_mismatch")
        provenance_pairs = (
            ("repository", "repository_identity_mismatch"),
            ("target_ref", "provenance_target_ref_mismatch"),
            ("head_sha", "provenance_head_sha_mismatch"),
            ("workflow_run_id", "provenance_workflow_run_mismatch"),
            ("attestation_artifact_name", "provenance_artifact_name_mismatch"),
        )
        for field, code in provenance_pairs:
            if provenance.get(field) is not None and str(receipt.get(field)) != str(provenance.get(field)):
                reasons.append(code)
        evidence = receipt.get("evidence_artifact")
        if isinstance(evidence, Mapping):
            if provenance.get("evidence_artifact_name") is not None and str(evidence.get("name")) != str(provenance.get("evidence_artifact_name")):
                reasons.append("provenance_evidence_artifact_name_mismatch")
            if provenance.get("evidence_artifact_digest") is not None and str(evidence.get("digest")) != str(provenance.get("evidence_artifact_digest")):
                reasons.append("provenance_evidence_artifact_digest_mismatch")
    if subject is not None:
        provenance_target = str(provenance.get("target_ref") or target_ref)
        if provenance_target:
            local_target = "refs/remotes/origin/main" if _run(("git", "rev-parse", "--verify", "refs/remotes/origin/main"), cwd=root, check=False).returncode == 0 else target_ref
            if not local_target or not _git_ancestor(root, subject, local_target):
                reasons.append("subject_not_reachable_from_target_ref")
        else:
            reasons.append("target_ref_unresolvable")
        if receipt.get("reachable") is False:
            reasons.append("receipt_declares_unreachable")
        declared_tree = str(receipt.get("delivered_tree") or receipt.get("subject_tree") or "").lower()
        actual_tree = _git_tree(root, subject)
        if not declared_tree:
            reasons.append("delivered_tree_missing")
        elif actual_tree != declared_tree:
            reasons.append("delivered_tree_mismatch")
    if not _checks_passed(receipt) and provenance.get("checks_passed") is not True:
        reasons.append("required_checks_not_passed")

    contract_records = receipt.get("contracts")
    contract_record: Mapping[str, Any] | None = None
    if isinstance(contract_records, list):
        contract_record = next(
            (item for item in contract_records if isinstance(item, Mapping) and item.get("change_id") == change_id),
            None,
        )
    elif receipt.get("change_id") == change_id:
        contract_record = receipt
    if contract_record is None:
        reasons.append("change_not_present_in_receipt")
    elif subject is not None:
        contract_prefix = f"docs/dev-changes/{change_id}"
        for name, field in (("impact.yaml", "impact_sha256"), ("completion.yaml", "completion_sha256")):
            expected = contract_record.get(field)
            text = _git_text(root, subject, f"{contract_prefix}/{name}")
            if not expected:
                reasons.append(f"{field}_missing")
            if text is None:
                reasons.append(f"subject_contract_{name.replace('.', '_')}_missing")
            elif expected and _sha256_text(text) != str(expected):
                reasons.append(f"{field}_mismatch")
        base = _git_commit(root, contract_record.get("base_commit"))
        expected_diff = contract_record.get("changed_paths_sha256", contract_record.get("diff_sha256"))
        if not contract_record.get("base_commit"):
            reasons.append("base_commit_missing")
        elif base is None:
            reasons.append("base_commit_unresolvable")
        elif not _git_ancestor(root, base, subject):
            reasons.append("base_commit_not_ancestor")
        if not expected_diff:
            reasons.append("changed_paths_sha256_missing")
        else:
            paths = _changed_paths(root, base, subject) if base else None
            digest = _sha256_text("\n".join(paths or ()) + ("\n" if paths else "")) if paths is not None else None
            if digest != str(expected_diff):
                reasons.append("changed_paths_sha256_mismatch")

    if receipt_path is not None and subject is not None:
        try:
            relative = receipt_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = ""
        if relative and _git_text(root, subject, relative) is not None:
            reasons.append("receipt_is_inside_subject_commit")

    receipt_digest = _sha256_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return {
        "change_id": change_id,
        "valid": not reasons,
        "delivery_state": "delivered" if not reasons else "stale",
        "subject_commit": subject,
        "target_ref": target_ref or None,
        "receipt_sha256": receipt_digest,
        "receipt_locator": receipt_path.name if receipt_path else "inline",
        "reasons": reasons,
    }


def resolve_delivered_contracts(
    root: Path,
    receipt_paths: Iterable[Path] = (),
    *,
    provenance_verifier: ProvenanceVerifier | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve verified delivered contracts from explicit paths and shared cache."""

    root = repository_root(root)
    resolved: dict[str, dict[str, Any]] = {}
    verifier = provenance_verifier or offline_provenance
    for path in discover_receipt_paths(root, receipt_paths):
        try:
            receipt = _read_json(path)
        except ProjectionInputError:
            continue
        ids: list[str] = []
        contracts = receipt.get("contracts")
        if isinstance(contracts, list):
            ids.extend(
                str(item.get("change_id"))
                for item in contracts
                if isinstance(item, Mapping) and item.get("change_id")
            )
        if receipt.get("change_id"):
            ids.append(str(receipt["change_id"]))
        for change_id in dict.fromkeys(ids):
            result = verify_delivery_receipt(
                root,
                receipt,
                change_id,
                receipt_path=path,
                provenance_verifier=verifier,
            )
            if result["valid"]:
                resolved[change_id] = result
    return resolved


def _contract_slices(impact: Mapping[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    for item in impact.get("feature_refs") or []:
        if not isinstance(item, Mapping):
            continue
        reference = str(item.get("feature_ref", ""))
        tokens = [f"S{match}" for match in re.findall(r"S(\d+(?:\.\d+)?)", reference)]
        if len(tokens) >= 2 and "-" in reference:
            try:
                start, end = SLICE_ORDER.index(tokens[0]), SLICE_ORDER.index(tokens[-1])
            except ValueError:
                continue
            found.extend(SLICE_ORDER[start : end + 1])
        else:
            found.extend(token for token in tokens if token in SLICE_ORDER)
    return tuple(dict.fromkeys(found))


def _contract_status(
    state: str,
    delivery: Mapping[str, Any] | None,
    *,
    schema_version: int | None,
) -> str:
    if delivery and delivery.get("valid") is True:
        return "COMPLETE"
    # Schema v1/v2 predate external delivery attestations and used their
    # immutable COMPLETE contract state as authority. Preserve that historical
    # compatibility; schema v3 remains fail-closed without trusted CI evidence.
    if schema_version in {1, 2} and state == "COMPLETE":
        return "COMPLETE"
    if state == "GRAPH_DIFF_READY":
        return "VERIFIED_NOT_DELIVERED"
    if state in {"IMPACT_LOCKED", "IMPLEMENTING", "VERIFYING"}:
        return "IN_PROGRESS"
    if state == "DISCOVERED":
        return "NOT_STARTED"
    return "UNKNOWN"


def _all_required_status(items: Iterable[str]) -> str:
    statuses = tuple(items)
    if not statuses:
        return "NOT_STARTED"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return min(statuses, key=lambda item: PROGRESS_RANK[item])


def _s0_gate_status(evidence: Mapping[str, Any]) -> tuple[str, list[str]]:
    failures: list[str] = []
    unknowns: list[str] = []
    secret = evidence.get("secret_scan") if isinstance(evidence.get("secret_scan"), Mapping) else {}
    if secret.get("status") == "failed":
        failures.append("secret_scan_failed")
    elif secret.get("status") != "passed":
        unknowns.append("secret_scan_unknown")
    ownership = evidence.get("ownership") if isinstance(evidence.get("ownership"), Mapping) else {}
    counts = ownership.get("counts") if isinstance(ownership.get("counts"), Mapping) else {}
    if any(int(counts.get(key, 0) or 0) for key in ("conflict", "scope_conflict", "lease_conflict", "unassigned")):
        failures.append("workspace_ownership_conflict")
    elif ownership.get("status") not in {"passed", "clear"}:
        unknowns.append("workspace_ownership_unknown")
    migration = evidence.get("migration_baseline") if isinstance(evidence.get("migration_baseline"), Mapping) else {}
    if migration.get("status") in {"failed", "blocked", "drift"}:
        failures.append("migration_baseline_failed")
    elif migration.get("status") not in {"ready", "passed", "verified"}:
        unknowns.append("migration_baseline_unknown")
    if failures:
        return "BLOCKED", failures + unknowns
    if unknowns:
        return "UNKNOWN", unknowns
    return "COMPLETE", []


def _load_contracts(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    contracts: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "docs" / "dev-changes").glob("*/impact.yaml")):
        contracts.append((path, _read_yaml(path)))
    return contracts


def _load_ownership_scanner(root: Path) -> ModuleType:
    # Use the generator's installed companion implementation while scanning the
    # caller-supplied repository (important for isolated Git fixtures).
    path = Path(__file__).resolve().with_name("workspace_ownership.py")
    spec = importlib.util.spec_from_file_location("omni_workspace_ownership_projection", path)
    if spec is None or spec.loader is None:
        raise ProjectionInputError(f"cannot load ownership scanner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def summarize_secret_scan(scan: Mapping[str, Any], *, sample_limit: int = 8) -> dict[str, Any]:
    """Keep projection evidence bounded while the scanner retains full audit detail."""

    value = dict(scan)
    skipped = [item for item in value.pop("skipped", []) if isinstance(item, Mapping)]
    by_reason: dict[str, int] = {}
    for item in skipped:
        reason = str(item.get("reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    value["skipped_summary"] = {
        "count": len(skipped),
        "by_reason": dict(sorted(by_reason.items())),
        "samples": [
            {"path": str(item.get("path") or ""), "reason": str(item.get("reason") or "unknown")}
            for item in skipped[:sample_limit]
        ],
        "sample_limit": sample_limit,
    }
    findings = [item for item in value.get("findings", []) if isinstance(item, Mapping)]
    value["findings"] = findings[:50]
    value["findings_truncated"] = len(findings) > 50
    return value


def collect_s0_evidence(
    root: Path,
    *,
    attestation_paths: Iterable[Path] = (),
    delivered_contract_ids: Iterable[str] = (),
    migration_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    scanner = _load_ownership_scanner(root)
    inventory = scanner.inventory_workspace(
        root,
        include_primary=True,
        attestation_paths=attestation_paths,
        delivered_contract_ids=delivered_contract_ids,
        secret_scope="tracked",
    )
    return {
        "secret_scan": summarize_secret_scan(
            inventory.get("secret_scan", {"status": "unknown"})
        ),
        "ownership": {
            "status": "passed" if not any(
                int(inventory.get("counts", {}).get(key, 0) or 0)
                for key in ("conflict", "scope_conflict", "lease_conflict", "unassigned")
            ) else "failed",
            "counts": inventory.get("counts", {}),
        },
        "migration_baseline": dict(migration_baseline or {"status": "unknown"}),
    }


def build_projection(
    root: Path,
    *,
    receipts: Iterable[tuple[Path | None, Mapping[str, Any]]] = (),
    source_status: Mapping[str, Any] | None = None,
    provenance_verifier: ProvenanceVerifier | None = None,
    s0_evidence: Mapping[str, Any] | None = None,
    hook_trust: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = repository_root(root)
    head = _run(("git", "rev-parse", "HEAD"), cwd=root).stdout.strip()
    branch = _run(("git", "branch", "--show-current"), cwd=root, check=False).stdout.strip() or "DETACHED"
    receipt_values = list(receipts)
    contract_evidence: list[dict[str, Any]] = []
    projection_errors: list[str] = []
    projected: dict[str, list[dict[str, Any]]] = {slice_id: [] for slice_id in SLICE_ORDER}

    for path, impact in _load_contracts(root):
        change_id = str(impact.get("change_id") or path.parent.name)
        receipt_result: dict[str, Any] | None = None
        for receipt_path, receipt in receipt_values:
            candidate = verify_delivery_receipt(
                root,
                receipt,
                change_id,
                receipt_path=receipt_path,
                provenance_verifier=provenance_verifier,
            )
            if candidate["valid"] or receipt_result is None:
                receipt_result = candidate
            if candidate["valid"]:
                break
        state = str(impact.get("state", "UNKNOWN"))
        effective = _contract_status(
            state,
            receipt_result,
            schema_version=impact.get("schema_version"),
        )
        slices = _contract_slices(impact)
        refs_text = json.dumps(impact.get("feature_refs") or [], ensure_ascii=False).casefold()
        if not slices and "system-convergence" in refs_text:
            projection_errors.append(f"{change_id}: system-convergence feature_ref has no slice mapping")
        evidence = {
            "change_id": change_id,
            "contract_state": state,
            "effective_state": effective,
            "risk_level": (impact.get("risk") or {}).get("level") if isinstance(impact.get("risk"), Mapping) else None,
            "contract_path": path.relative_to(root).as_posix(),
            "slices": list(slices),
            "delivery": receipt_result or {"valid": False, "delivery_state": "verified_not_delivered", "reasons": ["external_receipt_not_supplied"]},
        }
        contract_evidence.append(evidence)
        for slice_id in slices:
            projected[slice_id].append(evidence)

    slices_payload: list[dict[str, Any]] = []
    for slice_id in SLICE_ORDER:
        evidence = projected[slice_id]
        status = _all_required_status(item["effective_state"] for item in evidence)
        slices_payload.append(
            {
                "id": slice_id,
                "title": SLICE_TITLES[slice_id],
                "status": status,
                "completion_claimed": status == "COMPLETE",
                "evidence_refs": [item["change_id"] for item in evidence],
                "remaining": [] if status == "COMPLETE" else [
                    "Complete required verification and obtain a trusted external delivery attestation."
                ] if evidence else [],
            }
        )
    s0_values = dict(s0_evidence or {})
    if not s0_values:
        scanner = _load_ownership_scanner(root)
        s0_values = {
            "secret_scan": scanner.scan_secrets(root, scope="tracked"),
            "ownership": {"status": "unknown", "counts": {}},
            "migration_baseline": {"status": "unknown"},
        }
    s0_gate, s0_gate_reasons = _s0_gate_status(s0_values)
    s0_slice = next(item for item in slices_payload if item["id"] == "S0")
    if s0_gate == "COMPLETE" and s0_slice["status"] == "NOT_STARTED":
        s0_slice["status"] = "COMPLETE"
        s0_slice["completion_claimed"] = True
        s0_slice["remaining"] = []
    elif s0_gate != "COMPLETE":
        s0_slice["status"] = s0_gate
        s0_slice["completion_claimed"] = False
        s0_slice["remaining"] = s0_gate_reasons
    if projection_errors:
        s0_slice["status"] = "BLOCKED"
        s0_slice["completion_claimed"] = False
        s0_slice["remaining"].extend(projection_errors)

    hook_trust_value = dict(hook_trust or hook_trust_facts(root))
    if hook_trust_value.get("status") != "confirmed":
        s05_slice = next(item for item in slices_payload if item["id"] == "S0.5")
        s05_slice["status"] = "BLOCKED"
        s05_slice["completion_claimed"] = False
        s05_slice["remaining"] = [
            "current_user_hook_trust_confirmation_required:/hooks"
        ]

    prerequisite: str | None = None
    for slice_item in slices_payload[: SLICE_ORDER.index("S3") + 1]:
        if prerequisite is not None and slice_item["status"] == "COMPLETE":
            slice_item["status"] = "BLOCKED"
            slice_item["completion_claimed"] = False
            slice_item["remaining"] = [f"prerequisite_not_complete:{prerequisite}"]
        if prerequisite is None and slice_item["status"] != "COMPLETE":
            prerequisite = slice_item["id"]
    current = next((item for item in slices_payload if item["status"] != "COMPLETE"), slices_payload[-1])
    document = (source_status or {}).get("document") if isinstance(source_status, Mapping) else None
    if not isinstance(document, Mapping):
        document = {
            "prd_id": DEFAULT_PRD_ID,
            "prd_version": "v1.2",
            "prd_status": "READY",
            "source_markdown": f"{DEFAULT_PRD_ID}-v1.2.md",
        }
    dirty_count = int(_run(("git", "status", "--porcelain=v1", "-uall"), cwd=root).stdout.count("\n"))
    ownership_scanner = _load_ownership_scanner(root)
    secret_scan = s0_values.get("secret_scan") or ownership_scanner.scan_secrets(root, scope="tracked")
    changed_paths = ownership_scanner._scan_paths(root, "changed")
    archive_count = sum(1 for path in changed_paths if ownership_scanner.archive_candidate(path))
    return {
        "schema_version": 2,
        "kind": "omni_prd_implementation_status",
        "document": dict(document),
        "generation": {
            "mode": "machine_projection",
            "generated_at": utc_now(),
            "generated_by": "scripts/generate_implementation_status.py",
            "manual_completion_allowed": False,
            "source_hash": _sha256_text(json.dumps(contract_evidence, ensure_ascii=False, sort_keys=True)),
        },
        "audit_snapshot": {
            "temporal_scope": "point_in_time",
            "repository": {"head": head, "branch": branch, "dirty": dirty_count > 0, "dirty_path_count": dirty_count},
            "s0_evidence": {
                "secret_scan": secret_scan,
                "ownership": s0_values.get("ownership", {"status": "unknown"}),
                "migration_baseline": s0_values.get("migration_baseline", {"status": "unknown"}),
                "gate_status": s0_gate,
                "gate_reasons": s0_gate_reasons,
                "archive_candidate_count": archive_count,
                "cleanup_mutated": False,
            },
            "hook_trust": hook_trust_value,
        },
        "projection_policy": {
            "contract_schema_for_new_changes": 3,
            "external_delivery_attestation_required": True,
            "receipt_must_be_outside_subject_commit": True,
            "unknown_is_not_complete": True,
            "historical_receipts_are_immutable": True,
            "repository_hook_delivery_does_not_imply_user_trust": True,
        },
        "current": {
            "slice_id": current["id"],
            "status": current["status"],
            "completion_claimed": current["status"] == "COMPLETE",
            "reason": "Projected from immutable contracts and externally supplied receipts; local verification alone is not delivery.",
        },
        "contracts": contract_evidence,
        "projection_errors": projection_errors,
        "slices": slices_payload,
        "refresh_contract": {
            "inputs": ["docs/dev-changes/*/impact.yaml", "external DeliveryReceipt artifacts", "Git reachability and immutable blobs"],
            "update_rule": "Regenerate from evidence; never edit a slice to COMPLETE by hand.",
        },
    }


def write_projection(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(yaml.safe_dump(dict(payload), allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    temporary.replace(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path, action="append", default=[])
    parser.add_argument("--receipt-dir", type=Path, action="append", default=[])
    parser.add_argument(
        "--migration-evidence",
        type=Path,
        help="JSON output from the read-only migration baseline preflight",
    )
    parser.add_argument(
        "--refresh-live-provenance",
        action="store_true",
        help="explicitly query GitHub run/artifact provenance; default is fast fail-closed offline mode",
    )
    parser.add_argument(
        "--live-timeout-seconds",
        type=float,
        default=30.0,
        help="one total wall-clock budget shared by all live provenance receipts (max 60)",
    )
    parser.add_argument("--stdout", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        root = repository_root(args.root)
        output = args.output or root / DEFAULT_STATUS_RELATIVE
        if not output.is_absolute():
            output = root / output
        receipt_paths = list(args.receipt)
        for directory in args.receipt_dir:
            receipt_paths.extend(sorted(directory.glob("*.json")))
        receipt_paths = list(discover_receipt_paths(root, receipt_paths))
        receipts = [(path, _read_json(path)) for path in receipt_paths]
        source = _read_yaml(output) if output.is_file() else None
        migration_evidence = _read_json(args.migration_evidence) if args.migration_evidence else None
        raw_provenance_verifier = (
            bounded_live_provenance(args.live_timeout_seconds)
            if args.refresh_live_provenance
            else offline_provenance
        )
        provenance_cache: dict[tuple[str, str], Mapping[str, Any]] = {}

        def provenance_verifier(
            verify_root: Path,
            receipt: Mapping[str, Any],
            receipt_path: Path | None = None,
        ) -> Mapping[str, Any]:
            key = (
                str(receipt_path.resolve()) if receipt_path is not None else "inline",
                _sha256_text(
                    json.dumps(
                        receipt,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
            )
            if key not in provenance_cache:
                provenance_cache[key] = raw_provenance_verifier(
                    verify_root, receipt, receipt_path
                )
            return provenance_cache[key]

        delivered = resolve_delivered_contracts(
            root,
            receipt_paths,
            provenance_verifier=provenance_verifier,
        )
        s0_evidence = collect_s0_evidence(
            root,
            attestation_paths=receipt_paths,
            delivered_contract_ids=delivered,
            migration_baseline=migration_evidence,
        )
        payload = build_projection(
            root,
            receipts=receipts,
            source_status=source,
            provenance_verifier=provenance_verifier,
            s0_evidence=s0_evidence,
        )
        write_projection(output, payload)
        if args.stdout:
            print(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=1000), end="")
        else:
            print(f"[implementation-status] GENERATED: {output.relative_to(root).as_posix()}")
    except (ProjectionInputError, ValueError) as exc:
        print(f"[implementation-status] ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
