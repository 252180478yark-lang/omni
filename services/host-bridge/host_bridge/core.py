"""Provider-neutral, authenticated Host Bridge primitives for S10."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$")


class HostBridgeError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class HostSession:
    session_id: str
    runner_provider: str
    runner_session_id: str | None
    project_dir: str
    execution_id: str | None = None
    parent_span_id: str | None = None
    model: str | None = None
    effort: str | None = None
    trace_id: str | None = None
    status: str = "active"


@dataclass
class HostRun:
    run_id: str
    request_id: str
    session_id: str
    status: str = "accepted"
    process_id: int | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    process: Any = None


class ProviderRunner(Protocol):
    def start(self, session: HostSession, prompt: str, parent_span_id: str | None = None): ...


TraceSink = Callable[[HostSession, str, str, str, dict[str, Any]], bool]
VisibleAuthOpener = Callable[[str], bool]


class SubprocessProviderRunner:
    """Opt-in local provider launcher. It never uses a shell or arbitrary cwd."""

    def __init__(self, commands: dict[str, str], *, mcp_url: str = "", state_dir: Path | None = None) -> None:
        self.commands = commands
        self.mcp_url = mcp_url.rstrip("/")
        self.state_dir = (state_dir or Path(os.getenv("OMNI_HOST_STATE_DIR", "./data/host-bridge"))).resolve()

    @classmethod
    def from_environment(cls) -> "SubprocessProviderRunner | None":
        enabled = os.getenv("OMNI_HOST_EXECUTION_ENABLED", "false").lower() in {"1", "true", "yes"}
        candidates = {"codex": os.getenv("CODEX_CLI_PATH", ""), "claude": os.getenv("CLAUDE_CLI_PATH", "")}
        commands = {provider: str(Path(command).resolve()) for provider, command in candidates.items() if command and Path(command).is_file()}
        mcp_base = os.getenv("OMNI_KE_URL", "").rstrip("/")
        return cls(commands, mcp_url=f"{mcp_base}/mcp" if mcp_base else "") if enabled and commands else None

    def _trace_headers(self, session: HostSession, parent_span_id: str | None) -> dict[str, str]:
        if not session.trace_id:
            return {}
        return {
            "X-Omni-Trace-Id": session.trace_id,
            "X-Omni-Execution-Id": session.execution_id or session.trace_id,
            "X-Omni-Parent-Span-Id": parent_span_id or f"host-session:{session.session_id}",
            "X-Omni-Session-Id": session.session_id,
        }

    def _claude_mcp_config(self, session: HostSession, parent_span_id: str | None) -> str | None:
        headers = self._trace_headers(session, parent_span_id)
        if not self.mcp_url or not headers:
            return None
        directory = self.state_dir / "mcp-config"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{hashlib.sha256(session.session_id.encode()).hexdigest()}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"mcpServers": {"omni": {"type": "http", "url": self.mcp_url, "headers": headers}}}, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
        return str(path)

    def build_command(self, session: HostSession, prompt: str, parent_span_id: str | None = None) -> list[str]:
        command = self.commands.get(session.runner_provider)
        if not command:
            raise HostBridgeError("host_runner_not_configured", 503)
        if session.runner_provider == "codex":
            args = [command, "exec"]
            if session.runner_session_id:
                args.extend(["resume", session.runner_session_id])
            else:
                args.extend(["-C", session.project_dir, "--sandbox", "danger-full-access"])
            args.extend(["--json", "--skip-git-repo-check"])
            if session.model:
                args.extend(["--model", session.model])
            if session.effort:
                args.extend(["--config", f'model_reasoning_effort="{session.effort}"'])
            headers = self._trace_headers(session, parent_span_id)
            if self.mcp_url and headers:
                args.extend(["--config", f'mcp_servers.omni.url="{self.mcp_url}"'])
                inline = ",".join(f'"{key}"="{value}"' for key, value in sorted(headers.items()))
                args.extend(["--config", f"mcp_servers.omni.http_headers={{{inline}}}"])
            return [*args, prompt]
        args = [command, "-p", prompt, "--output-format", "stream-json", "--verbose"]
        mcp_config = self._claude_mcp_config(session, parent_span_id)
        if mcp_config:
            args.extend(["--mcp-config", mcp_config])
        if session.runner_session_id:
            args.extend(["--resume", session.runner_session_id])
        if session.model:
            args.extend(["--model", session.model])
        if session.effort:
            args.extend(["--effort", session.effort])
        return args

    def start(self, session: HostSession, prompt: str, parent_span_id: str | None = None):
        return subprocess.Popen(
            self.build_command(session, prompt, parent_span_id), cwd=session.project_dir, shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )


class HostLease:
    """Atomic singleton file. A second live Host never replaces its owner."""

    def __init__(self, state_dir: Path, instance_id: str) -> None:
        self.path = state_dir / "host-bridge.lock"
        self.instance_id = instance_id
        self.token = secrets.token_hex(16)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"instance_id": self.instance_id, "token": self.token, "pid": os.getpid()})
        try:
            with self.path.open("x", encoding="utf-8") as handle:
                handle.write(payload)
        except FileExistsError as exc:
            raise HostBridgeError("host_bridge_allocation_held", 409) from exc

    def release(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("token") == self.token:
            self.path.unlink(missing_ok=True)


class HostBridge:
    def __init__(
        self,
        *,
        state_dir: Path,
        allow_roots: list[Path],
        instance_id: str,
        build_identity: dict[str, str | None] | None = None,
        runner: ProviderRunner | None = None,
        trace_sink: TraceSink | None = None,
        visible_auth_origins: set[str] | None = None,
        visible_auth_opener: VisibleAuthOpener | None = None,
    ) -> None:
        self.state_dir = state_dir.resolve()
        self.allow_roots = [root.resolve() for root in allow_roots]
        self.instance_id = instance_id
        self.build_identity = build_identity or {}
        self.runner = runner
        self.trace_sink = trace_sink
        self.visible_auth_origins = {
            origin for value in (visible_auth_origins or set())
            if (origin := self._https_origin(value, configuration=True)) is not None
        }
        self.visible_auth_opener = visible_auth_opener
        self.lease = HostLease(self.state_dir, instance_id)
        self._session_path = self.state_dir / "sessions.json"
        self._runs: dict[str, HostRun] = {}
        self._requests: dict[tuple[str, str, str], str] = {}
        self._lock = threading.RLock()
        self._started_at = datetime.now(timezone.utc)

    def start(self) -> None:
        self.lease.acquire()

    def stop(self) -> None:
        with self._lock:
            for run in self._runs.values():
                if run.status in {"accepted", "running"} and run.process is not None:
                    self._terminate(run.process)
        self.lease.release()

    def health(self) -> dict[str, Any]:
        runner_configured = self.runner is not None
        visible_auth_configured = bool(self.visible_auth_origins and self.visible_auth_opener)
        capabilities = ["attachment.upload", "attachment.download", "project.policy"]
        if runner_configured:
            capabilities.extend(["session.create", "session.resume", "run.events", "run.cancel"])
        if visible_auth_configured:
            capabilities.append("visible_auth.open")
        reasons = []
        if not runner_configured:
            reasons.append("host_provider_runner_unconfigured")
        if not visible_auth_configured:
            reasons.append("host_visible_auth_unconfigured")
        return {
            "state": "healthy" if not reasons else "degraded",
            "instance_id": self.instance_id,
            "capabilities": capabilities,
            "build_identity": self.build_identity,
            "reason_codes": reasons,
            "started_at": self._started_at.isoformat(),
        }

    @staticmethod
    def _https_origin(raw: str, *, configuration: bool = False) -> str | None:
        try:
            parsed = urlsplit(raw.strip())
            if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
                return None
            if configuration and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                return None
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            return None
        return f"https://{parsed.hostname.lower()}{port}"

    def _validate_project_dir(self, raw: str) -> str:
        try:
            candidate = Path(raw).resolve(strict=True)
        except OSError as exc:
            raise HostBridgeError("project_dir_unavailable", 404) from exc
        if not self.allow_roots or not any(candidate.is_relative_to(root) for root in self.allow_roots):
            raise HostBridgeError("project_dir_not_allowlisted", 403)
        if not (candidate / "AGENTS.md").is_file():
            raise HostBridgeError("project_rules_missing", 422)
        return str(candidate)

    def _read_sessions(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self._session_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            raise HostBridgeError("host_session_store_invalid", 503) from exc

    def _write_sessions(self, sessions: dict[str, dict[str, Any]]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp = self._session_path.with_suffix(".tmp")
        temp.write_text(json.dumps(sessions, sort_keys=True), encoding="utf-8")
        os.replace(temp, self._session_path)

    def ensure_session(self, session: HostSession) -> HostSession:
        identifiers = (session.session_id, session.runner_session_id, session.trace_id, session.execution_id, session.parent_span_id)
        if any(value is not None and not IDENTIFIER.fullmatch(value) for value in identifiers):
            raise HostBridgeError("invalid_session_identifier", 422)
        if session.runner_provider not in {"codex", "claude"}:
            raise HostBridgeError("unsupported_runner_provider", 422)
        normalized = HostSession(**{**asdict(session), "project_dir": self._validate_project_dir(session.project_dir)})
        with self._lock:
            sessions = self._read_sessions()
            existing = sessions.get(normalized.session_id)
            if existing and existing.get("runner_session_id") and normalized.runner_session_id and existing["runner_session_id"] != normalized.runner_session_id:
                raise HostBridgeError("session_runner_identity_conflict", 409)
            if existing and existing.get("runner_session_id") and existing.get("runner_provider") != normalized.runner_provider:
                raise HostBridgeError("session_runner_provider_conflict", 409)
            if existing:
                merged = {**existing, **{key: value for key, value in asdict(normalized).items() if value is not None}}
                if normalized.trace_id and normalized.trace_id != existing.get("trace_id") and session.parent_span_id is None:
                    merged["parent_span_id"] = None
                normalized = HostSession(**merged)
            sessions[normalized.session_id] = asdict(normalized)
            self._write_sessions(sessions)
        return normalized

    def get_session(self, session_id: str) -> HostSession:
        if not IDENTIFIER.fullmatch(session_id):
            raise HostBridgeError("invalid_session_identifier", 422)
        with self._lock:
            record = self._read_sessions().get(session_id)
        if record is None:
            raise HostBridgeError("session_not_found", 404)
        return HostSession(**record)

    def start_run(self, session_id: str, prompt: str, request_id: str) -> dict[str, Any]:
        if not prompt.strip() or len(prompt) > 32_000:
            raise HostBridgeError("invalid_prompt", 422)
        if not IDENTIFIER.fullmatch(request_id):
            raise HostBridgeError("invalid_request_identifier", 422)
        if self.runner is None:
            raise HostBridgeError("host_provider_runner_unconfigured", 503)
        session = self.get_session(session_id)
        with self._lock:
            request_key = ("provider-run", session_id, request_id)
            previous = self._requests.get(request_key)
            if previous:
                return self._run_response(self._runs[previous], duplicate=True)
            run = HostRun(run_id=f"run:{uuid.uuid4().hex}", request_id=request_id, session_id=session_id)
            self._runs[run.run_id] = run
            self._requests[request_key] = run.run_id
        try:
            process = self.runner.start(session, prompt, run.run_id)
        except HostBridgeError:
            with self._lock:
                run.status = "failed"
            raise
        except OSError as exc:
            with self._lock:
                run.status = "failed"
            raise HostBridgeError("host_runner_start_failed", 503) from exc
        with self._lock:
            run.process = process
            run.process_id = int(process.pid)
            run.status = "running"
            self._append(run, "host.run.started", {"provider": session.runner_provider})
        self._emit_trace(session, run, "started", "running", {"provider": session.runner_provider})
        threading.Thread(target=self._read_stdout, args=(run, session), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(run,), daemon=True).start()
        threading.Thread(target=self._wait, args=(run, session), daemon=True).start()
        return self._run_response(run, duplicate=False)

    def open_visible_auth(self, session_id: str, provider: str, url: str, request_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", provider):
            raise HostBridgeError("visible_auth_provider_invalid", 422)
        if not IDENTIFIER.fullmatch(request_id):
            raise HostBridgeError("invalid_request_identifier", 422)
        origin = self._https_origin(url)
        if origin is None or origin not in self.visible_auth_origins:
            raise HostBridgeError("visible_auth_origin_not_allowlisted", 403)
        if self.visible_auth_opener is None:
            raise HostBridgeError("host_visible_auth_unconfigured", 503)
        session = self.get_session(session_id)
        request_key = ("visible-auth", session_id, request_id)
        with self._lock:
            previous = self._requests.get(request_key)
            if previous:
                previous_run = self._runs[previous]
                if previous_run.status != "completed":
                    raise HostBridgeError("visible_auth_open_failed", 503)
                return self._visible_auth_response(previous_run, provider, duplicate=True)
            run = HostRun(run_id=f"visible-auth:{uuid.uuid4().hex}", request_id=request_id, session_id=session_id, status="running")
            self._runs[run.run_id] = run
            self._requests[request_key] = run.run_id
            self._append(run, "host.visible_auth.started", {"provider": provider})
        self._emit_trace(session, run, "started", "running", {"capability": "visible_auth", "provider": provider})
        try:
            opened = bool(self.visible_auth_opener(url))
        except Exception:
            opened = False
        with self._lock:
            run.status = "completed" if opened else "failed"
            self._append(
                run,
                "host.visible_auth.opened" if opened else "host.visible_auth.failed",
                {"provider": provider, **({} if opened else {"reason": "visible_auth_open_failed"})},
            )
        self._emit_trace(
            session, run, "completed" if opened else "failed", run.status,
            {"capability": "visible_auth", "provider": provider, **({} if opened else {"reason": "visible_auth_open_failed"})},
        )
        if not opened:
            raise HostBridgeError("visible_auth_open_failed", 503)
        return self._visible_auth_response(run, provider, duplicate=False)

    def _visible_auth_response(self, run: HostRun, provider: str, *, duplicate: bool) -> dict[str, Any]:
        return {
            "accepted": run.status == "completed", "duplicate": duplicate,
            "run_id": run.run_id, "session_id": run.session_id,
            "provider": provider, "status": run.status,
        }

    def _append(self, run: HostRun, kind: str, payload: dict[str, Any]) -> None:
        run.events.append({"cursor": len(run.events) + 1, "kind": kind, "payload": payload, "observed_at": datetime.now(timezone.utc).isoformat()})

    def _read_stdout(self, run: HostRun, session: HostSession) -> None:
        if run.process.stdout is None:
            return
        for line in run.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                with self._lock:
                    self._append(run, "host.output.unparsed", {"reason": "provider_non_json_output"})
                continue
            if not isinstance(chunk, dict):
                with self._lock:
                    self._append(run, "host.output.unparsed", {"reason": "provider_non_object_output"})
                continue
            runner_session_id = chunk.get("thread_id") if chunk.get("type") == "thread.started" else chunk.get("session_id") if chunk.get("type") == "system" else None
            if isinstance(runner_session_id, str) and IDENTIFIER.fullmatch(runner_session_id):
                self._persist_runner_session(session.session_id, runner_session_id)
            with self._lock:
                self._append(run, "provider.chunk", {"chunk": chunk})

    def _read_stderr(self, run: HostRun) -> None:
        if run.process.stderr is None:
            return
        for _line in run.process.stderr:
            with self._lock:
                self._append(run, "host.provider.stderr", {"redacted": True})

    def _wait(self, run: HostRun, session: HostSession) -> None:
        code = int(run.process.wait())
        with self._lock:
            if run.status == "cancelled":
                status, kind = "cancelled", "host.run.cancelled"
            elif code == 0:
                status, kind = "completed", "host.run.completed"
            else:
                status, kind = "failed", "host.run.failed"
            run.status = status
            self._append(run, kind, {"exit_code": code})
        self._emit_trace(session, run, "cancelled" if status == "cancelled" else "completed" if status == "completed" else "failed", status, {"exit_code": code})

    def _persist_runner_session(self, session_id: str, runner_session_id: str) -> None:
        with self._lock:
            sessions = self._read_sessions()
            record = sessions.get(session_id)
            if record is None or record.get("runner_session_id") == runner_session_id:
                return
            if record.get("runner_session_id"):
                return
            record["runner_session_id"] = runner_session_id
            sessions[session_id] = record
            self._write_sessions(sessions)

    def _emit_trace(self, session: HostSession, run: HostRun, event_type: str, status: str, payload: dict[str, Any]) -> None:
        if self.trace_sink is None or not session.trace_id:
            return
        try:
            ok = self.trace_sink(session, run.run_id, event_type, status, payload)
        except Exception:
            ok = False
        if not ok:
            with self._lock:
                self._append(run, "host.trace.gap", {"reason": "runtime_trace_append_failed"})

    def _run_response(self, run: HostRun, *, duplicate: bool) -> dict[str, Any]:
        session = self.get_session(run.session_id)
        return {
            "accepted": run.status in {"accepted", "running"}, "duplicate": duplicate,
            "run_id": run.run_id, "status": run.status, "session_id": run.session_id,
            "runner_session_id": session.runner_session_id, "trace_id": session.trace_id,
            "execution_id": session.execution_id, "parent_span_id": session.parent_span_id,
            "process_id": run.process_id,
        }

    def run_events(self, run_id: str, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise HostBridgeError("host_run_not_found", 404)
            events = [event for event in run.events if int(event["cursor"]) > cursor]
            return {"run_id": run_id, "session_id": run.session_id, "status": run.status, "events": events, "next_cursor": events[-1]["cursor"] if events else cursor}

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise HostBridgeError("host_run_not_found", 404)
            if run.status not in {"accepted", "running"}:
                return {"run_id": run_id, "status": run.status, "already_terminal": True}
            run.status = "cancelled"
            process = run.process
        if process is not None:
            self._terminate(process)
        return {"run_id": run_id, "status": "cancelled", "already_terminal": False}

    @staticmethod
    def _terminate(process) -> None:
        try:
            process.terminate()
        except OSError:
            return

    def save_attachment(self, session_id: str, name: str, content: bytes, content_type: str) -> dict[str, Any]:
        self.get_session(session_id)
        if not content_type or len(content_type) > 200 or len(content) > 25 * 1024 * 1024:
            raise HostBridgeError("attachment_rejected", 422)
        digest = hashlib.sha256(content).hexdigest()
        suffix = Path(name).suffix.lower()
        if suffix and not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            raise HostBridgeError("attachment_name_invalid", 422)
        store = self.state_dir / "attachments"
        store.mkdir(parents=True, exist_ok=True)
        storage_key = f"sha256/{digest}"
        target = store / digest
        if not target.exists():
            temporary = store / f".{digest}.{uuid.uuid4().hex}.tmp"
            temporary.write_bytes(content)
            os.replace(temporary, target)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise HostBridgeError("attachment_store_checksum_mismatch", 503)
        attachment_key = hashlib.sha256(f"{session_id}\0{digest}".encode()).hexdigest()[:32]
        metadata = {"attachment_id": f"attachment:{attachment_key}", "session_id": session_id, "sha256": digest, "size_bytes": len(content), "content_type": content_type, "storage_key": storage_key, "path": str(target)}
        with self._lock:
            index = self._read_attachment_index()
            index[metadata["attachment_id"]] = metadata
            self._write_attachment_index(index)
        return {key: value for key, value in metadata.items() if key not in {"path", "session_id"}}

    def attachment(self, session_id: str, attachment_id: str) -> tuple[Path, dict[str, Any]]:
        self.get_session(session_id)
        with self._lock:
            metadata = self._read_attachment_index().get(attachment_id)
        if metadata is None or metadata.get("session_id") != session_id:
            raise HostBridgeError("attachment_not_found", 404)
        path = Path(metadata["path"]).resolve()
        if not path.is_relative_to((self.state_dir / "attachments").resolve()) or not path.is_file():
            raise HostBridgeError("attachment_not_found", 404)
        return path, metadata

    def _read_attachment_index(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads((self.state_dir / "attachments.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_attachment_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / "attachments.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
