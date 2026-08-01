from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_ci_has_blocking_empty_and_existing_database_migration_parity_gate() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    gate = jobs["migration-parity-gate"]
    assert gate.get("continue-on-error") is not True
    assert gate["services"]["postgres"]["image"].startswith("pgvector/")
    script = "\n".join(
        str(step.get("run", "")) for step in gate["steps"] if isinstance(step, dict)
    )
    assert "tests/test_migration_runner_contract.py" in script
    assert "scripts/apply_migrations.py --dry-run --verify" in script
    assert "omni_ci_empty" in script
    assert "omni_ci_existing" in script
    assert "016_mcp_audit.sql" in script
    assert script.count("scripts/apply_migrations.py --allocation-aware") >= 3
    assert "ledger == repository" in script


def test_delivery_attestation_requires_migration_gate_and_content_addressed_evidence() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    delivery = workflow["jobs"]["delivery-seal"]
    assert "migration-parity-gate" in delivery["needs"]
    attestation = next(
        step
        for step in delivery["steps"]
        if isinstance(step, dict) and step.get("name") == "生成 CI 外部 delivery attestation"
    )
    assert attestation["env"]["EVIDENCE_DIGEST"] == (
        "sha256:${{ steps.evidence.outputs.artifact-digest }}"
    )
    script = "\n".join(
        str(step.get("run", ""))
        for step in delivery["steps"]
        if isinstance(step, dict)
    )
    assert "--migration-gate-verified" in script
    assert "--required-check migration-parity-gate=passed" in script
    assert script.count('--evidence-artifact-digest "$EVIDENCE_DIGEST"') == 1
    evidence_upload = next(
        step
        for step in delivery["steps"]
        if isinstance(step, dict) and step.get("id") == "evidence"
    )
    assert evidence_upload["uses"] == "actions/upload-artifact@v4"


def test_delivery_attestation_blocks_on_executed_convergence_foundation_tests() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    gate = jobs["convergence-foundation-gate"]
    assert gate.get("continue-on-error") is not True
    assert gate["runs-on"] == "ubuntu-latest"
    assert "services" not in gate
    assert gate["env"] == {"PYTHONDONTWRITEBYTECODE": "1", "APP_ENV": "test"}
    script = "\n".join(
        str(step.get("run", "")) for step in gate["steps"] if isinstance(step, dict)
    )
    assert 'pip install -e "services/knowledge-engine[dev]"' in script
    assert '-e "services/identity-service[dev]"' in script
    for target in (
        "tests/test_development_policy.py",
        "tests/test_development_hooks.py",
        "tests/test_system_health.py",
        "tests/test_system_health_router.py",
        "tests/test_approval_operations.py",
        "tests/test_approval_operation_worker.py",
        "tests/test_approval_audit.py",
        "tests/test_feature_definitions.py",
        "tests/test_system_graph_models.py",
        "tests/test_system_graph_collectors.py",
        "tests/test_system_graph_snapshots.py",
        "tests/test_system_graph_redaction.py",
        "tests/test_runtime_preflight.py",
        "tests/test_auth.py",
    ):
        assert target in script
    assert "--collect-only" not in script
    assert "test_router_human_gates.py" not in script
    assert "DATABASE_URL" not in script
    assert "OMNI_APPROVAL_SERVICE_SECRET" not in script

    delivery = jobs["delivery-seal"]
    assert "convergence-foundation-gate" in delivery["needs"]
    delivery_script = "\n".join(
        str(step.get("run", ""))
        for step in delivery["steps"]
        if isinstance(step, dict)
    )
    assert '"convergence-foundation-gate": "passed"' in delivery_script
    assert "--required-check convergence-foundation-gate=passed" in delivery_script
