from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "knowledge-engine"))


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


allocation = _load_module("s6_vertical_allocation", ROOT / "scripts" / "runtime_allocation.py")
contract_helpers = _load_module("s6_vertical_contract_helpers", ROOT / "tests" / "test_feature_contracts.py")


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(args, cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


def _runtime_manifest(repo: Path) -> None:
    (repo / "config").mkdir()
    (repo / "config" / "runtime-manifest.yaml").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "canonical_runtime": {
                    "runtime_id": "omni-main",
                    "compose_project": "omni",
                    "database": "omni_vibe_db",
                },
                "services": {
                    "postgres": {"published_ports": [5432]},
                    "redis": {"published_ports": [6379]},
                    "knowledge-engine": {"published_ports": [8002]},
                    "frontend": {"published_ports": [3000]},
                },
            }
        ),
        encoding="utf-8",
    )
    _run(repo, "git", "add", "config/runtime-manifest.yaml")
    _run(repo, "git", "commit", "-qm", "add runtime manifest")


def _commit_candidate(repo: Path, *, change_id: str, relative_path: str, risk_level: str) -> tuple[str, dict[str, object]]:
    base = _run(repo, "git", "rev-parse", "HEAD")
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"# isolated {change_id}\nVALUE = 1\n", encoding="utf-8")
    pair = contract_helpers._write_complete_contract(
        repo,
        change_id,
        [relative_path],
        actual_paths=[relative_path],
        state="GRAPH_DIFF_READY",
        schema_version=3,
        base_commit=base,
        risk_level=risk_level,
    )
    _run(repo, "git", "add", "--", relative_path, *pair)
    _run(repo, "git", "commit", "-qm", f"fixture {change_id}")
    head = _run(repo, "git", "rev-parse", "HEAD")
    changed = contract_helpers.gate.git_changed_files(repo, base, head)
    report = contract_helpers.gate.check_feature_contracts(
        repo,
        changed,
        validator=contract_helpers.dc,
        head_ref=head,
        evaluation_ref=head,
        validation_mode="commit",
        base_ref=base,
    )
    assert report.errors == ()
    receipt = contract_helpers.gate.build_delivery_attestation(
        repo,
        report,
        head,
        attestor="fixture-github-actions",
        run_id="6102",
        repository="fixture/repo",
        required_checks={"contract": "passed", "tests": "success"},
        evidence_artifact_name=f"fixture-evidence-{head}",
        evidence_artifact_digest="sha256:" + "c" * 64,
    )
    return head, receipt


def test_s6_isolated_r1_r2_vertical_records_receipt_transcript_and_release(tmp_path: Path) -> None:
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    contract_helpers._initialize_git_repo(repo)
    _runtime_manifest(repo)
    state_dir = tmp_path / "runtime-state"
    receipt_root = tmp_path / "fixture-receipts"
    transcript: list[dict[str, object]] = []

    for change_id, relative_path, risk_level in (
        ("s6-r1", "services/r1/app.py", "R1"),
        ("s6-r2", "frontend/src/r2/page.ts", "R2"),
    ):
        allocated = allocation.acquire(
            repo,
            change_id=change_id,
            owner="s6-fixture",
            path_globs=[relative_path],
            risk_level=risk_level,
            state_dir=state_dir,
        )
        runtime = allocated["allocation"]
        assert runtime["canonical"] is False
        assert runtime["cron_owner"] is False
        assert runtime["database"] != "omni_vibe_db"
        assert allocated["environment"]["OMNI_SCHEDULER_ENABLED"] == "false"

        head, receipt = _commit_candidate(
            repo, change_id=change_id, relative_path=relative_path, risk_level=risk_level
        )
        receipt_path = receipt_root / f"{change_id}-{head}.json"
        contract_helpers.gate.write_delivery_attestation(receipt_path, receipt)
        assert receipt_path.is_file()
        transcript.append(
            {
                "change_id": change_id,
                "states": ["DISCOVERED", "IMPACT_LOCKED", "IMPLEMENTING", "VERIFYING", "GRAPH_DIFF_READY"],
                "allocation_id": runtime["allocation_id"],
                "canonical": runtime["canonical"],
                "fixture_ci_attestation": receipt_path.name,
                "delivery_status": "external_ci_pending",
            }
        )
        released = allocation.release(
            repo,
            runtime["allocation_id"],
            owner="s6-fixture",
            expected_revision=runtime["revision"],
            state_dir=state_dir,
        )
        assert released["state"] == "released"

    from app.services.system_graph.pilot import r3_pending_fixture

    r3 = r3_pending_fixture(request_id="r3-fixture-1", target="external:fixture", payload_hash="sha256:fixture")
    transcript.append(
        {
            "change_id": "s6-r3-fixture",
            "states": ["DISCOVERED", "WAITING_APPROVAL"],
            "effect_executed": r3.effect_executed,
            "delivery_status": "r3_gate_pending",
        }
    )
    transcript_path = tmp_path / "s6-vertical-transcript.json"
    transcript_path.write_text(json.dumps(transcript, indent=2) + "\n", encoding="utf-8")
    assert json.loads(transcript_path.read_text(encoding="utf-8"))[2]["effect_executed"] is False
    assert all(item["delivery_status"] != "COMPLETE" for item in transcript)
