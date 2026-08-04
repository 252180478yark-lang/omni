from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_workspace_ownership_tests", ROOT / "scripts" / "workspace_ownership.py"
)
assert SPEC is not None and SPEC.loader is not None
ownership = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ownership
SPEC.loader.exec_module(ownership)


def _run(repo: Path, *args: str) -> None:
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "base")
    return repo


def test_primary_dirty_paths_are_preserved_external_user_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    (repo / "base.txt").write_text("user edit\n", encoding="utf-8")
    before = (repo / "base.txt").read_bytes()
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(repo, include_primary=True)

    fact = next(item for item in report["paths"] if item["path"] == "base.txt")
    assert fact["ownership"] == "preserved_external_user"
    assert fact["disposition"] == "preserve_in_place"
    assert (repo / "base.txt").read_bytes() == before


def test_external_path_overlapping_current_contract_remains_blocking(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    current = tmp_path / "current"
    _run(repo, "git", "worktree", "add", "-q", "-b", "current", str(current))
    contract = current / "docs" / "dev-changes" / "change-current" / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": "change-current",
                "state": "IMPLEMENTING",
                "planned_changes": [{"paths": ["services/shared/**"]}],
            }
        ),
        encoding="utf-8",
    )
    external = repo / "services" / "shared" / "app.py"
    external.parent.mkdir(parents=True)
    external.write_text("primary_user_edit = True\n", encoding="utf-8")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(
        current, include_primary=True, secret_scope="changed"
    )

    fact = next(
        item
        for item in report["paths"]
        if item["worktree_id"] == "primary"
        and item["path"] == "services/shared/app.py"
    )
    assert fact["scope_owners"] == ("change-current",)
    assert fact["scope_conflict"] is True
    assert report["counts"]["dirty_scope_conflict"] == 1
    assert report["counts"]["external_scope_overlap"] == 0
    assert "dirty_scope_conflict" in ownership.blocking_ownership_states(
        report["counts"]
    )


def test_external_path_with_mismatched_scope_source_remains_blocking(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    owner = tmp_path / "owner"
    foreign = tmp_path / "foreign"
    current = tmp_path / "observer"
    _run(repo, "git", "worktree", "add", "-q", "-b", "owner", str(owner))
    _run(repo, "git", "worktree", "add", "-q", "-b", "foreign", str(foreign))
    _run(repo, "git", "worktree", "add", "-q", "-b", "observer", str(current))
    contract = owner / "docs" / "dev-changes" / "change-owner" / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": "change-owner",
                "state": "IMPLEMENTING",
                "planned_changes": [{"paths": ["services/shared/**"]}],
            }
        ),
        encoding="utf-8",
    )
    target = foreign / "services" / "shared" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("foreign_edit = True\n", encoding="utf-8")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(
        current, include_primary=False, secret_scope="changed"
    )

    foreign_id = ownership.worktree_id(
        foreign, primary=ownership.primary_worktree(current)
    )
    fact = next(
        item
        for item in report["paths"]
        if item["worktree_id"] == foreign_id
        and item["path"] == "services/shared/app.py"
    )
    assert fact["scope_owners"] == ("change-owner",)
    assert fact["scope_conflict"] is True
    assert report["counts"]["dirty_scope_conflict"] == 1
    assert "dirty_scope_conflict" in ownership.blocking_ownership_states(
        report["counts"]
    )


def test_same_physical_owner_nested_contracts_are_audit_only(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    owner = tmp_path / "owner"
    current = tmp_path / "observer"
    _run(repo, "git", "worktree", "add", "-q", "-b", "owner", str(owner))
    _run(repo, "git", "worktree", "add", "-q", "-b", "observer", str(current))
    for change_id, pattern in (
        ("change-outer", "services/shared/**"),
        ("change-inner", "services/shared/app.py"),
    ):
        contract = owner / "docs" / "dev-changes" / change_id / "impact.yaml"
        contract.parent.mkdir(parents=True)
        contract.write_text(
            yaml.safe_dump(
                {
                    "change_id": change_id,
                    "state": "IMPLEMENTING",
                    "planned_changes": [{"paths": [pattern]}],
                }
            ),
            encoding="utf-8",
        )
    target = owner / "services" / "shared" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("one_physical_writer = True\n", encoding="utf-8")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(
        current, include_primary=False, secret_scope="changed"
    )

    owner_id = ownership.worktree_id(owner, primary=ownership.primary_worktree(current))
    fact = next(
        item
        for item in report["paths"]
        if item["worktree_id"] == owner_id
        and item["path"] == "services/shared/app.py"
    )
    assert fact["scope_owners"] == ("change-inner", "change-outer")
    assert fact["scope_conflict"] is False
    assert report["counts"]["dirty_scope_conflict"] == 0
    assert report["counts"]["external_scope_overlap"] == 3
    assert report["contract_scope_overlaps"] == []
    assert ownership.blocking_ownership_states(report["counts"]) == ()


def test_same_change_in_two_external_worktrees_remains_blocking(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    owner = tmp_path / "owner"
    second_owner = tmp_path / "second-owner"
    current = tmp_path / "observer"
    _run(repo, "git", "worktree", "add", "-q", "-b", "owner", str(owner))
    _run(
        repo,
        "git",
        "worktree",
        "add",
        "-q",
        "-b",
        "second-owner",
        str(second_owner),
    )
    _run(repo, "git", "worktree", "add", "-q", "-b", "observer", str(current))
    for worktree in (owner, second_owner):
        contract = (
            worktree
            / "docs"
            / "dev-changes"
            / "change-shared"
            / "impact.yaml"
        )
        contract.parent.mkdir(parents=True)
        contract.write_text(
            yaml.safe_dump(
                {
                    "change_id": "change-shared",
                    "state": "IMPLEMENTING",
                    "planned_changes": [{"paths": ["services/shared/**"]}],
                }
            ),
            encoding="utf-8",
        )
    target = owner / "services" / "shared" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("ambiguous_writer = True\n", encoding="utf-8")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(
        current, include_primary=False, secret_scope="changed"
    )

    owner_id = ownership.worktree_id(owner, primary=ownership.primary_worktree(current))
    fact = next(
        item
        for item in report["paths"]
        if item["worktree_id"] == owner_id
        and item["path"] == "services/shared/app.py"
    )
    assert fact["scope_owners"] == ("change-shared",)
    assert fact["scope_conflict"] is True
    assert report["counts"]["contract_owner_ambiguity"] == 1
    assert report["counts"]["external_scope_overlap"] == 0
    assert "contract_owner_ambiguity" in ownership.blocking_ownership_states(
        report["counts"]
    )


def test_linked_worktree_contract_ownership_and_archive_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    contract_dir = repo / "docs" / "dev-changes" / "change-a"
    contract_dir.mkdir(parents=True)
    impact = {
        "change_id": "change-a",
        "state": "IMPLEMENTING",
        "planned_changes": [{"paths": ["services/a/**"]}],
        "allowed_unplanned_paths": [],
    }
    (contract_dir / "impact.yaml").write_text(yaml.safe_dump(impact), encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "contract")
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-q", "-b", "feature", str(linked))
    (linked / "services" / "a").mkdir(parents=True)
    (linked / "services" / "a" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (linked / "other.py").write_text("x = 2\n", encoding="utf-8")
    (linked / ".pytest_cache").mkdir()
    (linked / ".pytest_cache" / "state").write_text("cache", encoding="utf-8")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(linked, include_primary=False)

    facts = {item["path"]: item for item in report["paths"]}
    assert facts["services/a/app.py"]["owner_id"] == "change-a"
    assert facts["other.py"]["ownership"] == "unassigned"
    assert facts[".pytest_cache/state"]["hygiene_class"] == "archive_candidate"
    assert report["cleanup"] == {
        "archive_candidate_count": 1,
        "mutated": False,
        "default_recovery_action": "archive_to_change_scoped_recovery_bundle",
    }


@pytest.mark.parametrize("blocking_key", ownership.BLOCKING_OWNERSHIP_COUNT_KEYS)
def test_fail_unassigned_returns_nonzero_for_every_blocking_ownership_state(
    blocking_key: str, monkeypatch
) -> None:
    counts = {key: 0 for key in ownership.BLOCKING_OWNERSHIP_COUNT_KEYS}
    counts[blocking_key] = 1
    report = {"counts": counts, "secret_scan": {"status": "passed"}}
    monkeypatch.setattr(ownership, "inventory_workspace", lambda *_args, **_kwargs: report)

    assert ownership.main(["--fail-unassigned"]) == 1


def test_secret_scan_redacts_token_bearer_dsn_and_private_key_and_honors_allowlist(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    marker = "-----BEGIN " + "PRIVATE KEY-----"
    secret_values = [
        "live_abcdefghijklmnopqrstuvwxyz123456",
        "eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnopqrstuv",
        "real-db-password-928374",
    ]
    (repo / "secrets.env").write_text(
        "API_KEY=" + secret_values[0] + "\n"
        "AUTH=Bearer " + secret_values[1] + "\n"
        "DATABASE_URL=postgresql://user:" + secret_values[2] + "@db:5432/app\n"
        + marker + "\n",
        encoding="utf-8",
    )

    report = ownership.scan_secrets(repo, scope="changed")
    serialized = json.dumps(report)
    assert report["status"] == "failed"
    assert {item["rule"] for item in report["findings"]} == {
        "credential_env_assignment",
        "bearer_token",
        "credential_dsn",
        "private_key",
    }
    assert all(value not in serialized for value in secret_values)

    allowed = ownership.scan_secrets(repo, scope="changed", allowlist=["secrets.env:*"])
    assert allowed["status"] == "passed"
    assert allowed["finding_count"] == 0


def test_tracked_baseline_catches_committed_cookie_session_and_header_literals(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    values = {
        "cookie": "sessionid=" + "A7" * 20 + "; csrftoken=" + "B8" * 18,
        "session": "S9" * 24,
        "authorization": "T6" * 24,
        "credential": "C5" * 40,
    }
    (repo / "credential_literals.py").write_text(
        'Cookie: "' + values["cookie"] + '"\n'
        'sessionid = "' + values["session"] + '"\n'
        'Authorization: "Token ' + values["authorization"] + '"\n'
        'client_secret = "' + values["credential"] + '"\n',
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "credential fixture")

    assert ownership.scan_secrets(repo, scope="changed")["status"] == "passed"
    report = ownership.scan_secrets(repo, scope="tracked")
    assert report["status"] == "failed"
    assert {
        "cookie_header",
        "session_credential",
        "authorization_header",
        "long_credential",
    } <= {item["rule"] for item in report["findings"]}
    assert all(set(item) == {"path", "rule", "fingerprint"} for item in report["findings"])
    serialized = json.dumps(report)
    assert all(value not in serialized for value in values.values())


def test_exact_clean_contract_overlap_is_a_blocking_cli_state(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-q", "-b", "feature", str(linked))
    first = repo / "docs" / "dev-changes" / "change-a"
    first.mkdir(parents=True)
    (first / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "change_id": "change-a",
                "state": "IMPLEMENTING",
                "planned_changes": [{"paths": ["services/shared/**"]}],
            }
        ),
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "first contract")
    second = linked / "docs" / "dev-changes" / "change-b"
    second.mkdir(parents=True)
    (second / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "change_id": "change-b",
                "state": "IMPLEMENTING",
                "planned_changes": [{"paths": ["services/shared/app.py"]}],
            }
        ),
        encoding="utf-8",
    )
    _run(linked, "git", "add", ".")
    _run(linked, "git", "commit", "-qm", "second clean contract")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    scopes = ownership.active_contract_scopes(repo)
    assert {item.change_id for item in scopes} == {"change-a", "change-b"}
    overlaps = ownership.contract_scope_overlaps(scopes)
    assert len(overlaps) == 1
    assert {overlaps[0]["left_change_id"], overlaps[0]["right_change_id"]} == {
        "change-a",
        "change-b",
    }
    report = ownership.inventory_workspace(
        linked, include_primary=False, secret_scope="changed"
    )
    assert report["counts"]["contract_scope_conflict"] == 1
    assert report["counts"]["contract_owner_ambiguity"] == 0
    assert "contract_scope_conflict" in ownership.blocking_ownership_states(
        report["counts"]
    )
    monkeypatch.setattr(ownership, "inventory_workspace", lambda *_args, **_kwargs: report)
    assert ownership.main(["--root", str(linked), "--fail-unassigned"]) == 1


def test_nested_contracts_in_one_worktree_do_not_create_concurrent_owner_conflict(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    for change_id, pattern in (
        ("change-a", "services/shared/**"),
        ("change-b", "services/shared/app.py"),
    ):
        contract = repo / "docs" / "dev-changes" / change_id / "impact.yaml"
        contract.parent.mkdir(parents=True)
        contract.write_text(
            yaml.safe_dump(
                {
                    "change_id": change_id,
                    "state": "IMPLEMENTING",
                    "planned_changes": [{"paths": [pattern]}],
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    scopes = ownership.active_contract_scopes(repo)

    assert {item.change_id for item in scopes} == {"change-a", "change-b"}
    assert ownership.contract_scope_overlaps(scopes) == ()


def test_same_change_id_in_multiple_active_worktrees_is_blocking_ambiguity(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    contract = repo / "docs" / "dev-changes" / "change-a" / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": "change-a",
                "state": "IMPLEMENTING",
                "planned_changes": [{"paths": ["services/a/**"]}],
            }
        ),
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "active contract")
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-q", "-b", "feature", str(linked))
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(
        linked, include_primary=False, secret_scope="changed"
    )

    assert report["counts"]["contract_owner_ambiguity"] == 1
    assert report["counts"]["scope_conflict"] == 1
    assert report["contract_owner_ambiguities"][0]["change_id"] == "change-a"
    assert len(report["contract_owner_ambiguities"][0]["source_worktrees"]) == 2
    assert "contract_owner_ambiguity" in ownership.blocking_ownership_states(
        report["counts"]
    )
    monkeypatch.setattr(ownership, "inventory_workspace", lambda *_args, **_kwargs: report)
    assert ownership.main(["--root", str(linked), "--fail-unassigned"]) == 1


def test_discovered_copy_does_not_claim_paths_or_create_owner_ambiguity(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    contract = repo / "docs" / "dev-changes" / "change-a" / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": "change-a",
                "state": "DISCOVERED",
                "planned_changes": [{"paths": ["services/a/**"]}],
            }
        ),
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "discovery contract")
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-q", "-b", "feature", str(linked))
    linked_contract = linked / "docs" / "dev-changes" / "change-a" / "impact.yaml"
    impact = yaml.safe_load(linked_contract.read_text(encoding="utf-8"))
    impact["state"] = "IMPLEMENTING"
    linked_contract.write_text(yaml.safe_dump(impact), encoding="utf-8")
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})

    report = ownership.inventory_workspace(
        linked, include_primary=False, secret_scope="changed"
    )

    assert report["counts"]["contract_owner_ambiguity"] == 0
    assert report["contract_owner_ambiguities"] == []
    scope = next(item for item in report["active_contracts"] if item["change_id"] == "change-a")
    assert scope["source_worktrees"] == [
        ownership.worktree_id(linked, primary=ownership.primary_worktree(linked))
    ]


def test_only_explicit_trusted_provenance_removes_contract_from_active_ownership(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    contract = repo / "docs" / "dev-changes" / "change-a" / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": "change-a",
                "state": "GRAPH_DIFF_READY",
                "planned_changes": [{"paths": ["services/a/**"]}],
            }
        ),
        encoding="utf-8",
    )
    verifier = object()
    seen: list[object] = []

    def unresolved(*_args, provenance_verifier=None, **_kwargs):
        seen.append(provenance_verifier)
        return {}

    monkeypatch.setattr(ownership, "delivered_contracts", unresolved)

    report = ownership.inventory_workspace(
        repo,
        include_primary=False,
        provenance_verifier=verifier,
        secret_scope="changed",
    )

    assert seen == [verifier]
    assert any(item["change_id"] == "change-a" for item in report["active_contracts"])
    assert report["delivered_contracts"] == []

    def trusted(*_args, provenance_verifier=None, **_kwargs):
        assert provenance_verifier is verifier
        return {"change-a": {"change_id": "change-a", "valid": True}}

    monkeypatch.setattr(ownership, "delivered_contracts", trusted)
    verified = ownership.inventory_workspace(
        repo,
        include_primary=False,
        provenance_verifier=verifier,
        secret_scope="changed",
    )
    assert all(item["change_id"] != "change-a" for item in verified["active_contracts"])
    assert verified["delivered_contracts"][0]["change_id"] == "change-a"


def test_delivery_resolution_receives_the_explicit_provenance_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    verifier = object()
    seen: list[object] = []

    def resolve(_root: Path, _paths, *, provenance_verifier=None):
        seen.append(provenance_verifier)
        return {}

    monkeypatch.setattr(
        ownership,
        "_load_delivery_resolver",
        lambda _root: type("Resolver", (), {"resolve_delivered_contracts": staticmethod(resolve)}),
    )

    assert ownership.delivered_contracts(
        repo,
        [repo / "missing-receipt.json"],
        provenance_verifier=verifier,
    ) == {}
    assert seen == [verifier]


@pytest.mark.parametrize("malformed", [False, None, [], {"valid": True, "reasons": None}])
def test_inventory_keeps_contract_active_when_provenance_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: object
) -> None:
    repo = _repo(tmp_path)
    change_id = "change-a"
    contract = repo / "docs" / "dev-changes" / change_id / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": change_id,
                "state": "GRAPH_DIFF_READY",
                "planned_changes": [{"paths": ["services/a/**"]}],
            }
        ),
        encoding="utf-8",
    )
    receipt = repo / "receipt.json"
    receipt.write_text(json.dumps({"change_id": change_id}), encoding="utf-8")
    resolver_spec = importlib.util.spec_from_file_location(
        "omni_delivery_resolver_fixture", ROOT / "scripts" / "generate_implementation_status.py"
    )
    assert resolver_spec is not None and resolver_spec.loader is not None
    resolver = importlib.util.module_from_spec(resolver_spec)
    sys.modules[resolver_spec.name] = resolver
    resolver_spec.loader.exec_module(resolver)
    monkeypatch.setattr(ownership, "_load_delivery_resolver", lambda _root: resolver)

    report = ownership.inventory_workspace(
        repo,
        include_primary=False,
        attestation_paths=[receipt],
        provenance_verifier=lambda *_args: malformed,
        secret_scope="changed",
    )

    assert report["delivered_contracts"] == []
    assert any(item["change_id"] == change_id for item in report["active_contracts"])


def test_foreign_active_lease_blocks_owned_dirty_path(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-q", "-b", "feature", str(linked))
    contract = linked / "docs" / "dev-changes" / "change-a" / "impact.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        yaml.safe_dump(
            {
                "change_id": "change-a",
                "state": "IMPLEMENTING",
                "planned_changes": [{"paths": ["services/a/**"]}],
            }
        ),
        encoding="utf-8",
    )
    target = linked / "services" / "a" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")
    foreign = {
        "lease_id": "lease-foreign",
        "change_id": "change-b",
        "owner": "agent-b",
        "path_globs": ["services/a/**"],
        "mode": "write",
        "state": "active",
        "effective_state": "active",
    }
    monkeypatch.setattr(
        ownership,
        "delivered_contracts",
        lambda *_args, **_kwargs: {"change-a": {"change_id": "change-a", "valid": True}},
    )
    monkeypatch.setattr(
        ownership, "_runtime_lease_inventory", lambda _root: ((foreign,), (foreign,))
    )

    report = ownership.inventory_workspace(
        linked, include_primary=False, secret_scope="changed"
    )

    fact = next(item for item in report["paths"] if item["path"] == "services/a/app.py")
    assert fact["ownership"] == "unassigned"
    assert fact["lease_conflict"] is True
    assert fact["lease_owners"] == ("change-b@agent-b",)
    assert report["counts"]["lease_conflict"] == 1
    assert "lease_conflict" in ownership.blocking_ownership_states(report["counts"])
    monkeypatch.setattr(ownership, "inventory_workspace", lambda *_args, **_kwargs: report)
    assert ownership.main(["--root", str(linked), "--fail-unassigned"]) == 1


def test_expired_lease_is_retained_for_audit_but_not_used_as_blocker(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    (repo / "service.py").write_text("changed\n", encoding="utf-8")
    stale = {
        "lease_id": "lease-stale",
        "change_id": "old-change",
        "owner": "old-owner",
        "path_globs": ["service.py"],
        "state": "active",
        "effective_state": "stale",
    }
    monkeypatch.setattr(ownership, "delivered_contracts", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(ownership, "_runtime_lease_inventory", lambda _root: ((), (stale,)))

    report = ownership.inventory_workspace(repo, include_primary=True, secret_scope="tracked")
    assert report["counts"]["lease_conflict"] == 0
    assert report["runtime_lease_audit"][0]["effective_state"] == "stale"
    assert ownership.blocking_ownership_states(report["counts"]) == ()
    monkeypatch.setattr(ownership, "inventory_workspace", lambda *_args, **_kwargs: report)
    assert ownership.main(["--root", str(repo), "--fail-unassigned"]) == 0
