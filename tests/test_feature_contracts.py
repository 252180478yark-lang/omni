from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_module("omni_feature_contract_gate", ROOT / "scripts" / "check_feature_contracts.py")
dc = _load_module(
    "omni_feature_contract_validator_for_gate_tests",
    ROOT
    / ".agents"
    / "skills"
    / "omni-feature-development"
    / "scripts"
    / "dev_contract.py",
)


def _write_complete_contract(
    repo: Path,
    change_id: str,
    planned_paths: list[str],
    *,
    allowed_paths: list[str] | None = None,
    state: str = "COMPLETE",
    embedded_change_id: str | None = None,
    actual_paths: list[str] | None = None,
    schema_version: int = 2,
    base_commit: str | None = None,
    risk_level: str = "R1",
) -> list[str]:
    contract_change_id = embedded_change_id or change_id
    impact = dc.impact_template(contract_change_id, f"Contract {change_id}")
    impact["schema_version"] = schema_version
    if schema_version in {2, 3}:
        impact["feature_refs"] = [
            {
                "feature_id": change_id,
                "feature_ref": f"prd:{change_id}#FR-001",
            }
        ]
        impact["before_snapshot"] = {"ref": "before"}
    if schema_version == 1:
        impact.pop("feature_refs", None)
        impact.pop("before_snapshot", None)
    elif schema_version == 3:
        impact["delivery"] = {
            "authority": "ci_attestation",
            "base_commit": base_commit or ("a" * 40),
        }
        impact["risk"] = {
            "level": risk_level,
            "reasons": ["The candidate changes protected repository behavior."],
            "external_effects": ["External irreversible effect."] if risk_level == "R3" else [],
            "approval": {
                "required": risk_level == "R3",
                "gate_ref": "human-gate:test-approval" if risk_level == "R3" else "",
            },
        }
    impact["state"] = state
    impact["intent"] = {
        "problem": "Prevent uncontracted cross-layer changes.",
        "expected_outcome": "Every protected file is declared and verified.",
        "user_visible_behavior": [],
    }
    impact["current_chain"] = {
        "nodes": ["service:contract-gate"],
        "edges": [],
        "evidence": ["scripts/check_feature_contracts.py:check_feature_contracts"],
    }
    impact["scope"]["services"] = ["service:contract-gate"]
    impact["planned_changes"] = [
        {
            "id": "CHG-001",
            "action": "modify",
            "kind": "service",
            "node_id": "service:contract-gate",
            "paths": planned_paths,
            "upstream": ["ci:feature-contract-gate"],
            "downstream": [],
            "contract_change": "compatible",
            "verification_ids": ["VER-001"],
        }
    ]
    impact["allowed_unplanned_paths"] = allowed_paths or []
    impact["compatibility"] = {
        "api": {"status": "not_applicable", "strategy": "No API change."},
        "database": {"status": "not_applicable", "strategy": "No database change."},
        "workflow": {"status": "compatible", "strategy": "Existing states remain valid."},
        "data_source": {"status": "not_applicable", "strategy": "No source change."},
    }
    impact["graph_acceptance"] = {
        "required_edges": [
            {
                "from": "ci:feature-contract-gate",
                "to": "service:contract-gate",
                "relation": "calls",
            }
        ],
        "allowed_unknowns": [],
        "forbidden_orphans": ["service:contract-gate"],
    }
    impact["out_of_scope"] = ["Runtime product behavior."]
    impact["rollback"] = {
        "strategy": "Revert the protected files.",
        "data_recovery": "No persistent data changes.",
    }
    impact["verification_plan"] = [
        {
            "id": "VER-001",
            "layer": "policy",
            "command": "python -m pytest tests/test_feature_contracts.py",
            "proves": "The feature-contract gate is deterministic.",
            "required": True,
        }
    ]
    impact["lock"] = {
        "locked_at": "2026-07-28T00:00:00Z",
        "locked_by": "codex",
        "rationale": "Scope reviewed against the changed boundaries.",
    }

    def sample_path(pattern: str) -> str:
        return "/".join(
            "example.py" if segment == "**" else segment.replace("*", "example").replace("?", "x")
            for segment in pattern.split("/")
        )

    completion_paths = actual_paths or [
        *(sample_path(pattern) for pattern in planned_paths),
        *(sample_path(pattern) for pattern in (allowed_paths or [])),
    ]
    completion = dc.completion_template(contract_change_id)
    completion["schema_version"] = schema_version
    completion["state"] = state
    if schema_version == 3 and dc.state_at_least(state, "GRAPH_DIFF_READY"):
        completion["delivery"] = {"status": "ready_for_ci"}
    completion["actual_changes"] = [
        {
            "id": "ACT-001",
            "planned_change_id": "CHG-001",
            "paths": completion_paths,
            "summary": "Implemented the declared protected changes.",
        }
    ]
    completion["verification_results"] = [
        {
            "id": "VER-001",
            "command": "python -m pytest tests/test_feature_contracts.py",
            "status": "passed",
            "exit_code": 0,
            "evidence": "Feature-contract tests passed.",
        }
    ]
    completion["graph_diff"].update(
        {
            "status": "clean",
            "snapshot_before": "before",
            "snapshot_after": "after",
            "required_edges": [
                {
                    "from": "ci:feature-contract-gate",
                    "to": "service:contract-gate",
                    "relation": "calls",
                    "status": "present",
                    "evidence": "CI workflow invokes the gate.",
                }
            ],
        }
    )
    completion["rollback"] = {"verified": True, "evidence": "Revert path reviewed."}
    if schema_version != 3:
        completion["final"] = {
            "status": "complete",
            "completed_at": "2026-07-28T00:00:00Z",
            "completed_by": "codex",
            "summary": "Protected changes are contract-covered.",
        }

    directory = repo / "docs" / "dev-changes" / change_id
    directory.mkdir(parents=True, exist_ok=True)
    dc.write_yaml(directory / "impact.yaml", impact)
    dc.write_yaml(directory / "completion.yaml", completion)
    return [
        f"docs/dev-changes/{change_id}/impact.yaml",
        f"docs/dev-changes/{change_id}/completion.yaml",
    ]


def _initialize_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)


def _commit_file(repo: Path, relative_path: str, contents: str = "VALUE = 1\n") -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "add", relative_path], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", f"add {relative_path}"], cwd=repo, check=True)


@pytest.mark.parametrize(
    "path",
    [
        "docs/design.md",
        "README.md",
        "tests/test_example.py",
        "frontend/tests/example.test.ts",
        "services/example/__tests__/example.ts",
        "scripts/test_probe.py",
    ],
)
def test_docs_and_tests_are_exempt(path: str) -> None:
    assert gate.requires_feature_contract(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        ".github/workflows/ci.yml",
        ".codex/hooks.json",
        ".agents/skills/example/SKILL.md",
        "scripts/tool.py",
        "frontend/src/app/page.tsx",
        "services/example/app.py",
        "pyproject.toml",
    ],
)
def test_product_and_infrastructure_paths_are_protected(path: str) -> None:
    assert gate.requires_feature_contract(path) is True


def test_docs_and_tests_only_diff_skips_without_a_contract(tmp_path: Path) -> None:
    report = gate.check_feature_contracts(
        tmp_path,
        ["docs/guide.md", "tests/test_guide.py", "frontend/tests/guide.spec.ts"],
        validator=dc,
    )

    assert report.skipped is True
    assert report.errors == ()


def test_contract_only_diff_cannot_change_just_one_side(tmp_path: Path) -> None:
    pair = _write_complete_contract(tmp_path, "feature-one", ["services/example/**"])

    report = gate.check_feature_contracts(tmp_path, [pair[0]], validator=dc)

    assert report.skipped is False
    assert any("contract pair is incomplete" in error for error in report.errors)
    assert any("completion.yaml" in error for error in report.errors)


def test_contract_only_pair_still_requires_complete_strict_state(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        state="DISCOVERED",
    )

    report = gate.check_feature_contracts(tmp_path, pair, validator=dc)

    assert report.skipped is False
    assert any("expected state COMPLETE" in error for error in report.errors)


def test_complete_contract_only_pair_is_validated_not_skipped(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/example.py")
    pair = _write_complete_contract(tmp_path, "feature-one", ["services/example/**"])

    report = gate.check_feature_contracts(tmp_path, pair, validator=dc)

    assert report.skipped is False
    assert report.errors == ()
    assert report.valid_contract_ids == ("feature-one",)


def test_gate_accepts_legacy_v1_and_new_v2_complete_contracts(tmp_path: Path) -> None:
    v1 = _write_complete_contract(
        tmp_path,
        "feature-v1",
        ["services/v1/**"],
        actual_paths=["services/v1/app.py"],
        schema_version=1,
    )
    v2 = _write_complete_contract(
        tmp_path,
        "feature-v2",
        ["services/v2/**"],
        actual_paths=["services/v2/app.py"],
        schema_version=2,
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/v1/app.py", "services/v2/app.py", *v1, *v2],
        validator=dc,
    )

    assert report.errors == ()
    assert report.valid_contract_ids == ("feature-v1", "feature-v2")


def test_gate_rejects_changed_v2_contract_without_identity(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-v2",
        ["services/v2/**"],
        actual_paths=["services/v2/app.py"],
    )
    impact_path = tmp_path / pair[0]
    impact = dc.read_yaml(impact_path)
    impact["feature_refs"] = []
    impact["before_snapshot"] = {"ref": ""}
    dc.write_yaml(impact_path, impact)

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/v2/app.py", *pair],
        validator=dc,
    )

    assert any("feature_refs must contain" in error for error in report.errors)
    assert any("before_snapshot.ref" in error for error in report.errors)


def test_protected_change_without_changed_contract_fails(tmp_path: Path) -> None:
    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py"],
        validator=dc,
    )

    assert any("require impact.yaml and completion.yaml" in error for error in report.errors)
    assert any("outside changed contract scope" in error for error in report.errors)


def test_both_contract_files_must_be_in_the_same_diff(tmp_path: Path) -> None:
    pair = _write_complete_contract(tmp_path, "feature-one", ["services/example/**"])
    changed = ["services/example/app.py", pair[0]]

    report = gate.check_feature_contracts(tmp_path, changed, validator=dc)

    assert any("contract pair is incomplete" in error for error in report.errors)
    assert any("completion.yaml" in error for error in report.errors)


def test_changed_contract_must_be_complete_and_strict(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        state="DISCOVERED",
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py", *pair],
        validator=dc,
    )

    assert any("expected state COMPLETE" in error for error in report.errors)
    assert any("strict validation requires COMPLETE" in error for error in report.errors)


def test_all_changed_contracts_are_validated(tmp_path: Path) -> None:
    valid = _write_complete_contract(
        tmp_path, "feature-one", ["services/**"], actual_paths=["services/example.py"]
    )
    incomplete = _write_complete_contract(
        tmp_path,
        "feature-two",
        ["frontend/**"],
        state="DISCOVERED",
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example.py", *valid, *incomplete],
        validator=dc,
    )

    assert report.valid_contract_ids == ("feature-one",)
    assert any(error.startswith("[feature-two]") for error in report.errors)


def test_multiple_changed_contracts_union_their_path_coverage(tmp_path: Path) -> None:
    first = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["frontend/src/**"],
        actual_paths=["frontend/src/app/page.tsx"],
    )
    second = _write_complete_contract(
        tmp_path,
        "feature-two",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        [
            "frontend/src/app/page.tsx",
            "services/example/app.py",
            "tests/test_example.py",
            *first,
            *second,
        ],
        validator=dc,
    )

    assert report.errors == ()
    assert report.valid_contract_ids == ("feature-one", "feature-two")


def test_uncovered_protected_file_fails_union_coverage(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["frontend/**"],
        actual_paths=["frontend/src/page.tsx"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["frontend/src/page.tsx", "services/undeclared.py", *pair],
        validator=dc,
    )

    assert "protected changed file is outside changed contract scope: services/undeclared.py" in report.errors
    assert (
        "protected changed file is missing from completion.actual_changes: services/undeclared.py"
        in report.errors
    )


def test_allowed_unplanned_paths_participate_in_union_coverage(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["scripts/declared.py"],
        allowed_paths=[".github/workflows/*.yml"],
        actual_paths=["scripts/declared.py", ".github/workflows/ci.yml"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["scripts/declared.py", ".github/workflows/ci.yml", *pair],
        validator=dc,
    )

    assert report.errors == ()


def test_protected_diff_and_completion_actual_paths_are_bidirectional(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        actual_paths=["services/example/other.py"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py", *pair],
        validator=dc,
    )

    assert (
        "protected changed file is missing from completion.actual_changes: services/example/app.py"
        in report.errors
    )
    assert (
        "completion.actual_changes path is neither in the current diff nor tracked "
        "at evaluation head HEAD: services/example/other.py"
        in report.errors
    )


def test_head_tracked_archival_actual_path_is_allowed_with_current_protected_diff(
    tmp_path: Path,
) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/archived.py")
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/current.py", "services/example/archived.py"],
        actual_paths=["services/example/current.py", "services/example/archived.py"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/current.py", *pair],
        validator=dc,
    )

    assert report.errors == ()


def test_untracked_archival_actual_path_cannot_bypass_current_diff_check(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    untracked = tmp_path / "services" / "example" / "untracked.py"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("VALUE = 1\n", encoding="utf-8")
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/current.py", "services/example/untracked.py"],
        actual_paths=["services/example/current.py", "services/example/untracked.py"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/current.py", *pair],
        validator=dc,
    )

    assert (
        "completion.actual_changes path is neither in the current diff nor tracked "
        "at evaluation head HEAD: services/example/untracked.py"
        in report.errors
    )


def test_contract_only_pair_rejects_actual_path_absent_from_evaluation_head(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    pair = _write_complete_contract(tmp_path, "feature-one", ["services/example/**"])

    report = gate.check_feature_contracts(tmp_path, pair, validator=dc)

    assert (
        "completion.actual_changes path is neither in the current diff nor tracked "
        "at evaluation head HEAD: services/example/example.py"
        in report.errors
    )


def test_gate_uses_explicit_evaluation_head_not_local_head(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    _commit_file(tmp_path, "services/example/archived.py")
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/current.py", "services/example/archived.py"],
        actual_paths=["services/example/current.py", "services/example/archived.py"],
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/current.py", *pair],
        validator=dc,
        head_ref=base,
    )

    assert (
        "completion.actual_changes path is neither in the current diff nor tracked "
        f"at evaluation head {base}: services/example/archived.py"
        in report.errors
    )


def test_index_evaluation_rejects_staged_contract_deletion_despite_worktree_copy(
    tmp_path: Path,
) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/app.py")
    pair = _write_complete_contract(tmp_path, "feature-one", ["services/example/**"])
    subprocess.run(["git", "add", "--", *pair], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add contract"], cwd=tmp_path, check=True)
    subprocess.run(["git", "rm", "--cached", "--", *pair], cwd=tmp_path, check=True)

    report = gate.check_feature_contracts(
        tmp_path,
        pair,
        validator=dc,
        head_ref=gate.INDEX_EVALUATION_REF,
        evaluation_ref=gate.INDEX_EVALUATION_REF,
    )

    assert report.valid_contract_ids == ()
    assert any("missing from evaluation index" in error for error in report.errors)


def test_index_evaluation_uses_staged_contract_not_worktree(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/app.py")
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
    )
    subprocess.run(["git", "add", "--", *pair], cwd=tmp_path, check=True)
    (tmp_path / pair[0]).write_text("not: [valid\n", encoding="utf-8")

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py", *pair],
        validator=dc,
        head_ref=gate.INDEX_EVALUATION_REF,
        evaluation_ref=gate.INDEX_EVALUATION_REF,
    )

    assert report.errors == ()
    assert report.valid_contract_ids == ("feature-one",)


def test_named_evaluation_head_uses_tree_contract_not_worktree(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/app.py")
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
    )
    subprocess.run(["git", "add", "--", *pair], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add contract"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / pair[0]).write_text("not: [valid\n", encoding="utf-8")

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py", *pair],
        validator=dc,
        head_ref=head,
        evaluation_ref=head,
    )

    assert report.errors == ()
    assert report.valid_contract_ids == ("feature-one",)


def test_cli_changed_files_mode_uses_index_for_contract_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/app.py")
    pair = _write_complete_contract(tmp_path, "feature-one", ["services/example/**"])
    subprocess.run(["git", "add", "--", *pair], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add contract"], cwd=tmp_path, check=True)
    subprocess.run(["git", "rm", "--cached", "--", *pair], cwd=tmp_path, check=True)
    (tmp_path / "changed.txt").write_text("\n".join(pair) + "\n", encoding="utf-8")
    monkeypatch.setattr(gate, "load_contract_validator", lambda _root: dc)

    exit_code = gate.main(
        ["--root", str(tmp_path), "--changed-files-file", "changed.txt"]
    )

    assert exit_code == 1
    assert "missing from evaluation index" in capsys.readouterr().err


def test_contract_change_id_must_match_directory(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/**"],
        embedded_change_id="feature-other",
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example.py", *pair],
        validator=dc,
    )

    assert any("must match its directory name" in error for error in report.errors)


def test_changed_files_file_is_utf8_and_normalizes_windows_separators(tmp_path: Path) -> None:
    changed_file = tmp_path / "changed.txt"
    changed_file.write_text(
        "frontend\\src\\app\\page.tsx\n./docs/guide.md\n",
        encoding="utf-8",
    )

    assert gate.read_changed_files(changed_file) == (
        "docs/guide.md",
        "frontend/src/app/page.tsx",
    )


def test_changed_files_file_accepts_utf8_bom(tmp_path: Path) -> None:
    changed_file = tmp_path / "changed.txt"
    changed_file.write_bytes(b"\xef\xbb\xbfdocs/guide.md\n")

    assert gate.read_changed_files(changed_file) == ("docs/guide.md",)


def test_cli_supports_changed_files_file_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    changed_file = tmp_path / "changed.txt"
    changed_file.write_text("docs/guide.md\ntests/test_guide.py\n", encoding="utf-8")

    exit_code = gate.main(
        ["--root", str(tmp_path), "--changed-files-file", "changed.txt"]
    )

    assert exit_code == 0
    assert "SKIP" in capsys.readouterr().out


def test_changed_path_cannot_escape_repository() -> None:
    with pytest.raises(gate.GateInputError, match="escapes the repository"):
        gate.normalize_changed_path("../outside.py")


def test_base_head_diff_uses_merge_base_and_reports_changed_paths(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    _commit_file(tmp_path, "services/example/app.py")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    assert gate.git_changed_files(tmp_path, base, head) == ("services/example/app.py",)


def test_worktree_and_index_modes_derive_different_git_truths(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    staged = tmp_path / "services" / "example" / "staged.py"
    staged.parent.mkdir(parents=True)
    staged.write_text("STAGED = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "services/example/staged.py"], cwd=tmp_path, check=True)
    unstaged = tmp_path / "services" / "example" / "unstaged.py"
    unstaged.write_text("UNSTAGED = True\n", encoding="utf-8")

    assert gate.git_index_changed_files(tmp_path) == ("services/example/staged.py",)
    assert gate.git_worktree_changed_files(tmp_path) == (
        "services/example/staged.py",
        "services/example/unstaged.py",
    )


def test_cli_resolves_worktree_index_and_backward_compatible_commit_modes(
    tmp_path: Path,
) -> None:
    _initialize_git_repo(tmp_path)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    product = tmp_path / "services" / "example" / "app.py"
    product.parent.mkdir(parents=True)
    product.write_text("VALUE = 2\n", encoding="utf-8")

    parser = gate._build_parser()
    worktree = gate._resolve_evaluation_inputs(
        parser.parse_args(["--root", str(tmp_path), "--mode", "worktree"])
    )
    assert worktree.mode == "worktree"
    assert worktree.changed_files == ("services/example/app.py",)

    subprocess.run(["git", "add", "services/example/app.py"], cwd=tmp_path, check=True)
    index = gate._resolve_evaluation_inputs(
        parser.parse_args(["--root", str(tmp_path), "--mode", "index"])
    )
    assert index.mode == "index"
    assert index.changed_files == ("services/example/app.py",)

    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    commit = gate._resolve_evaluation_inputs(
        parser.parse_args(
            ["--root", str(tmp_path), "--base", base, "--head", head]
        )
    )
    assert commit.mode == "commit"
    assert commit.changed_files == ("services/example/app.py",)


def test_two_contracts_cannot_share_one_protected_path(tmp_path: Path) -> None:
    first = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
        state="GRAPH_DIFF_READY",
        schema_version=3,
    )
    second = _write_complete_contract(
        tmp_path,
        "feature-two",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
        state="GRAPH_DIFF_READY",
        schema_version=3,
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py", *first, *second],
        validator=dc,
    )

    assert any("must have exactly one contract owner" in error for error in report.errors)
    assert any("feature-one, feature-two" in error for error in report.errors)


def test_legacy_v2_union_overlap_remains_compatible(tmp_path: Path) -> None:
    first = _write_complete_contract(
        tmp_path,
        "feature-one",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
        schema_version=2,
    )
    second = _write_complete_contract(
        tmp_path,
        "feature-two",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
        schema_version=2,
    )

    report = gate.check_feature_contracts(
        tmp_path,
        ["services/example/app.py", *first, *second],
        validator=dc,
    )

    assert report.errors == ()


def test_v3_declared_risk_cannot_be_below_derived_floor(tmp_path: Path) -> None:
    pair = _write_complete_contract(
        tmp_path,
        "governance-change",
        [".github/workflows/ci.yml"],
        actual_paths=[".github/workflows/ci.yml"],
        state="GRAPH_DIFF_READY",
        schema_version=3,
        risk_level="R1",
    )

    report = gate.check_feature_contracts(
        tmp_path,
        [".github/workflows/ci.yml", *pair],
        validator=dc,
    )

    assert any("declared risk R1 is below derived minimum R2" in error for error in report.errors)


def test_risk_floor_covers_r0_through_r3() -> None:
    assert gate.derive_risk_floor(["docs/guide.md", "tests/test_guide.py"]) == "R0"
    assert gate.derive_risk_floor(["services/example/app.py"]) == "R1"
    assert gate.derive_risk_floor(["frontend/src/app/page.tsx", "services/example/app.py"]) == "R2"
    assert gate.derive_risk_floor(["migrations/099_example.sql"]) == "R2"
    breaking = {"compatibility": {"api": {"status": "breaking"}}}
    assert gate.derive_risk_floor(["services/example/app.py"], breaking) == "R3"


def test_v3_commit_mode_binds_delivery_and_builds_external_attestation(
    tmp_path: Path,
) -> None:
    _initialize_git_repo(tmp_path)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    product = tmp_path / "services" / "example" / "app.py"
    product.parent.mkdir(parents=True)
    product.write_text("VALUE = 2\n", encoding="utf-8")
    pair = _write_complete_contract(
        tmp_path,
        "feature-v3",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
        state="GRAPH_DIFF_READY",
        schema_version=3,
        base_commit=base,
        risk_level="R1",
    )
    subprocess.run(["git", "add", "--", "services/example/app.py", *pair], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "deliver v3 candidate"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    changed = gate.git_changed_files(tmp_path, base, head)

    report = gate.check_feature_contracts(
        tmp_path,
        changed,
        validator=dc,
        head_ref=head,
        evaluation_ref=head,
        validation_mode="commit",
        base_ref=base,
    )

    assert report.errors == ()
    payload = gate.build_delivery_attestation(
        tmp_path,
        report,
        head,
        attestor="github-actions",
        run_id="123",
    )
    assert payload["authority"] == "ci_attestation"
    assert payload["status"] == "COMPLETE"
    assert payload["delivered_commit"] == head
    assert payload["contracts"][0]["base_commit"] == base
    assert "delivered_commit" not in dc.read_yaml(tmp_path / pair[1])["delivery"]


def test_v3_stale_tracked_path_is_not_current_delivery(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    _commit_file(tmp_path, "services/example/archived.py")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    pair = _write_complete_contract(
        tmp_path,
        "feature-v3",
        ["services/example/**"],
        actual_paths=["services/example/archived.py"],
        state="GRAPH_DIFF_READY",
        schema_version=3,
        base_commit=base,
    )
    subprocess.run(["git", "add", "--", *pair], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "claim stale delivery"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    report = gate.check_feature_contracts(
        tmp_path,
        gate.git_changed_files(tmp_path, base, head),
        validator=dc,
        head_ref=head,
        evaluation_ref=head,
        validation_mode="commit",
        base_ref=base,
    )

    assert any("is not changed between the declared delivery baseline" in error for error in report.errors)


def test_v3_nonancestor_delivery_base_is_rejected(tmp_path: Path) -> None:
    _initialize_git_repo(tmp_path)
    original_branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=tmp_path, text=True
    ).strip()
    initial = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "checkout", "-qb", "foreign"], cwd=tmp_path, check=True)
    _commit_file(tmp_path, "foreign.txt")
    foreign = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "checkout", "-q", original_branch], cwd=tmp_path, check=True)
    product = tmp_path / "services" / "example" / "app.py"
    product.parent.mkdir(parents=True)
    product.write_text("VALUE = 2\n", encoding="utf-8")
    pair = _write_complete_contract(
        tmp_path,
        "feature-v3",
        ["services/example/**"],
        actual_paths=["services/example/app.py"],
        state="GRAPH_DIFF_READY",
        schema_version=3,
        base_commit=foreign,
    )
    subprocess.run(["git", "add", "--", "services/example/app.py", *pair], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    report = gate.check_feature_contracts(
        tmp_path,
        gate.git_changed_files(tmp_path, initial, head),
        validator=dc,
        head_ref=head,
        evaluation_ref=head,
        validation_mode="commit",
        base_ref=initial,
    )

    assert any("is not an ancestor" in error for error in report.errors)


def test_local_modes_cannot_generate_delivery_attestation(tmp_path: Path) -> None:
    report = gate.GateReport(
        changed_files=(),
        protected_files=(),
        changed_contract_ids=(),
        valid_contract_ids=(),
        errors=(),
        validation_mode="index",
    )

    with pytest.raises(gate.GateInputError, match="only in commit mode"):
        gate.build_delivery_attestation(tmp_path, report, "HEAD")


def test_r3_delivery_attestation_is_fail_closed_without_external_gate_verifier(
    tmp_path: Path,
) -> None:
    report = gate.GateReport(
        changed_files=("services/example/app.py",),
        protected_files=("services/example/app.py",),
        changed_contract_ids=("critical-change",),
        valid_contract_ids=("critical-change",),
        errors=(),
        validation_mode="commit",
        validated_contracts=(
            gate.ValidatedContract(
                change_id="critical-change",
                schema_version=3,
                risk_level="R3",
                base_commit="a" * 40,
                actual_paths=("services/example/app.py",),
                impact_sha256="b" * 64,
                completion_sha256="c" * 64,
            ),
        ),
    )

    with pytest.raises(gate.GateInputError, match="fail-closed"):
        gate.build_delivery_attestation(tmp_path, report, "HEAD")


def test_database_delivery_attestation_is_fail_closed_before_s15_gate(
    tmp_path: Path,
) -> None:
    migration = "migrations/099_example.sql"
    report = gate.GateReport(
        changed_files=(migration,),
        protected_files=(migration,),
        changed_contract_ids=("migration-change",),
        valid_contract_ids=("migration-change",),
        errors=(),
        validation_mode="commit",
        validated_contracts=(
            gate.ValidatedContract(
                change_id="migration-change",
                schema_version=3,
                risk_level="R2",
                base_commit="a" * 40,
                actual_paths=(migration,),
                impact_sha256="b" * 64,
                completion_sha256="c" * 64,
            ),
        ),
    )

    with pytest.raises(gate.GateInputError, match="S1.5 blocking migration gate"):
        gate.build_delivery_attestation(tmp_path, report, "HEAD")


def test_legacy_changed_file_mode_cannot_emit_attestation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    changed = tmp_path / "changed.txt"
    changed.write_text("docs/guide.md\n", encoding="utf-8")

    exit_code = gate.main(
        [
            "--root",
            str(tmp_path),
            "--changed-files-file",
            str(changed),
            "--attestation-out",
            str(tmp_path / "seal.json"),
        ]
    )

    assert exit_code == 2
    assert "allowed only in commit mode" in capsys.readouterr().err
    assert not (tmp_path / "seal.json").exists()


def test_ci_complete_seal_is_restricted_to_default_branch_push() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    seal = workflow["jobs"]["delivery-seal"]

    assert seal["if"] == (
        "github.event_name == 'push' && "
        "github.ref_type == 'branch' && "
        "github.ref_name == github.event.repository.default_branch"
    )
    assert "ke-bootstrap-gate" in seal["needs"]
    assert "full-suite" not in seal["needs"]
    assert workflow["concurrency"]["group"] == (
        "ci-${{ github.ref }}-${{ github.ref == "
        "format('refs/heads/{0}', github.event.repository.default_branch) "
        "&& github.run_id || 'cancelable' }}"
    )
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert seal["env"]["EVALUATION_SHA"] == "${{ github.sha }}"
    assert seal["env"]["ACTUAL_REF"] == "${{ github.ref }}"
    exact_ref = next(
        step for step in seal["steps"] if "精确验证默认分支引用" in step.get("name", "")
    )
    assert '[ "$ACTUAL_REF" != "refs/heads/$DEFAULT_BRANCH" ]' in exact_ref["run"]
    upload = next(
        step
        for step in seal["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    )
    assert upload["with"]["name"] == "delivery-attestation-${{ steps.refs.outputs.head_sha }}"


def test_ci_feature_push_uses_default_branch_merge_base() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    feature_gate = workflow["jobs"]["feature-contract-gate"]
    diff_step = next(
        step for step in feature_gate["steps"] if "计算 diff" in step.get("name", "")
    )
    script = diff_step["run"]

    assert diff_step["env"]["REF_NAME"] == "${{ github.ref_name }}"
    assert diff_step["env"]["REF_TYPE"] == "${{ github.ref_type }}"
    assert (
        'elif [ "$EVENT_NAME" = "push" ] && '
        '[ "$REF_TYPE" = "branch" ] && '
        '[ "$REF_NAME" = "$DEFAULT_BRANCH" ]; then'
    ) in script
    assert 'BASE_SHA="$(git merge-base "$HEAD_SHA" "origin/$DEFAULT_BRANCH"' in script


def test_ci_push_excludes_tags_and_required_bootstraps_are_blocking() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    triggers = workflow.get("on", workflow.get(True))

    assert triggers["push"]["branches"] == ["**"]
    assert "tags" not in triggers["push"]

    jobs = workflow["jobs"]
    bootstrap = jobs["ke-bootstrap-gate"]
    install = next(step for step in bootstrap["steps"] if "干净安装" in step.get("name", ""))
    collect = next(step for step in bootstrap["steps"] if "收集全套" in step.get("name", ""))
    frontend = next(
        step
        for step in jobs["codex-runner-gate"]["steps"]
        if "前端单测" in step.get("name", "")
    )

    assert 'pip install -e ".[dev]"' in install["run"]
    assert "pytest --collect-only" in collect["run"]
    assert collect["env"]["OMNI_UPLOAD_DIR"] == "${{ runner.temp }}/omni/uploads"
    assert frontend["run"] == "npm run test:unit"


def test_ci_names_critical_asset_gate_without_claiming_full_readiness() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["agents-policy-gate"]["steps"]
    readiness_step = next(
        step for step in steps if "关键开发资产" in step.get("name", "")
    )

    assert "--strict-critical-assets" in readiness_step["run"]
    assert "非全面 readiness" in readiness_step["name"]
