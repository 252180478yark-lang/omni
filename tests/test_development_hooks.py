import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "hooks" / "development_gate.py"
SPEC = importlib.util.spec_from_file_location("development_gate", MODULE_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    impact = tmp_path / "docs" / "dev-changes" / "fixture-change" / "impact.yaml"
    impact.parent.mkdir(parents=True)
    impact.write_text(
        "schema_version: 3\n"
        "change_id: fixture-change\n"
        "state: IMPLEMENTING\n"
        "risk:\n  level: R2\n"
        "planned_changes:\n"
        "- id: CHG-001\n"
        "  paths:\n"
        "  - src/owned.py\n"
        "  - src/tree/**\n",
        encoding="utf-8",
    )
    return tmp_path


def fixture(name: str) -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / "hooks" / name).read_text(encoding="utf-8"))


def lease(*, conflict=False, known=True, stale=False, owner=None):
    return lambda _root, _path, _change: gate.LeaseView(
        known=known, conflict=conflict, stale=stale, owner=owner
    )


def test_pretool_allows_owned_same_risk_path(repo: Path):
    result = gate.evaluate_pre_tool(
        fixture("pretool-allow.json"), repo, lease_resolver=lease()
    )
    assert result.decision is gate.Decision.ALLOW
    assert result.issue_code == "contract_and_lease_match"


def test_pretool_requests_contract_delta_before_retry(repo: Path):
    result = gate.evaluate_pre_tool(
        fixture("pretool-remediate.json"), repo, lease_resolver=lease()
    )
    assert result.decision is gate.Decision.REMEDIATE
    assert result.issue_code == "contract_delta_required"
    assert "contract" in result.repair.lower()


def test_pretool_blocks_risk_escalation(repo: Path):
    result = gate.evaluate_pre_tool(
        fixture("pretool-risk-block.json"), repo, lease_resolver=lease()
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "risk_escalation"


def test_pretool_blocks_active_foreign_lease(repo: Path):
    result = gate.evaluate_pre_tool(
        fixture("pretool-allow.json"),
        repo,
        lease_resolver=lease(conflict=True, owner="other-agent"),
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.lease_owner == "other-agent"


def test_pretool_ignores_expired_lease_but_keeps_warning(repo: Path):
    result = gate.evaluate_pre_tool(
        fixture("pretool-allow.json"),
        repo,
        lease_resolver=lease(stale=True, owner="old-agent"),
    )
    assert result.decision is gate.Decision.ALLOW
    assert "stale lease" in result.warnings[0]


def test_unknown_lease_fails_closed_for_r2_and_warns_for_r1(repo: Path):
    high = fixture("pretool-allow.json")
    high["risk"] = "R2"
    r2 = gate.evaluate_pre_tool(high, repo, lease_resolver=lease(known=False))
    low = fixture("pretool-allow.json")
    low["risk"] = "R1"
    r1 = gate.evaluate_pre_tool(low, repo, lease_resolver=lease(known=False))
    assert (r2.decision, r2.issue_code) == (gate.Decision.BLOCK, "lease_unknown")
    assert (r1.decision, r1.issue_code) == (gate.Decision.ALLOW, "lease_unknown_warning")


def test_malformed_high_risk_target_is_not_silently_allowed(repo: Path):
    result = gate.evaluate_pre_tool(
        {"tool_name": "Write", "risk": "R2", "tool_input": {}},
        repo,
        lease_resolver=lease(),
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "target_unknown"


def test_malformed_json_sentinel_is_fail_closed(repo: Path):
    result = gate.evaluate_pre_tool({"_malformed_input": True}, repo)
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "malformed_hook_input"


def test_migration_dry_run_verify_is_r2_but_real_apply_is_r3(repo: Path):
    verify = {
        "tool_name": "shell_command",
        "tool_input": {"command": "python -B scripts/apply_migrations.py --dry-run --verify"},
    }
    apply = {
        "tool_name": "shell_command",
        "tool_input": {"command": "python -B scripts/apply_migrations.py"},
    }
    assert gate._requested_risk(verify, None) == "R2"
    assert gate._requested_risk(apply, None) == "R3"


def test_active_contract_wins_over_delivered_overlap(repo: Path):
    older = repo / "docs" / "dev-changes" / "older" / "impact.yaml"
    older.parent.mkdir(parents=True)
    older.write_text(
        "change_id: older\nstate: GRAPH_DIFF_READY\nrisk:\n  level: R2\n"
        "planned_changes:\n- id: OLD\n  paths:\n  - src/owned.py\n",
        encoding="utf-8",
    )
    selected = gate._select_contract(gate._contracts(repo), {}, "src/owned.py")
    assert selected is not None
    assert selected.change_id == "fixture-change"


def test_contract_implicitly_owns_its_evidence_directory(repo: Path):
    contracts = gate._contracts(repo)
    assert gate._path_matches(
        "docs/dev-changes/fixture-change/completion.yaml", contracts[0].paths[-1]
    )


def test_stop_has_recursion_guard(repo: Path):
    result = gate.evaluate_stop({"stop_hook_active": True}, repo)
    assert result.decision is gate.Decision.ALLOW
    assert result.issue_code == "recursion_guard"


def test_stop_blocks_unowned_change_before_running_commands(repo: Path):
    result = gate.evaluate_stop({"changed_paths": ["outside.py"]}, repo)
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "deterministic_scope_gap"


def test_stop_timeout_is_unknown_and_blocking(repo: Path):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["verify"], 0.01)

    result = gate.evaluate_stop(
        {"changed_paths": ["src/owned.py"]}, repo, command_runner=timeout
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "verification_timeout"


def test_output_uses_host_hook_protocol(repo: Path):
    result = gate.evaluate_pre_tool(
        fixture("pretool-remediate.json"), repo, lease_resolver=lease()
    )
    output = gate._output(result)
    assert "continue" not in output
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert set(output["hookSpecificOutput"]) == {
        "hookEventName",
        "permissionDecision",
        "permissionDecisionReason",
    }


def test_stop_block_uses_official_continuation_protocol_only(repo: Path):
    output = gate._output(gate.evaluate_stop({"changed_paths": ["outside.py"]}, repo))
    assert output["decision"] == "block"
    assert "continue" not in output
    assert set(output) == {"decision", "reason"}


@pytest.mark.parametrize(
    "command",
    [
        "echo content > src/owned.py",
        "New-Item -ItemType File -Path src/owned.py",
        "Copy-Item src/source.py src/owned.py",
        "python -c \"open('src/owned.py', 'w').write('x')\"",
    ],
)
def test_shell_write_forms_are_classified_and_checked(repo: Path, command: str):
    result = gate.evaluate_pre_tool(
        {"tool_name": "shell_command", "tool_input": {"command": command}},
        repo,
        lease_resolver=lease(),
    )
    assert result.decision is gate.Decision.ALLOW
    assert result.path == "src/owned.py"


@pytest.mark.parametrize(
    "target",
    [
        "../src/owned.py",
        "src/../src/owned.py",
        "/src/owned.py",
        r"\\server\share\owned.py",
        r"C:src\owned.py",
        r"C:\src\owned.py",
        "src/owned.py:secret",
        "src/CON/file.py",
        "src/trailing. /file.py",
    ],
)
def test_invalid_or_ambiguous_write_paths_fail_closed(repo: Path, target: str):
    result = gate.evaluate_pre_tool(
        {"tool_name": "Write", "tool_input": {"file_path": target}},
        repo,
        lease_resolver=lease(),
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "target_invalid_or_incomplete"


def test_single_star_does_not_cross_path_segments():
    assert gate._path_matches("src/a.py", "src/*")
    assert not gate._path_matches("src/nested/a.py", "src/*")
    assert gate._path_matches("src/nested/a.py", "src/**")


def test_apply_patch_checks_every_target(repo: Path):
    payload = {
        "tool_name": "apply_patch",
        "tool_input": {
            "patch": "*** Update File: src/owned.py\n*** Update File: outside.py\n"
        },
    }
    result = gate.evaluate_pre_tool(payload, repo, lease_resolver=lease())
    assert result.decision is gate.Decision.REMEDIATE
    assert result.path == "outside.py"


def test_multiedit_checks_every_target(repo: Path):
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "edits": [
                {"file_path": "src/owned.py", "content": "ok"},
                {"file_path": "outside.py", "content": "not owned"},
            ]
        },
    }
    result = gate.evaluate_pre_tool(payload, repo, lease_resolver=lease())
    assert result.decision is gate.Decision.REMEDIATE
    assert result.path == "outside.py"


def test_multi_contract_write_must_be_split(repo: Path):
    second = repo / "docs" / "dev-changes" / "second" / "impact.yaml"
    second.parent.mkdir(parents=True)
    second.write_text(
        "change_id: second\nstate: IMPLEMENTING\nrisk:\n  level: R2\n"
        "planned_changes:\n- id: SECOND\n  paths:\n  - other/owned.py\n",
        encoding="utf-8",
    )
    payload = {
        "tool_name": "apply_patch",
        "tool_input": {
            "patch": "*** Update File: src/owned.py\n*** Update File: other/owned.py\n"
        },
    }
    result = gate.evaluate_pre_tool(payload, repo, lease_resolver=lease())
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "multi_contract_write"


def test_unknown_shell_intent_fails_closed_at_every_risk(repo: Path):
    payload = {"tool_name": "shell_command", "tool_input": {"command": "Get-Date"}}
    low = gate.evaluate_pre_tool(payload, repo, lease_resolver=lease())
    high = gate.evaluate_pre_tool({**payload, "risk": "R2"}, repo, lease_resolver=lease())
    assert (low.decision, low.issue_code) == (gate.Decision.BLOCK, "shell_intent_unknown")
    assert (high.decision, high.issue_code) == (
        gate.Decision.BLOCK,
        "shell_intent_unknown",
    )


def test_non_writable_contract_never_authorizes_write(repo: Path):
    impact = repo / "docs" / "dev-changes" / "fixture-change" / "impact.yaml"
    impact.write_text(
        impact.read_text(encoding="utf-8").replace("IMPLEMENTING", "GRAPH_DIFF_READY"),
        encoding="utf-8",
    )
    result = gate.evaluate_pre_tool(
        fixture("pretool-allow.json"), repo, lease_resolver=lease()
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "contract_not_writable"


def test_stop_does_not_treat_non_writable_contract_as_coverage(repo: Path):
    impact = repo / "docs" / "dev-changes" / "fixture-change" / "impact.yaml"
    impact.write_text(
        impact.read_text(encoding="utf-8").replace("IMPLEMENTING", "GRAPH_DIFF_READY"),
        encoding="utf-8",
    )
    result = gate.evaluate_stop({"changed_paths": ["src/owned.py"]}, repo)
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "deterministic_scope_gap"


@pytest.mark.parametrize("stdin", ["[]", '"x"', "null", "{}"])
def test_cli_rejects_non_object_or_missing_pretool_fields(repo: Path, stdin: str):
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(MODULE_PATH),
            "--event",
            "PreToolUse",
            "--root",
            str(repo),
        ],
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "malformed_hook_input" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_cli_rejects_shell_payload_without_command(repo: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(MODULE_PATH),
            "--event",
            "PreToolUse",
            "--root",
            str(repo),
        ],
        input=json.dumps({"tool_name": "shell_command", "tool_input": {}}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "malformed_hook_input" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_cli_blocks_r2_unknown_shell_intent(repo: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(MODULE_PATH),
            "--event",
            "PreToolUse",
            "--root",
            str(repo),
        ],
        input=json.dumps(
            {"tool_name": "shell_command", "risk": "R2", "tool_input": {"command": "Get-Date"}}
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "shell_intent_unknown" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_session_and_stop_never_echo_subprocess_secret_canaries(repo: Path, monkeypatch):
    canary = "Bearer test-token-SECRET-CANARY-123456 postgres://user:placeholder-password@db/name"

    def session_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["check"],
            0,
            stdout=json.dumps({"systemMessage": canary}),
            stderr=canary,
        )

    monkeypatch.setattr(gate.subprocess, "run", session_runner)
    session_output = json.dumps(gate._output(gate._session_start(repo, 1)), ensure_ascii=False)

    def stop_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(["verify"], 1, stdout=canary, stderr=canary)

    stop = gate.evaluate_stop(
        {"changed_paths": ["src/owned.py"]}, repo, command_runner=stop_runner
    )
    stop_output = json.dumps(gate._output(stop), ensure_ascii=False)
    assert "SECRET-CANARY" not in session_output
    assert "PASSWORD-CANARY" not in session_output
    assert "SECRET-CANARY" not in stop_output
    assert "PASSWORD-CANARY" not in stop_output


def test_hooks_config_observes_all_pretool_events_and_canonical_tools():
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert set(config) == {"hooks"}
    assert set(config["hooks"]) == {"SessionStart", "PreToolUse", "Stop"}
    matcher = config["hooks"]["PreToolUse"][0]["matcher"]
    assert matcher == "*"
    assert all(matcher == "*" for _tool in ("apply_patch", "Bash", "Edit", "Write"))


def test_official_apply_patch_command_shape_checks_all_path_classes(repo: Path):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {
            "command": (
                "*** Begin Patch\n"
                "*** Update File: src/owned.py\n"
                "*** Add File: .codex/new-hook.json\n"
                "*** Update File: docs/new.md\n"
                "*** End Patch"
            )
        },
    }
    result = gate.evaluate_pre_tool(payload, repo, lease_resolver=lease())
    assert result.decision is gate.Decision.REMEDIATE
    assert result.path in {".codex/new-hook.json", "docs/new.md"}


def test_unknown_external_write_tool_is_never_assumed_read_only(repo: Path):
    result = gate.evaluate_pre_tool(
        {
            "tool_name": "mcp__external__publish",
            "effect_kinds": ["publish"],
            "tool_input": {"channel": "production"},
        },
        repo,
        lease_resolver=lease(),
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "target_unknown"


def test_unknown_tool_without_effect_metadata_fails_closed(repo: Path):
    result = gate.evaluate_pre_tool(
        {"tool_name": "mcp__external__mystery", "tool_input": {}},
        repo,
        lease_resolver=lease(),
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "tool_intent_unknown"


def test_official_rename_checks_move_destination(repo: Path):
    payload = {
        "tool_name": "apply_patch",
        "tool_input": {
            "command": (
                "*** Begin Patch\n"
                "*** Update File: src/owned.py\n"
                "*** Move to: outside/moved.py\n"
                "*** End Patch"
            )
        },
    }
    result = gate.evaluate_pre_tool(payload, repo, lease_resolver=lease())
    assert result.decision is gate.Decision.REMEDIATE
    assert result.path == "outside/moved.py"


@pytest.mark.parametrize("destination", ["../outside.py", "C:/outside.py", r"\\host\share\x.py"])
def test_official_rename_rejects_invalid_destination(repo: Path, destination: str):
    result = gate.evaluate_pre_tool(
        {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": f"*** Update File: src/owned.py\n*** Move to: {destination}\n"
            },
        },
        repo,
        lease_resolver=lease(),
    )
    assert result.decision is gate.Decision.BLOCK
    assert result.issue_code == "target_invalid_or_incomplete"


def test_read_shell_is_allowed_but_external_and_db_writes_are_r3_blocked(repo: Path):
    read = gate.evaluate_pre_tool(
        {"tool_name": "Bash", "tool_input": {"command": "git status --short"}},
        repo,
        lease_resolver=lease(),
    )
    assert (read.decision, read.issue_code) == (gate.Decision.ALLOW, "read_only")
    for command in (
        "curl -X POST https://example.test/items",
        "Invoke-RestMethod https://example.test/items -Method POST",
        'psql -c "UPDATE records SET value=1"',
    ):
        result = gate.evaluate_pre_tool(
            {"tool_name": "Bash", "tool_input": {"command": command}},
            repo,
            lease_resolver=lease(),
        )
        assert result.decision is gate.Decision.BLOCK
        assert result.risk == "R3"
