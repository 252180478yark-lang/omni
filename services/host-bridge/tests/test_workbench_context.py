import io
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host_bridge.app import as_public_session
from host_bridge.core import HostBridge, HostBridgeError, HostSession


class BlockingProcess:
    pid = 9911

    def __init__(self):
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.released = threading.Event()
        self.terminated = False

    def wait(self):
        self.released.wait(timeout=2)
        return -15 if self.terminated else 0

    def terminate(self):
        self.terminated = True
        self.released.set()


class BlockingRunner:
    def __init__(self):
        self.process = BlockingProcess()

    def start(self, _session, _prompt, _parent_span_id=None):
        return self.process


def make_bridge(tmp_path: Path, runner=None):
    project = tmp_path / "projects" / "omni"
    project.mkdir(parents=True)
    (project / "AGENTS.md").write_text("rules", encoding="utf-8")
    return HostBridge(
        state_dir=tmp_path / "state", allow_roots=[project.parent],
        instance_id="host:test", runner=runner,
    ), project


def test_public_session_uses_opaque_identity_and_never_returns_project_path(tmp_path):
    bridge, project = make_bridge(tmp_path)
    session = bridge.ensure_session(HostSession(
        session_id="session:opaque", runner_provider="codex", runner_session_id=None,
        project_dir=str(project), context_snapshot_id="context:sku-a", context_revision=1,
        requested_provider="codex", resolved_provider="codex",
    ))

    public = as_public_session(session)
    assert "project_dir" not in public
    assert public["project"]["project_handle"].startswith("project:")
    assert public["project"]["project_hash"].startswith("sha256:")
    assert str(project) not in str(public)


def test_context_rebind_is_cas_and_each_run_keeps_its_frozen_pair(tmp_path):
    runner = BlockingRunner()
    bridge, project = make_bridge(tmp_path, runner)
    bridge.ensure_session(HostSession(
        "session:context", "codex", None, str(project),
        context_snapshot_id="context:sku-a", context_revision=1,
    ))
    first = bridge.start_run("session:context", "analyze sku a", "request:first")
    rebound = bridge.rebind_context(
        "session:context", expected_snapshot_id="context:sku-a", expected_revision=1,
        next_snapshot_id="context:sku-b", next_revision=2,
    )

    assert first["context_snapshot_id"] == "context:sku-a" and first["context_revision"] == 1
    assert rebound.current_context_snapshot_id == "context:sku-b" and rebound.current_context_revision == 2
    with pytest.raises(HostBridgeError, match="context_rebind_conflict"):
        bridge.rebind_context(
            "session:context", expected_snapshot_id="context:sku-a", expected_revision=1,
            next_snapshot_id="context:sku-c", next_revision=2,
        )
    runner.process.terminate()


def test_restart_restores_active_run_as_paused_with_recovery_event(tmp_path):
    runner = BlockingRunner()
    bridge, project = make_bridge(tmp_path, runner)
    bridge.ensure_session(HostSession(
        "session:recovery", "codex", None, str(project),
        context_snapshot_id="context:sku-a", context_revision=1,
    ))
    run = bridge.start_run("session:recovery", "continue", "request:recovery")

    restored = HostBridge(
        state_dir=tmp_path / "state", allow_roots=[project.parent],
        instance_id="host:restored", runner=None,
    )
    page = restored.run_events(run["run_id"])

    assert page["status"] == "paused"
    assert page["events"][-1]["kind"] == "host.run.paused"
    assert page["events"][-1]["payload"]["reason"] == "host_restarted"
    runner.process.terminate()


def test_provider_contract_is_immutable_after_acceptance(tmp_path):
    runner = BlockingRunner()
    bridge, project = make_bridge(tmp_path, runner)
    bridge.ensure_session(HostSession(
        "session:provider", "codex", None, str(project),
        requested_provider="auto", resolved_provider="codex",
    ))
    bridge.start_run("session:provider", "accept", "request:provider")

    with pytest.raises(HostBridgeError, match="session_runner_provider_conflict"):
        bridge.ensure_session(HostSession(
            "session:provider", "claude", None, str(project),
            requested_provider="auto", resolved_provider="claude",
        ))
    runner.process.terminate()
