"""W3b T6/T7: KB 管理 tool 测试。"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp.tools.kb import kb_upload_doc, kb_set_role
from app.mcp import human_gate

SMOKE_PREFIX = "_smoke_W3b_kb_"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    pool = get_pool()
    # 清理可能残留的 _smoke_ KB
    await pool.execute(
        "DELETE FROM knowledge.knowledge_bases WHERE name LIKE $1",
        SMOKE_PREFIX + "%",
    )
    # 准备一个测试 KB
    smoke_kb_id = str(uuid.uuid4())
    await pool.execute(
        """
        INSERT INTO knowledge.knowledge_bases
            (id, name, description, embedding_provider, embedding_model, dimension, kb_role)
        VALUES ($1::uuid, $2, '_smoke W3b test KB', 'gemini', 'gemini-embedding-2-preview', 1536, 'general')
        """,
        smoke_kb_id,
        SMOKE_PREFIX + "kb",
    )
    yield smoke_kb_id
    # teardown
    await pool.execute(
        "DELETE FROM knowledge.knowledge_bases WHERE name LIKE $1",
        SMOKE_PREFIX + "%",
    )
    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name IN ('kb_upload_doc', 'kb_set_role') AND args::text LIKE $1",
        "%" + SMOKE_PREFIX + "%",
    )
    await pool.execute(
        "DELETE FROM mcp.human_gates WHERE summary LIKE $1",
        "%" + SMOKE_PREFIX + "%",
    )
    await close_pool()


@pytest.mark.asyncio
async def test_kb_upload_doc_rejected_when_no_approval(setup_pool):
    """走 Gate 但 mock 返 rejected → 不真调 ingestion。"""
    kb_id = setup_pool
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("smoke W3b kb_upload_doc test content\n")
        tmp_path = f.name

    try:
        original_request = human_gate.request_approval

        async def mock_rejected(**kwargs):
            return {"decision": "rejected", "decision_note": "test mock"}

        human_gate.request_approval = mock_rejected
        try:
            result = await kb_upload_doc(kb_id=kb_id, file_path=tmp_path)
        finally:
            human_gate.request_approval = original_request

        assert result["ok"] is False
        assert result["error"] == "rejected_by_user"
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_kb_upload_doc_approved_creates_task(setup_pool):
    """Gate 批准 → 真调 ingestion，返 task_id。"""
    kb_id = setup_pool
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("approved upload smoke content\n这是中文内容用于测试 ingestion 抽取。")
        tmp_path = f.name

    try:
        original_request = human_gate.request_approval

        async def mock_approved(**kwargs):
            return {"decision": "approved", "decision_note": "test approved"}

        human_gate.request_approval = mock_approved
        try:
            result = await kb_upload_doc(
                kb_id=kb_id, file_path=tmp_path, title="_smoke_W3b_doc"
            )
        finally:
            human_gate.request_approval = original_request

        assert result["ok"] is True
        assert "task_id" in result["result"]
        task_id = result["result"]["task_id"]
        assert isinstance(task_id, str) and len(task_id) > 0
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_kb_upload_doc_invalid_kb(setup_pool):
    """kb_id 不存在 → 提前 reject。"""
    fake_kb = str(uuid.uuid4())
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("any content")
        tmp_path = f.name

    try:
        original_request = human_gate.request_approval

        async def mock_approved(**kwargs):
            return {"decision": "approved"}

        human_gate.request_approval = mock_approved
        try:
            result = await kb_upload_doc(kb_id=fake_kb, file_path=tmp_path)
        finally:
            human_gate.request_approval = original_request

        assert result["ok"] is False
        assert result["error"] == "kb_not_found"
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_kb_set_role_approved(setup_pool):
    kb_id = setup_pool
    original_request = human_gate.request_approval

    async def mock_approved(**kwargs):
        return {"decision": "approved"}

    human_gate.request_approval = mock_approved
    try:
        result = await kb_set_role(kb_id=kb_id, kb_role="template")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is True
    assert result["result"]["kb_role"] == "template"

    # 验证 DB 真写入
    pool = get_pool()
    role = await pool.fetchval(
        "SELECT kb_role FROM knowledge.knowledge_bases WHERE id = $1::uuid",
        kb_id,
    )
    assert role == "template"

    # 改回 general 让后续测试稳定
    await pool.execute(
        "UPDATE knowledge.knowledge_bases SET kb_role = 'general' WHERE id = $1::uuid",
        kb_id,
    )


@pytest.mark.asyncio
async def test_kb_set_role_invalid_role(setup_pool):
    kb_id = setup_pool
    original_request = human_gate.request_approval

    async def mock_approved(**kwargs):
        return {"decision": "approved"}

    human_gate.request_approval = mock_approved
    try:
        result = await kb_set_role(kb_id=kb_id, kb_role="not_a_real_role")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is False
    assert result["error"] == "invalid_kb_role"


@pytest.mark.asyncio
async def test_kb_set_role_kb_not_found(setup_pool):
    fake_kb = str(uuid.uuid4())
    original_request = human_gate.request_approval

    async def mock_approved(**kwargs):
        return {"decision": "approved"}

    human_gate.request_approval = mock_approved
    try:
        result = await kb_set_role(kb_id=fake_kb, kb_role="general")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is False
    assert result["error"] == "kb_not_found"


@pytest.mark.asyncio
async def test_kb_set_role_rejected(setup_pool):
    kb_id = setup_pool
    original_request = human_gate.request_approval

    async def mock_rejected(**kwargs):
        return {"decision": "rejected", "decision_note": "test reject"}

    human_gate.request_approval = mock_rejected
    try:
        result = await kb_set_role(kb_id=kb_id, kb_role="template")
    finally:
        human_gate.request_approval = original_request

    assert result["ok"] is False
    assert result["error"] == "rejected_by_user"
