from __future__ import annotations

from pathlib import Path

from app.services.migration_baseline import build_baseline_report, resolve_p0_repository_root


def test_baseline_is_ready_for_matching_checksum_ledgers() -> None:
    report = build_baseline_report(
        repo_migration_entries=[
            {"filename": "001_initial.sql", "sha256": "one"},
            {"filename": "002_pipeline.sql", "sha256": "two"},
        ],
        runtime_migration_entries=[
            {"filename": "001_initial.sql"},
            {"filename": "002_pipeline.sql"},
        ],
        tracking_has_checksums=True,
    )

    assert report["status"] == "ready"
    assert report["production_entity_changes_allowed"] is True
    assert report["blockers"] == []


def test_baseline_fails_closed_for_missing_runtime_migrations_and_duplicate_numbers() -> None:
    report = build_baseline_report(
        repo_migration_entries=[
            {"filename": "001_initial.sql", "sha256": "one"},
            {"filename": "069_current.sql", "sha256": "sixty-nine"},
        ],
        runtime_migration_entries=[
            {"filename": "001_initial.sql"},
            {"filename": "070_branch_a.sql"},
            {"filename": "070_branch_b.sql"},
        ],
        tracking_has_checksums=False,
        candidate_sources={
            "001_initial.sql": "not-a-runtime-only-candidate",
            "070_branch_a.sql": "recoverable-commit",
        },
    )

    assert report["status"] == "blocked"
    assert report["production_entity_changes_allowed"] is False
    assert report["reconciliation"]["runtime_only"] == [
        "070_branch_a.sql",
        "070_branch_b.sql",
    ]
    assert report["reconciliation"]["runtime_only_candidate_sources"] == {
        "070_branch_a.sql": "recoverable-commit"
    }
    blocker_codes = {item["code"] for item in report["blockers"]}
    assert blocker_codes == {
        "runtime_duplicate_numeric_prefix",
        "runtime_migration_checksums_unavailable",
        "runtime_migration_missing_from_repository",
        "repository_migration_missing_from_runtime_ledger",
    }


def test_p0_scope_ignores_only_manifested_frozen_runtime_tracks() -> None:
    report = build_baseline_report(
        repo_migration_entries=[
            {"filename": "070_planting.sql", "sha256": "planting"},
        ],
        runtime_migration_entries=[
            {"filename": "070_planting.sql", "checksum": "planting"},
            {"filename": "070_ai_insert.sql", "checksum": None},
        ],
        tracking_has_checksums=True,
        frozen_runtime_filenames=["070_ai_insert.sql"],
    )

    assert report["status"] == "ready"
    assert report["reconciliation"]["frozen_runtime_migrations"] == [
        "070_ai_insert.sql"
    ]


def test_p0_scope_freezes_the_legacy_ecommerce_091_092_rows() -> None:
    report = build_baseline_report(
        repo_migration_entries=[
            {"filename": "091_p0_execution_vector_match.sql", "sha256": "p0-091"},
            {"filename": "092_p0_content_spec_reuse_scope.sql", "sha256": "p0-092"},
        ],
        runtime_migration_entries=[
            {"filename": "091_p0_execution_vector_match.sql", "checksum": "p0-091"},
            {"filename": "091_ecommerce_visual_prototype_gate.sql", "checksum": "legacy-091"},
            {"filename": "092_p0_content_spec_reuse_scope.sql", "checksum": "p0-092"},
            {"filename": "092_ecommerce_visual_prototype_runtime_contract.sql", "checksum": "legacy-092"},
        ],
        tracking_has_checksums=True,
        frozen_runtime_filenames=[
            "091_ecommerce_visual_prototype_gate.sql",
            "092_ecommerce_visual_prototype_runtime_contract.sql",
        ],
    )

    assert report["status"] == "ready"
    assert report["reconciliation"]["frozen_runtime_migrations"] == [
        "091_ecommerce_visual_prototype_gate.sql",
        "092_ecommerce_visual_prototype_runtime_contract.sql",
    ]


def test_baseline_blocks_untracked_canonical_sources() -> None:
    report = build_baseline_report(
        repo_migration_entries=[{"filename": "001_initial.sql", "sha256": "one"}],
        runtime_migration_entries=[{"filename": "001_initial.sql", "checksum": "one"}],
        tracking_has_checksums=True,
        git={"untracked_paths": ["migrations/001_initial.sql"]},
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == [
        {
            "code": "canonical_source_untracked",
            "detail": ["migrations/001_initial.sql"],
        }
    ]


def test_repository_root_prefers_configured_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "omni"
    (root / "migrations").mkdir(parents=True)
    (root / "services" / "knowledge-engine" / "config").mkdir(parents=True)
    anchor = root / "services" / "knowledge-engine" / "scripts" / "probe.py"
    anchor.parent.mkdir(parents=True)
    anchor.touch()

    monkeypatch.setenv("P0_REPOSITORY_ROOT", str(root))

    assert resolve_p0_repository_root(anchor) == root
