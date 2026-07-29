from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_development_readiness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("development_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


readiness = _load_module()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def _write(root: Path, relative: str, text: str = "fixture\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "codex@example.invalid")
    _git(tmp_path, "config", "user.name", "Codex Test")
    executable_fixtures = {
        "scripts/development_policy.py",
        "scripts/generate_implementation_status.py",
        "scripts/workspace_ownership.py",
    }
    for relative in readiness.CRITICAL_ASSETS:
        if relative in executable_fixtures:
            _write(tmp_path, relative, (ROOT / relative).read_text(encoding="utf-8"))
        else:
            _write(tmp_path, relative)
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def test_ready_when_critical_assets_match_head(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)

    report = readiness.build_report(root)

    assert report["readiness"] == "ready"
    assert report["missing_from_head"] == []
    assert {item["state"] for item in report["critical_assets"]} == {
        "delivered_in_head"
    }


def test_staged_governance_asset_is_candidate_not_delivered(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    _write(root, "AGENTS.md", "changed candidate\n")
    _git(root, "add", "AGENTS.md")

    report = readiness.build_report(root)
    agent = next(item for item in report["critical_assets"] if item["path"] == "AGENTS.md")

    assert report["readiness"] == "candidate_not_delivered"
    assert agent["state"] == "staged_candidate"
    assert "AGENTS.md" in report["missing_from_head"]


def test_unstaged_change_after_index_is_visible(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    _write(root, ".github/workflows/ci.yml", "staged\n")
    _git(root, "add", ".github/workflows/ci.yml")
    _write(root, ".github/workflows/ci.yml", "later worktree edit\n")

    report = readiness.build_report(root)
    ci = next(
        item
        for item in report["critical_assets"]
        if item["path"] == ".github/workflows/ci.yml"
    )

    assert ci["state"] == "candidate_modified_after_index"
    assert report["git_status"]["staged_entries"] == 1
    assert report["git_status"]["unstaged_entries"] == 1


def test_active_contract_overlap_is_reported(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    declared_paths = {
        "change-one": ["services/**"],
        "change-two": ["services/example.py"],
    }
    for change_id, paths in declared_paths.items():
        impact = {
            "schema_version": 2,
            "change_id": change_id,
            "state": "IMPLEMENTING",
            "planned_changes": [{"paths": paths}],
            "allowed_unplanned_paths": [],
        }
        path = root / "docs" / "dev-changes" / change_id / "impact.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(impact, sort_keys=False), encoding="utf-8")

    report = readiness.build_report(root)

    assert report["overlapping_active_patterns"] == [
        "services/** <-> services/example.py: change-one, change-two"
    ]
    assert len(report["active_contracts"]) == 2


def test_non_overlapping_globs_are_not_reported(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    for change_id, pattern in (
        ("change-one", "services/alpha/**"),
        ("change-two", "services/beta/**"),
    ):
        impact = {
            "schema_version": 2,
            "change_id": change_id,
            "state": "IMPLEMENTING",
            "planned_changes": [{"paths": [pattern]}],
        }
        path = root / "docs" / "dev-changes" / change_id / "impact.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(impact, sort_keys=False), encoding="utf-8")

    report = readiness.build_report(root)

    assert report["overlapping_active_patterns"] == []


def test_malformed_contract_is_explicitly_unknown(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    path = root / "docs" / "dev-changes" / "broken-contract" / "impact.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("planned_changes: [\n", encoding="utf-8")

    report = readiness.build_report(root)

    assert report["readiness"] == "contract_state_unknown"
    assert report["checks"]["contracts"] == "unknown"
    assert report["active_contracts"][0]["state"] == "unknown"
    assert report["contract_errors"]
    assert "invalid YAML" in report["contract_errors"][0]


def test_hook_output_is_advisory_and_never_stops_turn(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    _write(root, "AGENTS.md", "candidate\n")
    _git(root, "add", "AGENTS.md")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--hook"],
        input=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "cwd": str(root),
            }
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "只能视为候选实现" in payload["hookSpecificOutput"]["additionalContext"]
    assert "continue" not in payload
    assert "decision" not in payload


def test_strict_fails_when_asset_is_not_in_head(tmp_path: Path) -> None:
    root = _seed_repository(tmp_path)
    _write(root, "AGENTS.md", "candidate\n")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--strict-critical-assets",
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "context_status=candidate_not_delivered" in result.stdout


def test_missing_pyyaml_still_emits_advisory_hook_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = _seed_repository(tmp_path)
    monkeypatch.setattr(readiness, "yaml", None)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    exit_code = readiness.main(["--root", str(root), "--hook"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "未知项" in payload["systemMessage"]
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "contract_state_unknown" in context
    assert "contracts=unknown" in context
    assert "PyYAML" in context


def test_hook_reinjects_readiness_after_clear_and_compact() -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    handlers = config["hooks"]["SessionStart"]
    readiness_handler = next(
        handler
        for handler in handlers
        if "scripts/hooks/development_gate.py" in handler["hooks"][0]["command"]
        and "--event SessionStart" in handler["hooks"][0]["command"]
    )

    assert readiness_handler["matcher"] == "startup|resume|clear|compact"
    assert readiness_handler["hooks"][0]["timeout"] == 45
    gate_source = (ROOT / "scripts" / "hooks" / "development_gate.py").read_text(
        encoding="utf-8"
    )
    assert "scripts\" / \"check_development_readiness.py" in gate_source
