from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_s4_s6_ci_executes_real_checks_and_uploads_warning_issue_and_pilot_evidence() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    gate = workflow["jobs"]["convergence-foundation-gate"]
    assert gate.get("continue-on-error") is not True
    scripts = "\n".join(
        str(step.get("run", "")) for step in gate["steps"] if isinstance(step, dict)
    )
    for target in (
        "tests/test_system_graph_planned.py",
        "tests/test_system_graph_issues.py",
        "tests/test_system_graph_integration_plans.py",
        "tests/test_system_graph_integration_router.py",
        "tests/test_system_graph_mcp_registration.py",
        "tests/test_system_graph_s4_s6_completion.py",
        "tests/test_system_convergence_s6_repository_pilot.py",
        "tests/test_system_convergence_s6_vertical.py",
    ):
        assert target in scripts
    assert "scripts/system_graph.py check-contract" in scripts
    assert "--issue-root \"$RUNNER_TEMP/system-graph-issues\"" in scripts
    assert "scripts/run_system_convergence_pilots.py" in scripts
    assert "--output \"$RUNNER_TEMP/system-graph-s6-pilot.json\"" in scripts

    uploads = [
        step
        for step in gate["steps"]
        if isinstance(step, dict) and step.get("uses") == "actions/upload-artifact@v4"
    ]
    names = {step["with"]["name"] for step in uploads}
    assert any(str(name).startswith("system-graph-s4-warning-") for name in names)
    assert any(str(name).startswith("system-graph-s6-pilot-") for name in names)
    paths = "\n".join(str(step["with"].get("path", "")) for step in uploads)
    assert "system-graph-s4-warning.json" in paths
    assert "system-graph-issues/*.json" in paths
    assert "system-graph-s6-pilot.json" in paths


def test_delivery_seal_requires_the_s4_s6_convergence_gate() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    delivery = workflow["jobs"]["delivery-seal"]
    assert "convergence-foundation-gate" in delivery["needs"]
    script = "\n".join(
        str(step.get("run", "")) for step in delivery["steps"] if isinstance(step, dict)
    )
    assert '"convergence-foundation-gate": "passed"' in script
    assert "--required-check convergence-foundation-gate=passed" in script
