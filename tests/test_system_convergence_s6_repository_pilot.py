from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_s6_pilots_use_real_repository_paths_isolated_allocations_and_pending_r3(tmp_path: Path) -> None:
    output = tmp_path / "s6-repository-pilots.json"
    state_dir = tmp_path / "runtime-state"
    subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/run_system_convergence_pilots.py",
            "--output",
            str(output),
            "--state-dir",
            str(state_dir),
            "--skip-commands",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    transcript = json.loads(output.read_text(encoding="utf-8"))

    assert transcript["summary"] == {
        "risk_levels": ["R1", "R2", "R3"],
        "all_candidate_paths_verified": True,
        "all_effects_disabled": True,
        "delivery_status": "external_ci_pending",
    }
    by_risk = {pilot["risk_level"]: pilot for pilot in transcript["pilots"]}
    for risk in ("R1", "R2"):
        runtime = by_risk[risk]["runtime_allocation"]
        assert runtime["canonical"] is False
        assert runtime["scheduler_owner"] is False
        assert runtime["released"] is True
        assert runtime["database"] != "omni_vibe_db"
        assert by_risk[risk]["delivery_status"] == "external_ci_pending"
        assert all((ROOT / path).exists() for path in by_risk[risk]["candidate_paths"])

    r3 = by_risk["R3"]
    assert r3["approval_state"] == "pending"
    assert r3["state"] == "waiting_approval"
    assert r3["effect_handler_registered"] is False
    assert r3["effect_executed"] is False
    assert r3["delivery_status"] == "r3_gate_pending"

    allocation_state = json.loads((state_dir / "allocations.json").read_text(encoding="utf-8"))
    assert {item["state"] for item in allocation_state["allocations"]} == {"released"}
