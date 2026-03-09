# SP3 ai-provider-hub

Unified provider hub for chat and embedding APIs.

统一的模型 Provider 层，提供聊天与向量能力，并兼容 OpenAI API 前缀。

## Status / 当前状态

- Service is runnable with provider skeletons and fallback logic.
- Deep SDK integration (granular timeout/rate-limit/error-code/token-cost accounting) is not fully complete.

当前版本为可运行骨架，真实生产化细节仍在补齐。

## Run / 运行

```bash
cd services/ai-provider-hub
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## API / 接口

- Native API:
  - `POST /api/v1/ai/chat`
  - `POST /api/v1/ai/chat/stream`
  - `POST /api/v1/ai/embedding`
  - `GET /api/v1/ai/providers`
  - `GET /api/v1/ai/models`
- OpenAI compatible:
  - `POST /v1/chat/completions`
  - `POST /v1/embeddings`
- Health:
  - `GET /health`

## Environment Variables / 环境变量

| Variable | Default | Description |
| --- | --- | --- |
| `SERVICE_NAME` | `ai-provider-hub` | service name |
| `SERVICE_PORT` | `8001` | service port |
| `LOG_LEVEL` | `INFO` | log level |
| `GEMINI_API_KEY` | `` | Gemini API key |
| `OPENAI_API_KEY` | `` | OpenAI API key |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama base URL |
| `DEFAULT_CHAT_PROVIDER` | `gemini` | default chat provider |
| `DEFAULT_EMBEDDING_PROVIDER` | `openai` | default embedding provider |
| `REQUEST_TIMEOUT_SECONDS` | `30` | request timeout |

## Test / 测试

```bash
pytest -q
```

## Integration Example / 联调示例

```bash
curl -X POST http://localhost:8001/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

## Roadmap / 后续计划

- Persist usage tracking into PostgreSQL
- Complete provider SDK error mapping and quota control
- Production Dockerfile (multi-stage + non-root)
