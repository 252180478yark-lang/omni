"""Knowledge Engine API tests.

These tests mock the database layer to validate API routing and request/response
schemas without requiring a live PostgreSQL instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


_FAKE_KB = {
    "id": str(uuid4()),
    "name": "test-kb",
    "description": "unit test",
    "embedding_provider": "gemini",
    "embedding_model": "gemini-embedding-2-preview",
    "dimension": 1536,
    "created_at": "2026-01-01T00:00:00+00:00",
}


# ═══ Knowledge Bases ═══


@patch("app.routers.knowledge.create_kb_with_profile", new_callable=AsyncMock, return_value=_FAKE_KB)
def test_create_kb(mock_create, client):
    resp = client.post(
        "/api/v1/knowledge/bases",
        json={"name": "test-kb", "description": "unit test"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "test-kb"
    mock_create.assert_awaited_once()


@patch("app.routers.knowledge.list_kbs", new_callable=AsyncMock, return_value=[_FAKE_KB])
def test_list_kbs(mock_list, client):
    resp = client.get("/api/v1/knowledge/bases")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


@patch("app.routers.knowledge.delete_kb", new_callable=AsyncMock, return_value=True)
def test_delete_kb(mock_del, client):
    resp = client.delete(f"/api/v1/knowledge/bases/{_FAKE_KB['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


@patch("app.routers.knowledge.delete_kb", new_callable=AsyncMock, return_value=False)
def test_delete_kb_not_found(mock_del, client):
    resp = client.delete("/api/v1/knowledge/bases/nonexistent")
    assert resp.status_code == 404


# ═══ Ingestion ═══


@patch("app.routers.knowledge.get_kb", new_callable=AsyncMock, return_value=None)
def test_ingest_returns_404_for_unknown_kb(mock_kb, client):
    resp = client.post(
        "/api/v1/knowledge/ingest",
        json={"kb_id": "missing", "title": "doc", "text": "hello"},
    )
    assert resp.status_code == 404


@patch("app.routers.knowledge.submit_ingestion_task", new_callable=AsyncMock, return_value="task-123")
@patch("app.routers.knowledge.get_kb", new_callable=AsyncMock, return_value=_FAKE_KB)
def test_ingest_text(mock_kb, mock_submit, client):
    resp = client.post(
        "/api/v1/knowledge/ingest",
        json={
            "kb_id": _FAKE_KB["id"],
            "title": "my doc",
            "text": "some content",
            "source_type": "news",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["task_id"] == "task-123"
    mock_submit.assert_awaited_once()
    call_kwargs = mock_submit.call_args
    assert call_kwargs[0][4] == "news"  # source_type positional arg


# ═══ Search ═══


@patch("app.routers.knowledge.search_chunks", new_callable=AsyncMock, return_value=[])
@patch("app.routers.knowledge.get_kb", new_callable=AsyncMock, return_value=_FAKE_KB)
def test_query_empty_results(mock_kb, mock_search, client):
    resp = client.post(
        "/api/v1/knowledge/query",
        json={"kb_id": _FAKE_KB["id"], "query": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ═══ Documents ═══


@patch("app.routers.knowledge.list_documents", new_callable=AsyncMock, return_value=[])
def test_list_documents_empty(mock_docs, client):
    resp = client.get("/api/v1/knowledge/documents")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@patch("app.routers.knowledge.delete_document", new_callable=AsyncMock, return_value=False)
def test_delete_document_not_found(mock_del, client):
    resp = client.delete("/api/v1/knowledge/documents/nonexistent")
    assert resp.status_code == 404


# ═══ Stats ═══


@patch(
    "app.routers.knowledge.get_stats",
    new_callable=AsyncMock,
    return_value={"knowledge_bases": 1, "documents": 3, "chunks": 15, "tasks_by_status": {}},
)
def test_stats(mock_stats, client):
    resp = client.get("/api/v1/knowledge/stats")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["knowledge_bases"] == 1
    assert data["chunks"] == 15
