import io
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host_bridge import app as host_app
from host_bridge.core import HostBridge


class Process:
    pid = 9191
    stdout = io.StringIO('{"type":"thread.started","thread_id":"runner:http"}\n{"type":"turn.completed"}\n')
    stderr = io.StringIO('')
    def wait(self): return 0
    def terminate(self): return None


class Runner:
    def start(self, _session, _prompt, _parent_span_id=None): return Process()


@pytest.mark.asyncio
async def test_canonical_and_wecom_compatibility_routes_share_authenticated_core(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("rules", encoding="utf-8")
    token_file = tmp_path / "host.token"
    token_file.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setenv("OMNI_HOST_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("OMNI_PROJECT_DIR", str(project))
    opened_urls = []
    monkeypatch.setattr(host_app, "bridge", HostBridge(
        state_dir=tmp_path / "state", allow_roots=[tmp_path], instance_id="host:test", runner=Runner(),
        visible_auth_origins={"https://login.example.test"},
        visible_auth_opener=lambda url: opened_urls.append(url) is None,
    ))
    headers = {"Authorization": f"Bearer {'x' * 32}"}
    transport = httpx.ASGITransport(app=host_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post("/api/sessions", json={"project_dir": str(project)})
        created = await client.post("/api/sessions", json={"project_dir": str(project), "brain_provider": "codex"}, headers=headers)
        session_id = created.json()["session_id"]
        opened = await client.post(f"/api/sessions/{session_id}/open", headers=headers)
        prompted = await client.post(f"/api/sessions/{session_id}/prompt", json={"prompt": "hello", "brain_provider": "codex", "request_id": "request:http"}, headers=headers)
        visible_denied = await client.post(
            f"/api/v1/host-bridge/sessions/{session_id}/visible-auth",
            json={"provider": "wecom", "url": "https://evil.example/qr", "request_id": "request:evil"}, headers=headers,
        )
        visible = await client.post(
            f"/api/v1/host-bridge/sessions/{session_id}/visible-auth",
            json={"provider": "wecom", "url": "https://login.example.test/qr?ticket=secret-value", "request_id": "request:visible"}, headers=headers,
        )
        events = await client.get(f"/api/v1/host-bridge/runs/{prompted.json()['run_id']}/events", headers=headers)
        uploaded = await client.post(
            f"/api/v1/host-bridge/sessions/{session_id}/attachments",
            files={"attachment": ("proof.txt", b"attachment proof", "text/plain")}, headers=headers,
        )
        downloaded = await client.get(
            f"/api/v1/host-bridge/sessions/{session_id}/attachments/{uploaded.json()['attachment_id']}", headers=headers,
        )
    assert denied.status_code == 401
    assert created.status_code == 200 and opened.status_code == 200 and prompted.status_code == 200
    assert prompted.json()["trace_id"].startswith("trace:host:")
    assert prompted.json()["execution_id"].startswith("execution:host:")
    assert visible_denied.status_code == 403 and visible.status_code == 200
    assert opened_urls == ["https://login.example.test/qr?ticket=secret-value"]
    assert "secret-value" not in visible.text
    assert events.status_code == 200 and events.json()["next_cursor"] >= 1
    assert uploaded.status_code == 200 and downloaded.content == b"attachment proof"
