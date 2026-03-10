from pathlib import Path
import sqlite3
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.ingestion import create_kb, init_db


def test_create_and_list_knowledge_base(tmp_path: Path) -> None:
    settings.database_path = str(tmp_path / "knowledge-test.db")
    init_db()
    client = TestClient(app)

    create_resp = client.post(
        "/api/v1/knowledge/bases",
        json={
            "name": "demo-kb",
            "description": "for test",
            "embedding_model": "text-embedding-3-small",
            "dimension": 1536,
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    assert created["name"] == "demo-kb"

    list_resp = client.get("/api/v1/knowledge/bases")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["data"]) >= 1


def test_ingest_returns_404_for_unknown_kb(tmp_path: Path) -> None:
    settings.database_path = str(tmp_path / "knowledge-test-notfound.db")
    init_db()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/knowledge/ingest",
        json={"kb_id": "missing", "title": "doc", "text": "hello"},
    )
    assert resp.status_code == 404


def test_list_and_delete_documents(tmp_path: Path) -> None:
    settings.database_path = str(tmp_path / "knowledge-documents.db")
    init_db()
    client = TestClient(app)
    kb = create_kb("demo-kb", "for docs", "text-embedding-3-small", 1536)

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(settings.database_path)
    try:
        conn.execute(
            "INSERT INTO documents(id, kb_id, title, source_url, raw_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("doc-1", kb["id"], "first doc", None, "hello world", now),
        )
        conn.execute(
            "INSERT INTO chunks(id, document_id, kb_id, chunk_index, title, source_url, content, embedding_json, dimension, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("chunk-1", "doc-1", kb["id"], 0, "first doc", None, "hello", "[]", 1536, "{}", now),
        )
        conn.commit()
    finally:
        conn.close()

    list_resp = client.get(f"/api/v1/knowledge/documents?kb_id={kb['id']}")
    assert list_resp.status_code == 200
    data = list_resp.json()["data"]
    assert len(data) == 1
    assert data[0]["chunk_count"] == 1

    delete_resp = client.delete("/api/v1/knowledge/documents/doc-1")
    assert delete_resp.status_code == 200

    list_after = client.get(f"/api/v1/knowledge/documents?kb_id={kb['id']}")
    assert list_after.status_code == 200
    assert list_after.json()["data"] == []


def test_delete_base_cascades_data(tmp_path: Path) -> None:
    settings.database_path = str(tmp_path / "knowledge-delete-base.db")
    init_db()
    client = TestClient(app)
    kb = create_kb("demo-kb", "for delete", "text-embedding-3-small", 1536)

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(settings.database_path)
    try:
        conn.execute(
            "INSERT INTO tasks(id, kb_id, status, error, document_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("task-1", kb["id"], "queued", None, None, now, now),
        )
        conn.execute(
            "INSERT INTO documents(id, kb_id, title, source_url, raw_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("doc-1", kb["id"], "first doc", None, "hello world", now),
        )
        conn.execute(
            "INSERT INTO entities(id, kb_id, name, entity_type, description) VALUES (?, ?, ?, ?, ?)",
            ("ent-1", kb["id"], "hello", "concept", "demo"),
        )
        conn.execute(
            "INSERT INTO relations(id, kb_id, source_entity, target_entity, relation_type, weight) VALUES (?, ?, ?, ?, ?, ?)",
            ("rel-1", kb["id"], "hello", "world", "related", 1.0),
        )
        conn.commit()
    finally:
        conn.close()

    delete_resp = client.delete(f"/api/v1/knowledge/bases/{kb['id']}")
    assert delete_resp.status_code == 200

    list_resp = client.get("/api/v1/knowledge/bases")
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == []
