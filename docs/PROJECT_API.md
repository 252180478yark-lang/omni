# Omni 项目统一 API 文档

本文档汇总了当前仓库可用的 API，并给出统一调用约定。

## 默认调用约定

- 统一网关基地址：`http://localhost`
- 程序默认走网关路径：
  - `http://localhost/api/v1/ai/*`
  - `http://localhost/v1/*`
  - `http://localhost/api/v1/knowledge/*`
  - `http://localhost/api/v1/news/*`
  - `http://localhost/api/v1/video-analysis/*`
- 前端内部 BFF 路径（Next.js Route Handlers）：
  - `/api/omni/*`
  - `/api/tri-mind/*`

## 网关层（Nginx）聚合 API

当前 `services/infra-core/nginx/conf.d/default.conf` 已配置：

- `GET /health`
- `ANY /api/v1/ai/*` -> `ai-provider-hub:8001`
- `ANY /v1/*` -> `ai-provider-hub:8001`
- `ANY /api/v1/knowledge/*` -> `knowledge-engine:8002`
- `ANY /api/v1/news/*` -> `news-aggregator:8005`
- `ANY /api/v1/video-analysis/*` -> `video-analysis:8006`

## 前端 BFF API（Next.js）

### Omni 聚合接口

- `GET /api/omni/overview`
- `GET /api/omni/models`
- `POST /api/omni/models`（支持 `refresh` / `update-provider` / `test-connection`）
- `GET /api/omni/knowledge/bases`
- `POST /api/omni/knowledge/bases`
- `DELETE /api/omni/knowledge/bases/{kbId}`
- `POST /api/omni/knowledge/ingest`
- `GET /api/omni/knowledge/tasks`
- `POST /api/omni/knowledge/tasks/{taskId}/retry`
- `GET /api/omni/knowledge/documents`
- `GET /api/omni/knowledge/documents/{documentId}`
- `DELETE /api/omni/knowledge/documents/{documentId}`

### Tri-Mind 接口

- `POST /api/tri-mind/debate`（`application/x-ndjson` 流式）
- `GET /api/tri-mind/sessions`
- `POST /api/tri-mind/sessions`
- `GET /api/tri-mind/sessions/{id}`
- `DELETE /api/tri-mind/sessions/{id}`
- `POST /api/tri-mind/test-connection`

## SP3：ai-provider-hub

### Native API

- `POST /api/v1/ai/chat`
- `POST /api/v1/ai/chat/stream`
- `POST /api/v1/ai/embedding`
- `GET /api/v1/ai/providers`
- `GET /api/v1/ai/models`
- `POST /api/v1/ai/config`
- `POST /api/v1/ai/test-connection`

### OpenAI Compatible API

- `POST /v1/chat/completions`
- `POST /v1/embeddings`

### Health

- `GET /health`

## SP4：knowledge-engine

- `POST /api/v1/knowledge/bases`
- `GET /api/v1/knowledge/bases`
- `DELETE /api/v1/knowledge/bases/{kb_id}`
- `POST /api/v1/knowledge/ingest`
- `GET /api/v1/knowledge/tasks/{task_id}`
- `GET /api/v1/knowledge/tasks`
- `POST /api/v1/knowledge/tasks/{task_id}/retry`
- `POST /api/v1/knowledge/query`
- `GET /api/v1/knowledge/graph/{kb_id}`
- `GET /api/v1/knowledge/documents/{document_id}`
- `GET /api/v1/knowledge/documents`
- `DELETE /api/v1/knowledge/documents/{document_id}`
- `GET /api/v1/knowledge/stats`

### 知识库创建默认行为

- 当 `POST /api/v1/knowledge/bases` 未显式传 `embedding_provider` / `embedding_model` 时，
  服务会自动读取 ai-provider-hub 当前保存的 Provider 配置，优先选择可用的 embedding provider，并使用其默认 embedding 模型。

## SP5：news-aggregator

- `GET /health`
- `POST /api/v1/news/fetch`
- `GET /api/v1/news/fetch/{job_id}`
- `GET /api/v1/news/articles`
- `PATCH /api/v1/news/articles/{article_id}`
- `POST /api/v1/news/articles/batch`
- `GET /api/v1/news/archive`
- `GET /api/v1/news/archive/tags`
- `GET /api/v1/news/archive/stats`
- `POST /api/v1/news/archive/retry-kb`

## SP6：video-analysis

- `GET /health`
- `POST /api/v1/video-analysis/settings/gemini/test`
- `GET /api/v1/video-analysis/videos`
- `POST /api/v1/video-analysis/videos`
- `GET /api/v1/video-analysis/videos/{video_id}`
- `GET /api/v1/video-analysis/assets/*`

## 说明

- 本文档为“接口汇总文档”，用于统一检索与默认调用约定。
- 若后续新增路由，请同步更新本文档，保持网关与代码一致。
