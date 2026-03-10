# Omni / Omni-Vibe OS

> Hybrid architecture intelligent system: frontend console + SP1-SP4 backend service cluster.
>
> 混合架构智能系统：前端控制台 + SP1-SP4 后端服务集群。

![Status](https://img.shields.io/badge/Status-Active_Development-green)
![Frontend](https://img.shields.io/badge/Frontend-Next.js_14-black)
![Backend](https://img.shields.io/badge/Backend-FastAPI-blue)

## Overview / 项目概览

Omni is a full-stack workspace for AI-native operations:

- Frontend console (`frontend`) based on Next.js 14.
- SP1 infrastructure core (`services/infra-core`): PostgreSQL, Redis, Nginx.
- SP3 AI provider hub (`services/ai-provider-hub`): provider abstraction + OpenAI compatible routes.
- SP4 knowledge engine (`services/knowledge-engine`): ingestion, retrieval, graph extraction.
- SP5 news aggregator (`services/news-aggregator`): multi-source AI news fetch/review/archive.
- SP6 video analysis (`services/video-analysis`): internal short-video analysis and report assets.

Omni 是一个 AI Native 全栈工作台，采用“前端控制台 + 后端服务化”组合架构。

## Repository Layout / 仓库结构

```text
omni/
├── frontend/
├── services/
│   ├── infra-core/
│   ├── ai-provider-hub/
│   ├── knowledge-engine/
│   ├── news-aggregator/
│   └── video-analysis/
├── apps/
├── 项目拆解/
├── docker-compose.yml
└── package.json
```

## Quick Start / 快速开始

### 1) Frontend / 前端

```bash
cd frontend
npm install
npm run dev
```

Open: `http://localhost:3000`

### 2) Infra Core / 基础设施

```bash
cd services/infra-core
cp .env.example .env
docker compose -f docker-compose.infra.yml up -d
```

### 3) SP3-SP6 Services / 后端服务

```bash
cd services
docker compose -f docker-compose.sp1-sp4.yml up -d --build
```

## Service Endpoints / 服务路由

- Frontend: `http://localhost:3000`
- Nginx health: `http://localhost/health`
- AI Native API: `http://localhost/api/v1/ai/*`
- AI OpenAI-compatible API: `http://localhost/v1/*`
- Knowledge: `http://localhost/api/v1/knowledge/*`
- News Aggregator: `http://localhost/api/v1/news/*`
- Video Analysis: `http://localhost/api/v1/video-analysis/*`

## Unified API Document / 统一 API 文档

- See `docs/PROJECT_API.md`
- 默认建议使用统一网关基地址：`http://localhost`

## SP5 Quick Start

```bash
cd services/news-aggregator
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8005
```

Core endpoints:

- `POST /api/v1/news/fetch`
- `GET /api/v1/news/fetch/{job_id}`
- `GET /api/v1/news/articles`
- `PATCH /api/v1/news/articles/{id}`
- `POST /api/v1/news/articles/batch`
- `GET /api/v1/news/archive`
- `GET /api/v1/news/archive/tags`
- `GET /api/v1/news/archive/stats`
- `POST /api/v1/news/archive/retry-kb`

## Environment Variables / 环境变量总表

| Variable | Default | Used By | Description |
| --- | --- | --- | --- |
| `POSTGRES_USER` | `omni_user` | infra-core | PostgreSQL user |
| `POSTGRES_PASSWORD` | `changeme_in_production` | infra-core | PostgreSQL password |
| `POSTGRES_DB` | `omni_vibe_db` | infra-core | PostgreSQL database |
| `POSTGRES_PORT` | `5432` | infra-core | PostgreSQL host port |
| `REDIS_PASSWORD` | `changeme_redis` | infra-core | Redis password |
| `REDIS_PORT` | `6379` | infra-core | Redis host port |
| `NGINX_PORT` | `80` | infra-core | Nginx HTTP port |
| `NGINX_SSL_PORT` | `443` | infra-core | Nginx HTTPS port |
| `DATABASE_PATH` | `/app/data/*.db` | knowledge | sqlite path (temporary) |
| `SERVICE_NAME` | service-specific | all backend services | logical service name |
| `SERVICE_PORT` | `8001/8002/8005/8006` | all backend services | service listen port |
| `LOG_LEVEL` | `INFO` | ai-provider-hub | logging level |
| `GEMINI_API_KEY` | empty | ai-provider-hub | Gemini API key |
| `OPENAI_API_KEY` | empty | ai-provider-hub | OpenAI API key |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | ai-provider-hub | Ollama endpoint |
| `DEFAULT_CHAT_PROVIDER` | `gemini` | ai-provider-hub | default chat provider |
| `DEFAULT_EMBEDDING_PROVIDER` | `openai` | ai-provider-hub | default embedding provider |
| `REQUEST_TIMEOUT_SECONDS` | `30` | ai-provider-hub | upstream timeout |
| `OMNI_API_BASE_URL` | `http://localhost` | frontend server | unified gateway base URL for server-side API calls |
| `AI_PROVIDER_HUB_URL` | `http://ai-provider-hub:8001` | knowledge-engine | AI hub endpoint |
| `VIDEO_ANALYSIS_SERVICE_URL` | `http://video-analysis:8006` | frontend server | video-analysis internal service URL (for BFF sync route) |
| `NEXT_PUBLIC_OMNI_API_BASE_URL` | `http://localhost` | frontend client | unified gateway base URL for browser-side API calls |
| `EMBEDDING_PROVIDER` | `openai` | knowledge-engine | embedding provider key |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | knowledge-engine | embedding model |
| `CHUNK_SIZE` | `512` | knowledge-engine | chunk size |
| `CHUNK_OVERLAP` | `50` | knowledge-engine | chunk overlap |
| `EMBEDDING_BATCH_SIZE` | `100` | knowledge-engine | embedding batch size |

## FAQ

### 1) Why both `/api/v1/ai/*` and `/v1/*`?

`/api/v1/ai/*` is native internal API; `/v1/*` is OpenAI-compatible for SDK clients.

### 2) Why does knowledge-engine still use sqlite?

Current branch keeps a minimal runnable baseline. PostgreSQL + migration upgrades are planned in subsequent iterations.

### 3) Why does knowledge-engine not use pgvector yet?

Current implementation prioritizes end-to-end flow validation. pgvector + HNSW migration will follow once schema and deployment baseline is finalized.

### 4) What should I run first in local dev?

Start infra (`infra-core`) first, then SP3-SP5 services, then frontend.

### 5) How to use short video analysis integration?

1. 启动 `infra-core` 与 `services/docker-compose.sp1-sp4.yml`，确保包含 `video-analysis` 服务。
2. 在 Omni 打开 `/models` 先配置 provider API Key。
3. 打开 `/video-analysis`，选择 provider/model，点击“同步系统 Key 到分析服务”。
4. 上传视频并等待报告生成，再选择一个或多个知识库保存结果。

## License

MIT
