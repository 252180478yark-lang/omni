import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_s7_s14_contract_projects_every_remaining_slice_without_local_complete_claim() -> None:
    path = ROOT / "scripts/generate_implementation_status.py"
    spec = importlib.util.spec_from_file_location("implementation_status_s14", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    impact = module._read_yaml(ROOT / "docs/dev-changes/2026-08-01-system-convergence-s7-s14/impact.yaml")
    assert module._contract_slices(impact) == ("S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14")
    assert module._contract_status("GRAPH_DIFF_READY", None, schema_version=3) == "VERIFIED_NOT_DELIVERED"
    assert module._contract_status("VERIFYING", None, schema_version=3) == "IN_PROGRESS"


def test_recovered_delivery_projection_preserves_truth_boundaries() -> None:
    evidence_path = (
        ROOT
        / "docs/dev-changes/2026-08-07-prd-receipt-cache-rebuild/delivery-projection.yaml"
    )
    projection = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    expected_subjects = {
        "2026-07-30-system-convergence-s0-s3-foundation": "041f05d931967d3ab014f031e684d1b02765c684",
        "2026-08-01-system-convergence-s4-s6-static": "af11294eeadc84a45284c3265ddf623826edb1f7",
        "2026-08-01-system-convergence-s4-s6-gap-closure": "5d760f733aeb976c5b88419c5406383bf272ca86",
        "2026-08-01-system-convergence-s7-s14": "c8c8eec71d9d970272de84649cf31f87fd148441",
    }
    contracts = {item["change_id"]: item for item in projection["contracts"]}
    for change_id, subject in expected_subjects.items():
        contract = contracts[change_id]
        assert contract["effective_state"] == "COMPLETE"
        assert contract["delivery"]["valid"] is True
        assert contract["delivery"]["subject_commit"] == subject
        assert contract["delivery"]["reasons"] == []

    slices = {item["id"]: item["status"] for item in projection["slices"]}
    assert all(slices[f"S{index}"] == "COMPLETE" for index in range(4, 15))
    assert slices["S0"] == "BLOCKED"
    assert slices["S0.5"] == "BLOCKED"
    assert projection["projection_errors"] == []
    assert projection["audit_snapshot"]["s0_evidence"]["migration_baseline"]["status"] == "unknown"
    assert projection["audit_snapshot"]["hook_trust"]["status"] == "review_required"
    assert projection["runtime_observation"] == {
        "status": "unknown",
        "reason": "not_collected_by_delivery_projection",
    }
    assert projection["projection_policy"]["delivery_does_not_imply_runtime_health"] is True
