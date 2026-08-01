#!/usr/bin/env python3
"""Run S6 pilots against this checkout and emit a local evidence transcript."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "knowledge-engine"
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.approval_operations import (  # noqa: E402
    ApprovalOperationCreate,
    ApprovalOperationState,
    IdempotencyStrategy,
)
from app.services.approval_operations import (  # noqa: E402
    ApprovalOperationService,
    ApprovalPrincipal,
    InMemoryApprovalRepository,
)
from app.services.system_graph.pilot import (  # noqa: E402
    PilotManifest,
    RepositoryPilot,
    validate_repository_paths,
)
from runtime_allocation import acquire, release  # noqa: E402


DEFAULT_MANIFEST = SERVICE_ROOT / "config" / "system_graph" / "pilots.yaml"


def load_manifest(path: Path) -> PilotManifest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PilotManifest.model_validate(payload)


def _source_commit(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


def _run_commands(root: Path, pilot: RepositoryPilot) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for command in pilot.commands:
        argv = [sys.executable if index == 0 and value == "python" else value for index, value in enumerate(command.argv)]
        working_directory = root if command.working_directory == "." else root / command.working_directory
        completed = subprocess.run(argv, cwd=working_directory, check=True, text=True, capture_output=True)
        combined = (completed.stdout + completed.stderr).strip()
        evidence.append(
            {
                "working_directory": command.working_directory,
                "argv": command.argv,
                "returncode": completed.returncode,
                "output_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
                "output_tail": combined.splitlines()[-1] if combined else "",
            }
        )
    return evidence


async def _r3_pending(pilot: RepositoryPilot, source_commit: str) -> dict[str, Any]:
    repository = InMemoryApprovalRepository()
    principal = ApprovalPrincipal(
        "system:s6-pilot",
        scopes=frozenset({"approval:request"}),
        verifier_version="s6-pilot-v1",
    )
    service = ApprovalOperationService(repository, principal=principal)
    accepted = await service.create(
        ApprovalOperationCreate(
            request_id=f"{pilot.pilot_id}-{source_commit[:12]}",
            requested_by=principal.principal_id,
            permission_snapshot={"roles": [], "scopes": ["approval:request"]},
            trace_id=f"s6-{source_commit[:12]}",
            handler=pilot.approval_handler,
            summary="S6 inert approval pilot; no effect handler is registered",
            payload={"candidate_commit": source_commit, "effect_mode": "disabled"},
            target={"ref": pilot.approval_target},
            idempotency_strategy=IdempotencyStrategy.MANUAL_RECONCILIATION,
            expires_in_seconds=300,
        )
    )
    record = await repository.get(accepted.operation_id)
    if record is None or record.state is not ApprovalOperationState.PENDING:
        raise RuntimeError("R3 pilot did not persist a pending approval operation")
    if record.effect_started_at is not None or record.result is not None:
        raise RuntimeError("R3 pilot unexpectedly crossed the effect boundary")
    return {
        "pilot_id": pilot.pilot_id,
        "risk_level": pilot.risk_level,
        "candidate_paths": list(validate_repository_paths(ROOT, pilot)),
        "state": "waiting_approval",
        "approval_operation_id": accepted.operation_id,
        "approval_state": accepted.state.value,
        "effect_handler_registered": False,
        "effect_executed": False,
        "delivery_status": "r3_gate_pending",
    }


async def run_pilots(
    *,
    root: Path,
    manifest_path: Path,
    state_dir: Path,
    run_commands: bool,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    source_commit = _source_commit(root)
    results: list[dict[str, Any]] = []
    state_dir.mkdir(parents=True, exist_ok=True)

    for pilot in manifest.pilots:
        verified_paths = list(validate_repository_paths(root, pilot))
        if pilot.risk_level == "R3":
            results.append(await _r3_pending(pilot, source_commit))
            continue

        allocated = acquire(
            root,
            change_id=pilot.pilot_id,
            owner="system-convergence-s6-pilot",
            path_globs=pilot.allocation_paths,
            risk_level=pilot.risk_level,
            state_dir=state_dir,
        )
        runtime = allocated["allocation"]
        released = False
        try:
            command_evidence = _run_commands(root, pilot) if run_commands else []
        finally:
            released_record = release(
                root,
                runtime["allocation_id"],
                owner="system-convergence-s6-pilot",
                expected_revision=runtime["revision"],
                state_dir=state_dir,
            )
            released = released_record["state"] == "released"
        results.append(
            {
                "pilot_id": pilot.pilot_id,
                "risk_level": pilot.risk_level,
                "candidate_paths": verified_paths,
                "selected_block_codes": sorted(pilot.selected_block_codes),
                "state": "graph_diff_ready",
                "runtime_allocation": {
                    "allocation_id": runtime["allocation_id"],
                    "canonical": runtime["canonical"],
                    "scheduler_owner": runtime["cron_owner"],
                    "approval_worker_owner": runtime["approval_worker_owner"],
                    "database": runtime["database"],
                    "released": released,
                },
                "verification_commands_executed": run_commands,
                "verification": command_evidence,
                "effect_executed": False,
                "delivery_status": "external_ci_pending",
            }
        )

    return {
        "schema_version": 1,
        "source_commit": source_commit,
        "manifest": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "pilots": results,
        "summary": {
            "risk_levels": [result["risk_level"] for result in results],
            "all_candidate_paths_verified": True,
            "all_effects_disabled": all(not result["effect_executed"] for result in results),
            "delivery_status": "external_ci_pending",
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--skip-commands", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = args.manifest.resolve()
    if args.state_dir is None:
        with tempfile.TemporaryDirectory(prefix="omni-s6-pilot-") as temporary:
            transcript = asyncio.run(
                run_pilots(
                    root=ROOT,
                    manifest_path=manifest,
                    state_dir=Path(temporary),
                    run_commands=not args.skip_commands,
                )
            )
    else:
        transcript = asyncio.run(
            run_pilots(
                root=ROOT,
                manifest_path=manifest,
                state_dir=args.state_dir.resolve(),
                run_commands=not args.skip_commands,
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(transcript, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(transcript["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
