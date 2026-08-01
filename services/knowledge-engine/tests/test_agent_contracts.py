from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.agent_contracts import get_agent_contract_store, router
from app.routers.runtime_traces import require_trace_access
from app.services.agent_contracts import MemoryAgentContractStore


@pytest.mark.asyncio
async def test_fresh_session_captures_real_runner_and_attachment_metadata_without_raw_path():
    store = MemoryAgentContractStore()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_contract_store] = lambda: store
    app.dependency_overrides[require_trace_access] = lambda: None
    transport = httpx.ASGITransport(app=app)
    fresh = {"session_id": "session:contract", "runner_provider": "codex", "runner_session_id": None, "project_dir": "E:/agent/omni", "trace_id": "trace:contract"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/agent-contracts/sessions", json=fresh)
        captured = await client.post("/api/v1/agent-contracts/sessions", json={**fresh, "runner_session_id": "runner:real"})
        conflict = await client.post("/api/v1/agent-contracts/sessions", json={**fresh, "runner_session_id": "runner:other"})
        attachment = await client.post("/api/v1/agent-contracts/sessions/session:contract/attachments", json={
            "session_id": "session:contract", "attachment_id": "attachment:" + "d" * 32,
            "sha256": "a" * 64, "size_bytes": 12, "content_type": "text/plain", "storage_key": "sha256/" + "a" * 64 + ".txt",
        })
    assert created.json()["runner_session_id"] is None
    assert captured.json()["runner_session_id"] == "runner:real"
    assert conflict.status_code == 409 and attachment.status_code == 200
    assert "E:/agent/omni" not in str(captured.json())
