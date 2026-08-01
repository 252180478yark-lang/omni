import importlib.util
import sys
from pathlib import Path

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
