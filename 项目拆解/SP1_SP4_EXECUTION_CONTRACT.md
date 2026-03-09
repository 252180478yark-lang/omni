# SP1-SP4 执行契约（基于 debate-verdict）

## 1) 模型分工

- 简单框架生成：`composer1.5`
- 复杂任务与关键架构实现：`codex5.3`
- 前端页面与组件生成：`gemini-3.1-pro`

## 2) 必须遵守的架构修正

- SP#2 统一命名为 `identity-service`，不再使用 `backend-gateway` 名称。
- SP#3 对外协议采用 OpenAI 标准：`/v1/chat/completions` 与 `/v1/embeddings`。
- SP#4 入库改为异步：HTTP `202 + task_id`，禁止在 DB 事务里等待外部 AI I/O。
- 禁止微服务间共享 ORM 模型；用户上下文通过 JWT Payload 传递。
- 向量维度绑定到知识库（`embedding_model + dimension`），不可全局硬编码。
- Nginx 不做全局 `proxy_buffering off`；仅流式路由通过 `X-Accel-Buffering: no` 控制。
- 基础设施编排不依赖 `wait-for-it.sh`，采用 Compose healthcheck + depends_on。

## 3) 当前仓库已落地（本次执行）

- 新增 `services/infra-core`：Postgres(pgvector) / Redis / Nginx 基础编排与配置。
- 新增 `services/identity-service`：JWT 注册/登录/验签最小骨架。
- 新增 `services/ai-provider-hub`：OpenAI 兼容接口最小骨架（含 SSE）。
- 新增 `services/knowledge-engine`：异步 ingestion（202 + task_id）最小骨架。
- 新增 `services/docker-compose.sp1-sp4.yml`：SP1-SP4 联调编排文件。

## 4) 下一步（按复杂度分派）

- `composer1.5`：补齐各服务 README、脚手架测试、基础 CI、样板配置。
- `codex5.3`：实现真实 DB 模型/Alembic、Celery 任务链、RRF 混合检索、维度分区落表。
- `gemini-3.1-pro`：生成 SP#2~SP#4 的控制台页面、任务进度页、知识库管理页与模型配置页。
