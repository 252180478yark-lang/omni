from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.ingestion import init_db


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
