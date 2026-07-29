from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[1]
ALLOCATION_SPEC = importlib.util.spec_from_file_location(
    "approval_hmac_interop_runtime_allocation",
    ROOT / "scripts" / "runtime_allocation.py",
)
assert ALLOCATION_SPEC is not None and ALLOCATION_SPEC.loader is not None
allocation = importlib.util.module_from_spec(ALLOCATION_SPEC)
sys.modules[ALLOCATION_SPEC.name] = allocation
ALLOCATION_SPEC.loader.exec_module(allocation)

KNOWLEDGE_ENGINE_ROOT = ROOT / "services" / "knowledge-engine"
sys.path.insert(0, str(KNOWLEDGE_ENGINE_ROOT))

from app.routers import approval_operations as approval_router


def _request(url: str, body: bytes, headers: dict[str, str]) -> Request:
    parsed = urlsplit(url)
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": parsed.scheme,
            "path": parsed.path,
            "raw_path": parsed.path.encode("ascii"),
            "query_string": parsed.query.encode("ascii"),
            "headers": [
                (key.lower().encode("ascii"), value.encode("ascii"))
                for key, value in headers.items()
            ],
            "server": (parsed.hostname or "localhost", parsed.port or 80),
            "client": ("127.0.0.1", 50000),
        },
        receive,
    )


@pytest.mark.asyncio
async def test_allocator_raw_bytes_node_signer_python_verifier_interoperate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Include non-UTF8 bytes so an accidental text decode/trim in any runtime
    # changes the HMAC. Only the external file path crosses process boundaries.
    monkeypatch.setattr(
        allocation.secrets,
        "token_bytes",
        lambda size: (bytes((0, 255)) * ((size + 1) // 2))[:size],
    )
    secret_path = allocation.ensure_approval_hmac_secret(
        ROOT, path=tmp_path / "runtime-secrets" / "approval-hmac.key"
    )
    assert secret_path.stat().st_size == 48

    primary_frontend = allocation.primary_worktree(ROOT) / "frontend"
    node = shutil.which("node")
    tsx_cli = primary_frontend / "node_modules" / "tsx" / "dist" / "cli.mjs"
    assert node is not None and tsx_cli.is_file()
    body_text = json.dumps({"note": "approved"}, separators=(",", ":"))
    url = "http://knowledge-engine:8002/api/v1/mcp/human-gates/gate-1/approve"
    script = """
import { approvalServiceHeaders } from './src/app/api/omni/_shared.ts'
const headers = approvalServiceHeaders(
  'POST',
  process.env.INTEROP_URL,
  { id: 'admin@example.com', role: 'admin' },
  process.env.INTEROP_BODY,
)
console.log(JSON.stringify(headers))
"""
    env = os.environ.copy()
    env.update(
        {
            "NODE_PATH": str(primary_frontend / "node_modules"),
            "OMNI_APPROVAL_SERVICE_SECRET_FILE": str(secret_path),
            "INTEROP_URL": url,
            "INTEROP_BODY": body_text,
        }
    )
    signed = subprocess.run(
        [node, str(tsx_cli), "-e", script],
        cwd=ROOT / "frontend",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert signed.returncode == 0, signed.stderr
    headers = json.loads(signed.stdout)
    headers["Content-Type"] = "application/json"

    monkeypatch.setenv("OMNI_APPROVAL_SERVICE_SECRET_FILE", str(secret_path))
    approval_router._SERVICE_NONCES.clear()
    principal = await approval_router._service_principal(
        _request(url, body_text.encode("utf-8"), headers)
    )
    assert principal is not None
    assert principal.principal_id == "identity:admin@example.com"

    # The exact same signed request is rejected as a nonce replay.
    replay = await approval_router._service_principal(
        _request(url, body_text.encode("utf-8"), headers)
    )
    assert replay is None
