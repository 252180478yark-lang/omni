# SP4 knowledge-engine

Knowledge ingestion and retrieval service for chunking, vector search, and graph extraction.

知识引擎服务，负责文本切分、向量检索、图谱抽取与查询。

## Status / 当前状态

- Current version uses sqlite and application-layer retrieval.
- Blueprint target PostgreSQL + pgvector + HNSW is not fully migrated yet.

当前版本为可运行版本，生产级向量栈与 GraphRAG 完整流程仍在推进。

## Run / 运行

```bash
cd services/knowledge-engine
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

## API / 接口

- `GET /health`
- `POST /api/v1/knowledge/bases`
- `GET /api/v1/knowledge/bases`
- `POST /api/v1/knowledge/ingest`
- `GET /api/v1/knowledge/tasks/{task_id}`
- `POST /api/v1/knowledge/query`
- `GET /api/v1/knowledge/graph/{kb_id}`
- `GET /api/v1/knowledge/documents/{document_id}`

## Environment Variables / 环境变量

| Variable | Default | Description |
| --- | --- | --- |
| `SERVICE_NAME` | `knowledge-engine` | service name |
| `SERVICE_PORT` | `8002` | service port |
| `AI_PROVIDER_HUB_URL` | `http://ai-provider-hub:8001` | ai-provider-hub address |
| `EMBEDDING_PROVIDER` | `openai` | embedding provider key |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | embedding model |
| `CHUNK_SIZE` | `512` | chunk size |
| `CHUNK_OVERLAP` | `50` | overlap size |
| `EMBEDDING_BATCH_SIZE` | `100` | embedding batch size |
| `DATABASE_PATH` | `/app/data/knowledge.db` | sqlite path (temporary) |

## Test / 测试

```bash
pytest -q
```

## Roadmap / 后续计划

- PostgreSQL + pgvector + HNSW migration
- ORM model split (`Document`/`Chunk`/`Entity`/`Relation`/`KnowledgeBase`)
- Native pgvector index/operator usage
- GraphRAG with structured LLM extraction and community detection
- Complete file upload ingestion pipeline
- Production Docker image hardening
