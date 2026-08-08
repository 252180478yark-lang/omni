# Omni-Vibe OS Ultra

> 面向**内容投放操盘手**的本地 AI 工作台：素材分析 → 知识沉淀 → 投放复盘 → 新素材生产，一条龙。

![Frontend](https://img.shields.io/badge/Frontend-Next.js_14-black)
![Backend](https://img.shields.io/badge/Backend-FastAPI-blue)
![DB](https://img.shields.io/badge/DB-PostgreSQL_+_Redis-orange)
![Status](https://img.shields.io/badge/Status-Active-green)
![Mode](https://img.shields.io/badge/Mode-Single_User-yellow)

> 当前版本按**个人本机单用户**设计：默认身份固定为 `local-owner`，不设置账号、密码、登录页或内部服务密钥。所有发布端口默认绑定 `127.0.0.1`，详见 [§9 安全边界](#9-安全边界单用户本机模式)。

---

## 1. 系统概览

Omni 是一个 Next.js + FastAPI 微服务混合架构的 AI Native 工作台，集成 7 个外部模型 Provider，覆盖以下能力：

* **多模型对话**（Chat/RAG/圆桌讨论）
* **知识库管理**（PostgreSQL + tsvector + jieba 中文分词 + 可选 GraphRAG）
* **网页/飞书文档采集**（Playwright 抓取，可选登录态保存）
* **多源 AI 资讯聚合**（博查/Serper/天行/RSS → 去重 → enrich → 入库）
* **短视频多模态分析**（Gemini，输出报告 + 情感曲线）
* **直播切片分析**（抽帧分析 → Excel 报表）
* **投放复盘飞轮**（巨量千川 CSV + 视频分析 + 知识库 RAG → AI 复盘 → 多轮迭代仪表盘）
* **内容工坊**（一键生成营销视频脚本 + 分镜 + 视频）

### 1.1 架构图

```
浏览器 ─► Nginx :80（full profile）─┬─► frontend :3000   Next.js 14 + BFF（local-owner）
                     ├─► ai-provider-hub    :8001   7 个 Provider 统一适配
                     ├─► knowledge-engine   :8002   RAG / Harvester / Content Studio
                     ├─► news-aggregator    :8005   多源资讯
                     ├─► video-analysis     :8006   短视频分析
                     ├─► livestream-analysis:8007   直播切片
                     └─► ad-review-service  :8008   投放复盘 + 飞轮
                                │
                                ▼
                  PostgreSQL :5432 (多 schema)
                  Redis      :6379 (限流 / 用量 / 队列)
                                │
                                ▼  容器内通过 PROXY_URL 走出墙代理
                  OpenAI / Gemini / Anthropic / Deepseek
                  Seedance(火山方舟) / Kling / Ollama
```

---

## 2. 仓库结构

```text
omni/
├── frontend/                         Next.js 14 控制台（13 个页面）
│   └── src/
│       ├── app/<page>/page.tsx       业务页面（Client Component）
│       ├── app/api/omni/**/route.ts  BFF 路由（转发到后端服务）
│       ├── components/               UI + roundtable
│       ├── stores/                   Zustand 状态
│       └── server/roundtable/        多模型圆桌后端逻辑
├── services/
│   ├── infra-core/
│   │   ├── postgres/                 镜像构建 + init.sql 多 schema
│   │   ├── redis/redis.conf
│   │   └── nginx/{nginx.conf, conf.d/default.conf}
│   ├── identity-service/             仅保留的历史源码；不进入当前运行编排
│   ├── ai-provider-hub/              FastAPI，7 个 provider 适配
│   ├── knowledge-engine/             FastAPI + asyncpg（体量最大）
│   ├── news-aggregator/              FastAPI + SQLAlchemy + Alembic
│   ├── video-analysis/               FastAPI + 内置任务队列
│   ├── livestream-analysis/          FastAPI + Gemini 抽帧分析
│   └── ad-review-service/            FastAPI + asyncpg + ad_review schema
├── apps/tri-mind-synthesizer/        遗留：旧版三模型辩论
├── docs/                             PRD / IMPL / UAT / SYSTEM_ARCHITECTURE.md
├── migrations/                       SQL 迁移脚本
├── scripts/                          运维脚本
├── docker-compose.yml                本机编排（按 core/content/full profile 收敛）
├── docker-compose.dev.yml            开发模式（仅 postgres + redis）
├── dev-start.ps1 / dev-stop.ps1      Windows 一键启停
├── 启动全部.bat / 启动全部(包含Docker).bat
├── 停止全部.bat / 停止全部(清理数据库).bat
├── package.json                      根：npm run dev → 仅启动前端
└── .env / .env.example
```

---

## 3. 服务清单

| 服务 | 端口 | API 前缀 | 主要职责 |
|---|---|---|---|
| frontend | 3000 | `/` | Next.js 14，BFF 在 `/api/omni/*` |
| identity-service（历史源码） | — | — | 不进入当前 Compose；默认前端和服务链路不依赖 |
| ai-provider-hub | 8001 | `/api/v1/ai/`、`/v1/`（OpenAI 兼容） | chat/embedding/image/video/analyze + provider 配置 + usage/cost |
| knowledge-engine | 8002 | `/api/v1/knowledge/`、`/api/v1/knowledge/harvester/`、`/api/v1/content-studio/` | 知识库、采集、RAG、内容工坊 |
| news-aggregator | 8005 | `/api/v1/news/` | fetch / articles / archive |
| video-analysis | 8006 | `/api/v1/video-analysis/` | 上传 → 分析 → 报告 → 入 KB |
| livestream-analysis | 8007 | `/api/v1/livestream-analysis/` | 切片上传 → 抽帧分析 → Excel |
| ad-review-service | 8008 | `/api/v1/ad-review/` | products / campaigns / audiences / materials / review / analytics |
| postgres | 5432 | — | 多 schema 共享 `omni_vibe_db` |
| redis | 6379 | — | DB0 ai-hub / DB1 knowledge / DB2 news / DB3 identity |

---

## 4. 前端页面

| 路由 | 功能 |
|---|---|
| `/` | 控制台（健康检查 + 关键指标 + 快捷入口） |
| `/chat` | 智能问答（RAG、多模态、圆桌讨论、Persona） |
| `/knowledge` | 知识库管理（KB / 文档 / 任务 / 图谱） |
| `/knowledge/harvester` | 网页/飞书抓取入库 |
| `/knowledge/evaluate` | RAG A/B 评测 |
| `/news` | 资讯中心 |
| `/news/archive` | 资讯归档 |
| `/models` | Provider Key 配置 + 默认模型选择 + 连接测试 |
| `/tasks` | 全局异步任务进度 |
| `/video-analysis` | 短视频分析 |
| `/livestream-analysis` | 直播切片分析 |
| `/ad-review` | 投放复盘列表 |
| `/ad-review/[id]` | 单批次复盘详情 |
| `/ad-review/flywheel` | 飞轮多轮 ROI 仪表盘 |
| `/ad-review/analytics` | 投放数据分析 |
| `/content-studio` | 内容工坊（脚本 → 分镜 → 视频） |

---

## 5. 快速开始

### 5.1 模式选择

| 模式 | 何时用 | 启动命令 |
|---|---|---|
| **core**（默认开发） | 核心工作台与热重载 | `.\dev-start.ps1 -RuntimeProfile core` |
| **content** | 内容分析完整 Docker DNS 链 | `.\dev-start.ps1 -RuntimeProfile content` |
| **full**（演示/多端） | 全服务与 Nginx 网关 | `.\dev-start.ps1 -RuntimeProfile full` |

### 5.2 环境变量

```bash
cp .env.example .env
# 至少修改：
#   POSTGRES_PASSWORD / REDIS_PASSWORD       默认密码必须改
#   PROXY_URL                                若需访问 OpenAI/Gemini，例如 http://host.docker.internal:12334
```

各服务级别还有 `services/<svc>/.env.example`，全量 Docker 模式下 compose 已经通过 `env_file` 自动注入；开发模式下 `dev-start.ps1` 会把 `.env.dev` 复制为 `.env`。

### 5.3 RuntimeAllocation + Docker 启动

先用 `scripts/runtime_allocation.py acquire --runtime-profile core|content|full` 获取 allocation，并把返回的 `environment` 导入当前 shell。profile、端口、数据库和卷都以该 allocation 为准；详见 [`docs/runtime-profiles.md`](docs/runtime-profiles.md)。

```bash
docker compose up -d                         # core，canonical 入口 :3000
docker compose --profile content up -d       # content，入口 :3000
docker compose --profile full up -d          # full，Nginx 入口 :80

# 查看日志
docker compose logs -f knowledge-engine

# 停止
docker compose down
# 禁止 down -v / volume prune；profile 切换后 release 并重新 acquire
```

启动完成后访问：

* core/content：直连 `http://localhost:${FRONTEND_PORT}`（canonical 默认 3000）
* full：`http://localhost:${NGINX_HTTP_PORT}`（canonical 默认 80）

### 5.4 开发模式（Windows）

```powershell
.\dev-start.ps1               # core：Docker 核心后端 + host Identity/Next.js
.\dev-start.ps1 -RuntimeProfile content # exact content 容器运行面
.\dev-start.ps1 -RuntimeProfile full    # exact full 容器运行面（含 Nginx）
.\dev-start.ps1 -SkipDocker   # 假设你已自己起好 PG/Redis
.\dev-start.ps1 -SkipFrontend # 只跑后端
.\dev-start.ps1 -Only knowledge-engine,frontend
.\dev-stop.ps1                # 全部停掉
```

> 开发模式下各端口默认只绑定 `127.0.0.1`，适合本机自用；不要把这些端口直接暴露到公网。

启动完成：

* 前端：<http://localhost:3000>
* Identity：<http://localhost:8000/health>
* AI Hub：<http://localhost:8001/health>
* Knowledge：<http://localhost:8002/health>
* 日志：`.dev-logs\<service>.log` 与 `.log.err`

### 5.5 一键备份（自用推荐）

```powershell
.\scripts\backup.ps1
# 或
npm run backup
```

备份会落到 `backups/omni-backup-<时间>/`，包含 PostgreSQL dump、Docker 全量模式的数据卷，以及开发模式下的 `services/*/data` 本地数据目录。

### 5.6 一键脚本（图形化）

* `启动全部.bat` → 调用 `dev-start.ps1` 并在浏览器打开 :3000
* `启动全部(包含Docker).bat` → 同上但会先确保 Docker Desktop 已开
* `停止全部.bat`、`停止全部(清理数据库).bat`

---

## 6. 模型 Provider 配置

支持 7 个 Provider，统一在 `ai-provider-hub` 注册：

| Provider | Key 环境变量 | 能力 | 备注 |
|---|---|---|---|
| OpenAI | `OPENAI_API_KEY` | chat / embedding / image | 国内需代理 |
| Gemini | `GEMINI_API_KEY` | chat / embedding / multimodal | 国内需代理；默认 chat provider |
| Anthropic | `ANTHROPIC_API_KEY` | chat | 国内需代理 |
| Deepseek | `DEEPSEEK_API_KEY` | chat | 国内直连 |
| Ollama | `OLLAMA_BASE_URL` | chat / embedding | 本地部署 |
| Seedance（火山方舟）| `ARK_API_KEY` | video generate / edit / extend | doubao-seedance-2-0 |
| Kling | `KLING_API_KEY` | video generate | 可灵视频 |

**两种配置方式（推荐方式 B）**：

* **A. 写 `.env`**：在 `services/ai-provider-hub/.env` 中填入对应 KEY，重启服务。
* **B. 通过 UI**：访问 `/models` 页面，输入 Key、选择默认模型、点"测试连接"，结果会持久化到 `ai_hub_data` 卷里的 `provider-config.json`。

---

## 7. API 网关路由（Nginx）

full profile 的外部访问统一走 :80；core/content 直连 frontend。Nginx 内置以下转发规则（详见 `services/infra-core/nginx/conf.d/default.conf`）：

```text
/                                  → frontend (含 Next.js HMR)
/api/v1/ai/*                       → ai-provider-hub
/v1/*                              → ai-provider-hub  (OpenAI 兼容)
/v1/chat/completions               → ai-provider-hub  (SSE，长连不缓冲)
/api/v1/ai/chat/stream             → ai-provider-hub  (SSE)
/api/v1/knowledge/*                → knowledge-engine (300s 超时)
/api/v1/knowledge/harvester/*      → knowledge-engine (600s 超时，给抓取留时间)
/api/v1/knowledge/rag              → knowledge-engine (SSE)
/api/v1/content-studio/*           → knowledge-engine (SSE，600s)
/api/v1/news/*                     → news-aggregator
/api/v1/video-analysis/*           → video-analysis   (600s)
/api/v1/livestream-analysis/*      → livestream-analysis (600s, 上传 2GB)
/api/v1/ad-review/*                → ad-review-service (SSE，600s)
```

### 7.1 OpenAI 兼容入口

任何 OpenAI 兼容 SDK 把 `base_url` 指到 `http://localhost/v1`、`api_key` 留空，即可调用本地 hub 转发的任意已配置模型。

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost/v1", api_key="not-required")
client.chat.completions.create(model="gemini-2.0-flash", messages=[{"role":"user","content":"hi"}])
```

---

## 8. 主要数据流

```
A. 知识沉淀
   上传文件 / 抓网页 → submit_ingestion_task (PG 任务表) → 后台 worker
   → chunking → embedding (经 ai-hub) → knowledge_chunks(+tsv jieba 分词)
   → 可选 GraphRAG 实体抽取

B. RAG 对话（SSE）
   /chat → POST /api/v1/knowledge/rag (stream)
   → query_enhancer → hybrid_search(向量+全文) → reranker → context_compressor
   → ai-hub /api/v1/ai/chat/stream → 浏览器流式渲染

C. 视频分析 → 自动入库
   video-analysis 完成报告 → add_knowledge_entry → POST /api/v1/knowledge/ingest

D. 投放复盘飞轮
   /ad-review 创建 Campaign → 上传千川 CSV / 关联人群包 / 关联素材
   → POST /api/v1/ad-review/campaigns/{id}/review (SSE)
   → review_engine: metrics + 视频分析 + KB RAG → LLM → Markdown + JSON 建议
   → sync_review_to_kb → /ad-review/flywheel 多轮 ROI 对比
```

---

## 9. 安全边界（单用户本机模式）

> 这是一个**为个人本机自用设计**的工具，不应直接暴露到公网或不可信局域网。

1. **无需登录**：浏览器、BFF、Knowledge Engine、Runtime Trace 和 Host Bridge 默认使用固定 `local-owner`，不生成或要求内部账号、密码、cookie、JWT、HMAC、Bearer Token。
2. **只绑本机**：Compose 发布端口默认带 `127.0.0.1:`；如手工改为 `0.0.0.0` 或接入公网代理，就超出了当前安全模型。
3. **写操作仍有边界**：浏览器变更请求校验 same-origin；删除、发布、付费和外部平台写入仍需显式确认并保留审计记录。
4. **外部凭据例外**：OpenAI、Gemini、抖音等外部平台自身要求的 Key/Cookie 可以按需配置；它们不是 Omni 内部登录凭据，也不应提交进仓库。
5. **遗留认证隔离**：`identity-service` 只保留历史源码和迁移，不进入 core/content/full 或 Nginx 路由。

---

## 10. 数据存储

| 卷 | 内容 |
|---|---|
| `postgres_data` | 全部业务数据（多 schema：`knowledge` / `news` / `ad_review` / `identity` / `video_analysis`） |
| `redis_data` | 限流计数 / 每日成本 / 视频任务态 |
| `ai_hub_data` | `/app/data/provider-config.json`（UI 配的 Key/默认模型） |
| `knowledge_data` | 抓取来的图片、PDF 等附件 |
| `video_analysis_data` | 上传的视频原始文件 + 报告 + 情感曲线图 |
| `livestream_analysis_data` | 直播切片 + Excel |
| `ad_review_data` | CSV 上传、解析后的 metrics |

> 备份建议：`pg_dump` + `docker run --rm -v omni_<vol>:/v -v $(pwd):/b alpine tar czf /b/<vol>.tgz -C /v .`，目前没有内置备份脚本。

---

## 11. 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 14（App Router）、TypeScript、Tailwind、shadcn/ui、Zustand、framer-motion、recharts |
| 前端图表/导出 | recharts、html2canvas、jspdf |
| AI SDK（前端） | `openai`、`@google/generative-ai`、`@anthropic-ai/sdk` |
| 后端 | Python 3.11+、FastAPI、Uvicorn、Pydantic v2、sse-starlette、structlog |
| 数据访问 | identity / news 用 SQLAlchemy 2.x Async + Alembic；knowledge / ad-review 用 asyncpg 裸 SQL |
| 中文分词 | jieba（写入 tsv 列） |
| 抓取 | Playwright（knowledge-engine harvester） |
| 多模态 | Gemini（短视频/直播切片） |
| 视频生成 | Seedance 2.0（火山方舟）、Kling |
| 容器 | Docker Compose（生产）+ Windows PowerShell 脚本（开发） |

---

## 12. 文档

* [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md) — 完整系统架构与缺陷评估
* [`docs/PRD-投放复盘系统.md`](docs/PRD-投放复盘系统.md) — Ad Review 模块 PRD
* [`docs/IMPL-投放复盘系统.md`](docs/IMPL-投放复盘系统.md) — Ad Review 实现说明
* [`docs/PRD-角色系统与圆桌会议.md`](docs/PRD-角色系统与圆桌会议.md) — Persona / 圆桌讨论 PRD
* [`docs/IMPL-角色系统与圆桌会议.md`](docs/IMPL-角色系统与圆桌会议.md) — 实现说明
* `docs/UAT-*.md` — 各模块 UAT 用例与执行记录

---

## 13. 已知限制 & Roadmap 候选

* 🟠 单用户本机信任模型不支持公网或多用户部署
* 🟠 `/models` 外部 Provider Key 管理仅适合本机使用
* 🟠 content/full 使用完整容器运行面；core 才提供 host 热重载
* 🟠 video-analysis 与 livestream-analysis 重复封装 GeminiClient
* 🟠 knowledge-engine 启动时硬改表（无 alembic）
* 🟡 多个前端 page.tsx 是 30~44KB 单文件巨石，待拆分
* 🟡 `apps/tri-mind-synthesizer`、`backend/`、`src/components/tri-mind/*` 是早期遗留，待清理
* 🟡 缺统一备份/导出脚本
* 🟡 测试基线缺失，UAT 全靠手点

---

## 14. License

MIT
