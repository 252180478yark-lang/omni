import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_policy_contains_all_deterministic_p0_codes_and_keeps_unknown_warning() -> None:
    gate = _module("feature_contract_gate_s14", ROOT / "scripts/check_feature_contracts.py")
    assert gate.validate_repository_block_policy(ROOT) == ()
    policy = yaml.safe_load((ROOT / "services/knowledge-engine/config/system_graph/block-policy.yaml").read_text(encoding="utf-8"))
    assert set(policy["deterministic_p0_codes"]) == set(gate.REQUIRED_DETERMINISTIC_P0_CODES)
    assert policy["unknown_behavior"] == "warning"


def test_health_baseline_generation_is_deterministic_and_does_not_invent_runtime(tmp_path: Path) -> None:
    generator = _module("fde_health_baseline", ROOT / "scripts/generate_fde_health_baseline.py")
    snapshot = {"snapshot_id": "sha256:" + "a" * 64, "content": {"nodes": [{"id": "one"}], "edges": [], "source_results": [{"collector_id": "runtime", "status": "unknown"}], "diagnostics": []}}
    policy = yaml.safe_load((ROOT / "services/knowledge-engine/config/system_graph/block-policy.yaml").read_text(encoding="utf-8"))
    first = generator.build_baseline(snapshot, policy)
    second = generator.build_baseline(snapshot, policy)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["trace"] == {"status": "unknown", "event_count": None, "reason_code": "runtime_evidence_not_supplied"}
    assert first["graph"]["status"] == "partial"
