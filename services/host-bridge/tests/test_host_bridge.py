import io
from pathlib import Path
import sys
import time
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host_bridge.core import HostBridge, HostBridgeError, HostSession, SubprocessProviderRunner


class FakeProcess:
    _next_pid = 4000

    def __init__(self, lines=None, code=0):
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self.stdout = io.StringIO("".join(f"{line}\n" for line in (lines or [])))
        self.stderr = io.StringIO("")
        self.code = code
        self.terminated = False

    def wait(self):
        return -15 if self.terminated else self.code

    def terminate(self):
        self.terminated = True


class FakeRunner:
    def __init__(self, lines=None, code=0):
        self.lines = lines or ['{"type":"thread.started","thread_id":"runner:real"}', '{"type":"turn.completed"}']
        self.code = code
        self.prompts = []

    def start(self, session, prompt, _parent_span_id=None):
        self.prompts.append((session, prompt))
        return FakeProcess(self.lines, self.code)


class BlockingProcess(FakeProcess):
    def __init__(self):
        super().__init__([])
        self.released = threading.Event()

    def wait(self):
        self.released.wait(timeout=1)
        return -15 if self.terminated else 0

    def terminate(self):
        self.terminated = True
        self.released.set()


class BlockingRunner:
    def __init__(self): self.process = BlockingProcess()
    def start(self, _session, _prompt, _parent_span_id=None): return self.process


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "projects" / "allowed"
    project.mkdir(parents=True)
    (project / "AGENTS.md").write_text("rules", encoding="utf-8")
    return project


def session(project: Path, runner_id="runner:one") -> HostSession:
    return HostSession(
        "session:one", "codex", runner_id, str(project),
        execution_id="execution:one", parent_span_id="ws:execution:one", trace_id="trace:one",
    )


def bridge_for(tmp_path: Path, runner=None, trace_sink=None):
    project = make_project(tmp_path)
    bridge = HostBridge(state_dir=tmp_path / "state", allow_roots=[project.parent], instance_id="host:one", runner=runner or FakeRunner(), trace_sink=trace_sink)
    return bridge, project


def wait_terminal(bridge: HostBridge, run_id: str):
    for _ in range(100):
        page = bridge.run_events(run_id)
        if page["status"] in {"completed", "failed", "cancelled"}:
            return page
        time.sleep(0.005)
    raise AssertionError("run did not finish")


def test_second_host_does_not_take_singleton_allocation(tmp_path):
    bridge, project = bridge_for(tmp_path)
    second = HostBridge(state_dir=tmp_path / "state", allow_roots=[project.parent], instance_id="host:second", runner=FakeRunner())
    bridge.start()
    with pytest.raises(HostBridgeError, match="host_bridge_allocation_held"):
        second.start()
    bridge.stop()


def test_run_preserves_cwd_trace_real_runner_id_and_request_idempotency(tmp_path):
    emitted = []
    bridge, project = bridge_for(tmp_path, trace_sink=lambda *args: emitted.append(args) is None)
    bridge.ensure_session(session(project, runner_id=None))
    first = bridge.start_run("session:one", "continue", "request:one")
    duplicate = bridge.start_run("session:one", "continue", "request:one")
    page = wait_terminal(bridge, first["run_id"])
    assert duplicate["run_id"] == first["run_id"] and duplicate["duplicate"] is True
    assert bridge.get_session("session:one").runner_session_id == "runner:real"
    assert [event["cursor"] for event in page["events"]] == list(range(1, len(page["events"]) + 1))
    assert page["status"] == "completed"
    assert all("continue" not in str(event) for event in page["events"])
    assert all(args[0].execution_id == "execution:one" and args[0].parent_span_id == "ws:execution:one" for args in emitted)


def test_restart_resumes_persisted_real_runner_and_cancel_is_terminal(tmp_path):
    first, project = bridge_for(tmp_path)
    first.ensure_session(session(project))
    blocking = BlockingRunner()
    restarted = HostBridge(state_dir=tmp_path / "state", allow_roots=[project.parent], instance_id="host:two", runner=blocking)
    run = restarted.start_run("session:one", "continue", "request:cancel")
    cancelled = restarted.cancel_run(run["run_id"])
    page = wait_terminal(restarted, run["run_id"])
    assert blocking.process.terminated is True
    assert cancelled["status"] == "cancelled" and page["status"] == "cancelled"
    assert restarted.get_session("session:one").runner_session_id == "runner:one"


def test_rejects_path_escape_and_records_downloadable_attachment_checksum(tmp_path):
    bridge, project = bridge_for(tmp_path)
    with pytest.raises(HostBridgeError, match="project_dir_not_allowlisted"):
        bridge.ensure_session(HostSession("session:bad", "codex", None, str(tmp_path)))
    bridge.ensure_session(session(project))
    attachment = bridge.save_attachment("session:one", "input.txt", b"safe attachment", "text/plain")
    path, metadata = bridge.attachment("session:one", attachment["attachment_id"])
    bridge.ensure_session(HostSession("session:two", "codex", None, str(project)))
    same_content = bridge.save_attachment("session:two", "input.txt", b"safe attachment", "text/plain")
    assert attachment["sha256"] == "4c3fa86f0af3c86f4882c1a228cf43c848be601b86039e4160a8c0d641102d06"
    assert path.read_bytes() == b"safe attachment" and metadata["session_id"] == "session:one"
    assert same_content["sha256"] == attachment["sha256"]
    assert same_content["storage_key"] == attachment["storage_key"]
    assert same_content["attachment_id"] != attachment["attachment_id"]
    assert "safe attachment" not in str(attachment)


def test_opt_in_runner_builds_new_and_resume_argument_vectors_without_shell(tmp_path):
    project = make_project(tmp_path)
    executable = tmp_path / "codex.exe"
    executable.write_text("fixture", encoding="utf-8")
    runner = SubprocessProviderRunner({"codex": str(executable)}, mcp_url="http://ke.test/mcp", state_dir=tmp_path / "state")
    resume = runner.build_command(session(project), "continue safely", "run:one")
    fresh = runner.build_command(session(project, runner_id=None), "start safely", "run:two")
    assert resume[1:4] == ["exec", "resume", "runner:one"]
    assert "-C" in fresh and "--sandbox" in fresh
    assert resume[-1] == "continue safely" and fresh[-1] == "start safely"
    assert any("X-Omni-Trace-Id" in arg and "trace:one" in arg for arg in resume)
    assert any("X-Omni-Execution-Id" in arg and "execution:one" in arg for arg in resume)

    claude = tmp_path / "claude.exe"
    claude.write_text("fixture", encoding="utf-8")
    claude_runner = SubprocessProviderRunner({"claude": str(claude)}, mcp_url="http://ke.test/mcp", state_dir=tmp_path / "state")
    claude_session = HostSession("session:claude", "claude", None, str(project), trace_id="trace:claude")
    command = claude_runner.build_command(claude_session, "hello", "run:claude")
    config_path = Path(command[command.index("--mcp-config") + 1])
    config = config_path.read_text(encoding="utf-8")
    assert "trace:claude" in config and "run:claude" in config and "hello" not in config


def test_visible_auth_is_https_allowlisted_idempotent_and_redacted(tmp_path):
    opened = []
    emitted = []
    project = make_project(tmp_path)
    bridge = HostBridge(
        state_dir=tmp_path / "state", allow_roots=[project.parent], instance_id="host:visible",
        runner=FakeRunner(), trace_sink=lambda *args: emitted.append(args) is None,
        visible_auth_origins={"https://login.example.test"},
        visible_auth_opener=lambda url: opened.append(url) is None,
    )
    bridge.ensure_session(session(project))
    first = bridge.open_visible_auth(
        "session:one", "wecom", "https://login.example.test/qr?ticket=secret-value", "request:visible",
    )
    duplicate = bridge.open_visible_auth(
        "session:one", "wecom", "https://login.example.test/qr?ticket=secret-value", "request:visible",
    )
    events = bridge.run_events(first["run_id"])["events"]

    assert first["status"] == "completed" and duplicate["duplicate"] is True
    assert opened == ["https://login.example.test/qr?ticket=secret-value"]
    assert "visible_auth.open" in bridge.health()["capabilities"]
    assert "secret-value" not in str(first) and "secret-value" not in str(events) and "secret-value" not in str(emitted)
    with pytest.raises(HostBridgeError, match="visible_auth_origin_not_allowlisted"):
        bridge.open_visible_auth("session:one", "wecom", "https://evil.example/qr", "request:evil")
    with pytest.raises(HostBridgeError, match="visible_auth_origin_not_allowlisted"):
        bridge.open_visible_auth("session:one", "wecom", "http://login.example.test/qr", "request:http")


def test_visible_auth_failure_is_not_retried_and_origin_config_is_exact(tmp_path):
    attempts = []
    project = make_project(tmp_path)
    bridge = HostBridge(
        state_dir=tmp_path / "state", allow_roots=[project.parent], instance_id="host:visible-failure",
        runner=FakeRunner(), visible_auth_origins={"https://login.example.test"},
        visible_auth_opener=lambda url: attempts.append(url) is not None,
    )
    bridge.ensure_session(session(project))
    for _ in range(2):
        with pytest.raises(HostBridgeError, match="visible_auth_open_failed"):
            bridge.open_visible_auth("session:one", "wecom", "https://login.example.test/qr", "request:failed")
    assert attempts == ["https://login.example.test/qr"]

    invalid_config = HostBridge(
        state_dir=tmp_path / "other-state", allow_roots=[project.parent], instance_id="host:invalid-origin",
        runner=FakeRunner(), visible_auth_origins={"https://login.example.test/restricted"},
        visible_auth_opener=lambda _url: True,
    )
    assert "visible_auth.open" not in invalid_config.health()["capabilities"]
