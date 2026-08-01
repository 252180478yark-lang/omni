import importlib.util
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("client_retirement_audit", ROOT / "scripts/client_retirement_audit.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_ready_fixture_still_requires_explicit_r3_gate() -> None:
    import json
    value = json.loads((ROOT / "tests/fixtures/client-retirement/ready.json").read_text(encoding="utf-8"))
    report = MODULE.audit(value, as_of=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert report["ready_for_r3_review"] is True
    assert report["physical_retirement_allowed"] is False


def test_blocked_fixture_reports_window_usage_and_reconciliation() -> None:
    import json
    value = json.loads((ROOT / "tests/fixtures/client-retirement/blocked.json").read_text(encoding="utf-8"))
    report = MODULE.audit(value, as_of=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert report["ready_for_r3_review"] is False
    assert {"observation_window_incomplete", "exclusive_usage_observed", "sqlite_not_reconciled"} <= set(report["blockers"])

