from datetime import datetime, timedelta, timezone

from app.services.compatibility import CompatibilityEvent, ReconciliationEvidence, evaluate_retirement_readiness, safe_metadata

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def matched(kind: str) -> ReconciliationEvidence:
    checksum = "sha256:" + "a" * 64 if kind in {"sqlite", "attachments", "settings"} else None
    return ReconciliationEvidence(kind, "matched", NOW, checksum, checksum)


def test_retirement_is_fail_closed_without_window_and_reconciliation() -> None:
    report = evaluate_retirement_readiness(client_id="omni-desktop", as_of=NOW, coverage_started_at=None, events=[], reconciliations=[])
    assert report["ready_for_r3_review"] is False
    assert report["physical_retirement_allowed"] is False
    assert {item["code"] for item in report["blockers"]} >= {"observation_window_incomplete", "sqlite_not_reconciled", "secret_reauthorization_not_reconciled"}


def test_fourteen_day_zero_exclusive_usage_can_only_make_r3_review_ready() -> None:
    report = evaluate_retirement_readiness(
        client_id="omni-desktop",
        as_of=NOW,
        coverage_started_at=NOW - timedelta(days=15),
        events=[CompatibilityEvent("omni-desktop", "chat", "host", False, NOW - timedelta(days=1))],
        reconciliations=[matched(kind) for kind in ("sqlite", "attachments", "settings", "secret_reauthorization", "host_smoke", "restore_smoke")],
    )
    assert report["ready_for_r3_review"] is True
    assert report["physical_retirement_allowed"] is False
    assert report["required_gate"].startswith("R3")
    assert report["capability_matrix"] == [
        {
            "capability_id": "chat",
            "route_families": ["host"],
            "observation_count": 1,
            "exclusive_event_count": 0,
            "last_observed_at": (NOW - timedelta(days=1)).isoformat(),
            "compatibility_state": "shared_or_canonical",
        }
    ]


def test_telemetry_metadata_drops_secret_shaped_fields() -> None:
    assert safe_metadata({"version": "1", "token": "never", "webhook_url": "never", "state": "ok"}) == {"version": "1", "state": "ok"}
