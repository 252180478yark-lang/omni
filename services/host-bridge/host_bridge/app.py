"""Authenticated HTTP surface for the locally owned S10 Host Bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .core import HostBridge, HostBridgeError, HostSession, SubprocessProviderRunner


def _build_identity() -> dict[str, str | None]:
    config = {
        "allowed_roots": sorted(item for item in os.getenv("OMNI_HOST_ALLOWED_PROJECT_ROOTS", "").split(os.pathsep) if item),
        "execution_enabled": os.getenv("OMNI_HOST_EXECUTION_ENABLED", "false").lower(),
        "providers": sorted(provider for provider, key in (("codex", "CODEX_CLI_PATH"), ("claude", "CLAUDE_CLI_PATH")) if os.getenv(key)),
        "visible_auth_origins": sorted(item.strip() for item in os.getenv("OMNI_HOST_VISIBLE_AUTH_ORIGINS", "").split(",") if item.strip()),
    }
    return {
        "build_commit": os.getenv("OMNI_BUILD_COMMIT"),
        "image_digest": os.getenv("OMNI_IMAGE_DIGEST"),
        "worktree_id": os.getenv("OMNI_WORKTREE_ID"),
        "allocation_id": os.getenv("OMNI_ALLOCATION_ID"),
        "config_hash": "sha256:" + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "migration_head": os.getenv("OMNI_MIGRATION_HEAD"),
    }


def _trace_sink(session: HostSession, run_id: str, event_type: str, status: str, payload: dict[str, Any]) -> bool:
    base = os.getenv("OMNI_KE_URL", "").rstrip("/")
    token_path = os.getenv("OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE", "") or os.getenv("OMNI_RUNTIME_TRACE_TOKEN_FILE", "")
    if not base or not token_path or not session.trace_id:
        return False
    try:
        token = Path(token_path).read_text(encoding="utf-8").strip()
        if len(token) < 24:
            return False
        body = json.dumps({
            "source": "host.bridge", "event_id": f"{run_id}:{event_type}",
            "trace_id": session.trace_id, "execution_id": session.execution_id or session.trace_id,
            "span_id": run_id, "parent_span_id": session.parent_span_id,
            "event_type": event_type, "status": status,
            "span_kind": "host", "node_id": "service:host-bridge", "read_write": "none",
            "payload": payload,
        }).encode()
        request = urllib.request.Request(
            f"{base}/api/v1/runtime-traces/{urllib.parse.quote(session.trace_id, safe='')}/events",
            data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _contract_post(path: str, payload: dict[str, Any]) -> bool:
    base = os.getenv("OMNI_KE_URL", "").rstrip("/")
    token_path = os.getenv("OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE", "") or os.getenv("OMNI_RUNTIME_TRACE_TOKEN_FILE", "")
    if not base or not token_path:
        return False
    try:
        token = Path(token_path).read_text(encoding="utf-8").strip()
        if len(token) < 24:
            return False
        request = urllib.request.Request(
            f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _sync_session(session: HostSession) -> bool:
    public = as_public_session(session)
    return _contract_post("/api/v1/agent-contracts/sessions", {
        key: public[key] for key in (
            "session_id", "runner_provider", "runner_session_id", "project_dir",
            "model", "effort", "trace_id", "status",
        )
    })


def _sync_attachment(session_id: str, metadata: dict[str, Any]) -> bool:
    return _contract_post(f"/api/v1/agent-contracts/sessions/{urllib.parse.quote(session_id, safe='')}/attachments", {"session_id": session_id, **metadata})


def _bridge() -> HostBridge:
    roots = [Path(item) for item in os.getenv("OMNI_HOST_ALLOWED_PROJECT_ROOTS", "").split(os.pathsep) if item]
    visible_auth_origins = {item.strip() for item in os.getenv("OMNI_HOST_VISIBLE_AUTH_ORIGINS", "").split(",") if item.strip()}
    return HostBridge(
        state_dir=Path(os.getenv("OMNI_HOST_STATE_DIR", "./data/host-bridge")), allow_roots=roots,
        instance_id=os.getenv("OMNI_HOST_INSTANCE_ID", "host:local"), build_identity=_build_identity(),
        runner=SubprocessProviderRunner.from_environment(), trace_sink=_trace_sink,
        visible_auth_origins=visible_auth_origins,
        visible_auth_opener=lambda url: bool(webbrowser.open_new_tab(url)),
    )


bridge = _bridge()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bridge.start()
    try:
        yield
    finally:
        bridge.stop()


app = FastAPI(title="omni-host-bridge", lifespan=lifespan)


def _required_token() -> str:
    path = os.getenv("OMNI_HOST_TOKEN_FILE", "")
    try:
        token = Path(path).read_text(encoding="utf-8").strip() if path else ""
    except OSError:
        token = ""
    if len(token) < 24:
        raise HTTPException(status_code=503, detail={"code": "host_auth_unconfigured"})
    return token


def require_host_access(authorization: str | None = Header(default=None)) -> None:
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not supplied or not hmac.compare_digest(supplied, _required_token()):
        raise HTTPException(status_code=401, detail={"code": "host_auth_required"})


class SessionPayload(BaseModel):
    session_id: str = Field(min_length=2, max_length=200)
    runner_provider: str
    runner_session_id: str | None = Field(default=None, min_length=2, max_length=200)
    project_dir: str = Field(min_length=1, max_length=1024)
    execution_id: str | None = Field(default=None, min_length=2, max_length=200)
    parent_span_id: str | None = Field(default=None, min_length=2, max_length=200)
    model: str | None = None
    effort: str | None = None
    trace_id: str | None = None


class RunPayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    request_id: str = Field(min_length=2, max_length=200)


class VisibleAuthPayload(BaseModel):
    provider: str = Field(min_length=2, max_length=64)
    url: str = Field(min_length=8, max_length=4096)
    request_id: str = Field(min_length=2, max_length=200)


class LegacyCreatePayload(BaseModel):
    title: str = Field(default="Agent session", max_length=200)
    project_dir: str | None = Field(default=None, max_length=1024)
    session_id: str | None = Field(default=None, min_length=2, max_length=200)
    brain_provider: str = "codex"


class LegacyPromptPayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    brain_provider: str = "codex"
    model: str | None = None
    effort: str | None = None
    trace_id: str | None = None
    execution_id: str | None = None
    parent_span_id: str | None = None
    request_id: str | None = None


def _call(action):
    try:
        return action()
    except HostBridgeError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from exc


@app.get("/api/v1/host-bridge/health")
async def health() -> dict[str, Any]:
    value = bridge.health()
    if not os.getenv("OMNI_KE_URL") or not (os.getenv("OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE") or os.getenv("OMNI_RUNTIME_TRACE_TOKEN_FILE")):
        value["state"] = "degraded"
        value["reason_codes"] = [*value["reason_codes"], "core_contract_sync_unconfigured"]
    return value


@app.post("/api/v1/host-bridge/sessions", dependencies=[Depends(require_host_access)])
async def create_session(payload: SessionPayload) -> dict[str, Any]:
    session = _call(lambda: bridge.ensure_session(HostSession(**payload.model_dump())))
    return {**as_public_session(session), "contract_sync": "success" if _sync_session(session) else "partial"}


@app.get("/api/v1/host-bridge/sessions/{session_id}", dependencies=[Depends(require_host_access)])
async def get_session(session_id: str) -> dict[str, Any]:
    return _call(lambda: as_public_session(bridge.get_session(session_id)))


@app.post("/api/v1/host-bridge/sessions/{session_id}/runs", dependencies=[Depends(require_host_access)])
async def start_run(session_id: str, payload: RunPayload) -> dict[str, Any]:
    result = _call(lambda: bridge.start_run(session_id, payload.prompt, payload.request_id))
    session = _call(lambda: bridge.get_session(session_id))
    return {**result, "contract_sync": "success" if _sync_session(session) else "partial"}


@app.post("/api/v1/host-bridge/sessions/{session_id}/visible-auth", dependencies=[Depends(require_host_access)])
async def open_visible_auth(session_id: str, payload: VisibleAuthPayload) -> dict[str, Any]:
    return _call(lambda: bridge.open_visible_auth(session_id, payload.provider, payload.url, payload.request_id))


@app.get("/api/v1/host-bridge/runs/{run_id}/events", dependencies=[Depends(require_host_access)])
async def run_events(run_id: str, cursor: int = Query(default=0, ge=0)) -> dict[str, Any]:
    page = _call(lambda: bridge.run_events(run_id, cursor))
    session = _call(lambda: bridge.get_session(page["session_id"]))
    return {**page, "contract_sync": "success" if _sync_session(session) else "partial"}


@app.post("/api/v1/host-bridge/runs/{run_id}/cancel", dependencies=[Depends(require_host_access)])
async def cancel_run(run_id: str) -> dict[str, Any]:
    return _call(lambda: bridge.cancel_run(run_id))


@app.post("/api/v1/host-bridge/sessions/{session_id}/attachments", dependencies=[Depends(require_host_access)])
async def upload_attachment(session_id: str, attachment: UploadFile = File(...)) -> dict[str, Any]:
    content = await attachment.read(25 * 1024 * 1024 + 1)
    metadata = _call(lambda: bridge.save_attachment(session_id, attachment.filename or "attachment", content, attachment.content_type or "application/octet-stream"))
    return {**metadata, "contract_sync": "success" if _sync_attachment(session_id, metadata) else "partial"}


@app.get("/api/v1/host-bridge/sessions/{session_id}/attachments/{attachment_id}", dependencies=[Depends(require_host_access)])
async def download_attachment(session_id: str, attachment_id: str):
    path, metadata = _call(lambda: bridge.attachment(session_id, attachment_id))
    return FileResponse(path, media_type=metadata["content_type"], filename=path.name)


# Compatibility for the current WeCom orchestration call shape. It is still
# authenticated and delegates to the same provider-neutral session/run core.
@app.post("/api/sessions", dependencies=[Depends(require_host_access)])
async def legacy_create_session(payload: LegacyCreatePayload) -> dict[str, Any]:
    session_id = payload.session_id or f"session:{uuid.uuid4().hex}"
    project_dir = payload.project_dir or os.getenv("OMNI_PROJECT_DIR", "")
    session = _call(lambda: bridge.ensure_session(HostSession(session_id, payload.brain_provider, None, project_dir)))
    return {"id": session.session_id, "session_id": session.session_id, "runner_provider": session.runner_provider, "runner_session_id": session.runner_session_id, "status": session.status, "contract_sync": "success" if _sync_session(session) else "partial"}


@app.post("/api/sessions/{session_id}/open", dependencies=[Depends(require_host_access)])
async def legacy_open_session(session_id: str) -> dict[str, Any]:
    return _call(lambda: as_public_session(bridge.get_session(session_id)))


@app.post("/api/sessions/{session_id}/prompt", dependencies=[Depends(require_host_access)])
async def legacy_prompt(session_id: str, payload: LegacyPromptPayload) -> dict[str, Any]:
    existing = _call(lambda: bridge.get_session(session_id))
    trace_id = payload.trace_id or f"trace:host:{uuid.uuid4().hex}"
    execution_id = payload.execution_id or f"execution:host:{uuid.uuid4().hex}"
    updated = _call(lambda: bridge.ensure_session(HostSession(
        session_id=session_id, runner_provider=payload.brain_provider,
        runner_session_id=existing.runner_session_id, project_dir=existing.project_dir,
        execution_id=execution_id, parent_span_id=payload.parent_span_id,
        model=payload.model, effort=payload.effort, trace_id=trace_id,
    )))
    result = _call(lambda: bridge.start_run(updated.session_id, payload.prompt, payload.request_id or f"request:{uuid.uuid4().hex}"))
    return {**result, "contract_sync": "success" if _sync_session(updated) else "partial"}


def as_public_session(session: HostSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id, "runner_provider": session.runner_provider,
        "runner_session_id": session.runner_session_id, "project_dir": session.project_dir,
        "execution_id": session.execution_id, "parent_span_id": session.parent_span_id,
        "model": session.model, "effort": session.effort, "trace_id": session.trace_id,
        "status": session.status,
    }
