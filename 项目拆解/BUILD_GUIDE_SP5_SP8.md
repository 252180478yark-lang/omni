# Part 2 (续): SP#5 - SP#8 构建指南

---

## SP#5: langgraph-orchestrator — LangGraph 任务编排引擎

### 2.1 项目初始化指令

```bash
mkdir -p services/langgraph-orchestrator
cd services/langgraph-orchestrator

cat > pyproject.toml << 'EOF'
[project]
name = "langgraph-orchestrator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
    "httpx>=0.27.0",
    "structlog>=24.1.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
AI_PROVIDER_HUB_URL=http://localhost:8001
KNOWLEDGE_ENGINE_URL=http://localhost:8002
DEFAULT_ORCHESTRATOR_MODEL=gemini
MAX_ITERATIONS=5
SERVICE_NAME=langgraph-orchestrator
SERVICE_PORT=8003
EOF

python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 2.2 核心文件清单

```
services/langgraph-orchestrator/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── task_log.py                # 任务执行日志模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── orchestration.py           # TaskRequest, TaskResult 等
│   ├── routers/
│   │   ├── __init__.py
│   │   └── orchestrate.py             # /api/v1/orchestrate/* 路由
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py                   # LangGraph State 定义
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── planner.py             # Controller/Planner 节点
│   │   │   ├── executor.py            # 工具执行节点
│   │   │   └── reviewer.py            # 输出审查节点
│   │   ├── edges.py                   # 条件边（路由逻辑）
│   │   └── builder.py                 # StateGraph 构建器
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py                # 工具注册表
│   │   ├── knowledge_tool.py          # 知识查询工具
│   │   ├── content_tool.py            # 内容生成工具
│   │   └── web_search_tool.py         # Web 搜索工具
│   └── services/
│       ├── __init__.py
│       ├── ai_client.py               # AI Provider Hub 客户端
│       └── task_service.py            # 任务管理服务
└── tests/
    └── test_graph.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/4: [LangGraph State + 节点定义]**

```
角色：你是一名 AI 编排工程师，精通 LangGraph。

上下文：Omni-Vibe OS 的思考环使用 LangGraph 实现 Plan → Execute → Review 三步闭环。

请生成：

1. `app/graph/state.py`：
   - OrchestratorState(TypedDict)：
     - user_query: str（用户输入）
     - plan: list[PlanStep]（执行计划）
     - current_step: int
     - results: list[StepResult]（每步结果）
     - review_feedback: str（审查反馈）
     - iteration: int（当前迭代次数）
     - max_iterations: int（最大迭代）
     - final_answer: str（最终回答）
     - status: Literal["planning", "executing", "reviewing", "done", "failed"]

2. `app/graph/nodes/planner.py`：
   - plan_node(state) -> dict
   - 调用 AI Provider Hub 的 chat API
   - 系统提示词：分析用户意图，生成执行计划
   - 输出格式化的 PlanStep 列表（每步包含 tool_name, arguments, expected_output）

3. `app/graph/nodes/executor.py`：
   - execute_node(state) -> dict
   - 根据当前 PlanStep 调用对应工具
   - 从 ToolRegistry 查找工具并执行
   - 收集执行结果

4. `app/graph/nodes/reviewer.py`：
   - review_node(state) -> dict
   - 调用 AI 评估当前结果质量
   - 决策：accept（完成）/ refine（重新规划）/ retry（重试当前步骤）
   - 如果超过 max_iterations，强制完成

5. `app/graph/edges.py`：
   - should_continue(state) -> str
   - 根据 reviewer 的决策路由：
     - "accept" → END
     - "refine" → planner
     - "retry" → executor
   - 超过 max_iterations → END

6. `app/graph/builder.py`：
   - build_orchestrator_graph() -> CompiledGraph
   - 使用 StateGraph 构建图
   - 节点：planner, executor, reviewer
   - 边：planner → executor → reviewer → (conditional)

技术约束：
- LangGraph >= 0.2.0
- 使用 TypedDict 定义 State（不是 Pydantic）
- 所有节点函数返回 partial state dict
- 中英双语注释
- 每个节点记录 structlog 日志

输出：完整文件内容。
```

**验证方式**：
```python
from app.graph.builder import build_orchestrator_graph
graph = build_orchestrator_graph()
print(graph.get_graph().draw_ascii())  # 打印图结构
```

---

**Prompt 2/4: [工具注册表 + 内置工具]**

```
角色：你是一名 AI 工具链工程师。

请生成工具系统：

1. `app/tools/registry.py`：
   - ToolRegistry 类
   - register(name, description, func, parameters_schema)
   - get(name) -> Tool
   - list_tools() -> list[ToolInfo]
   - execute(name, arguments) -> ToolResult
   - 自动生成工具描述给 LLM 使用

2. `app/tools/knowledge_tool.py`：
   - 工具名：knowledge_query
   - 调用 Knowledge Engine 的 /api/v1/knowledge/query
   - 参数：query, kb_id, top_k

3. `app/tools/content_tool.py`：
   - 工具名：generate_image
   - 调用 Content Factory 的 /api/v1/content/generate-image
   - 参数：prompt, style, size

4. `app/tools/web_search_tool.py`：
   - 工具名：web_search
   - 使用 httpx 调用搜索 API（预留接口）
   - 参数：query, num_results

5. `app/services/ai_client.py`：
   - AIProviderClient 类（httpx 封装）
   - chat(messages, provider, model) -> str
   - chat_with_json(messages, provider, model) -> dict（强制 JSON 输出）

技术约束：
- 所有工具调用为 async
- 统一 ToolResult(success: bool, data: Any, error: str | None)
- 工具超时 60 秒

输出：完整文件内容。
```

---

**Prompt 3/4: [API 路由 + 任务日志]**

```
角色：你是一名后端工程师。

请生成：

1. `app/models/task_log.py`：
   - TaskLog 模型：id, user_id, query, plan_json, results_json, final_answer, status, duration_ms, created_at
   - 存储到 PostgreSQL

2. `app/services/task_service.py`：
   - run_task(user_id, query) -> TaskResult
   - 构建 graph → 执行 → 记录日志
   - 支持流式输出（yield 每步结果）

3. `app/routers/orchestrate.py`：
   - POST /api/v1/orchestrate/run （同步执行，返回最终结果）
   - POST /api/v1/orchestrate/run/stream （SSE 流式，逐步返回）
   - GET /api/v1/orchestrate/tasks （查询历史任务）
   - GET /api/v1/orchestrate/tasks/{id} （查询任务详情）

4. `app/schemas/orchestration.py`：
   - TaskRequest(query, kb_id?, max_iterations?)
   - TaskResult(task_id, query, plan, results, final_answer, status, duration_ms)
   - StreamEvent(step, type, data)

5. `app/main.py`：完整的 FastAPI 入口

输出：完整文件内容。
```

**验证方式**：
```bash
curl -X POST http://localhost:8003/api/v1/orchestrate/run \
  -H "Content-Type: application/json" \
  -d '{"query":"帮我分析最近的电商市场趋势"}'
```

---

**Prompt 4/4: [Dockerfile + 测试 + README]**

与前面子项目类似，生成 Dockerfile、测试和 README。

### 2.4 集成测试方案

**关键 API 端点：**
```
POST /api/v1/orchestrate/run          → 执行任务
POST /api/v1/orchestrate/run/stream   → 流式执行任务
GET  /api/v1/orchestrate/tasks        → 历史任务列表
GET  /api/v1/orchestrate/tasks/{id}   → 任务详情
```

**依赖验证：**
```bash
curl http://ai-provider-hub:8001/api/v1/ai/providers
curl http://knowledge-engine:8002/health
```

### 2.5 Git 操作指令

```bash
git checkout -b feat/sp5-langgraph-orchestrator
git add services/langgraph-orchestrator/
git commit -m "feat(orchestrator): add LangGraph task orchestration engine

- Plan → Execute → Review closed loop
- Tool registry with knowledge/content/search tools
- Reviewer agent with retry/refine logic
- Task history logging
- SSE streaming for step-by-step results"

git push origin feat/sp5-langgraph-orchestrator
```

---

## SP#6: content-factory — AI 内容生产工厂

### 2.1 项目初始化指令

```bash
mkdir -p services/content-factory
cd services/content-factory

cat > pyproject.toml << 'EOF'
[project]
name = "content-factory"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "celery[redis]>=5.4.0",
    "redis>=5.0.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "httpx>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
    "Pillow>=10.0.0",
    "structlog>=24.1.0",
    "python-multipart>=0.0.9",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
REDIS_URL=redis://:changeme_redis@localhost:6379/0
AI_PROVIDER_HUB_URL=http://localhost:8001
COMFYUI_URL=http://localhost:8188
MIDJOURNEY_API_URL=https://api.example.com/mj
MIDJOURNEY_API_KEY=your-key
KLING_API_URL=https://api.example.com/kling
KLING_API_KEY=your-key
FFMPEG_PATH=/usr/bin/ffmpeg
OUTPUT_DIR=/app/outputs
SERVICE_NAME=content-factory
SERVICE_PORT=8004
EOF

python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 2.2 核心文件清单

```
services/content-factory/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── content_task.py            # 内容任务模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── content.py                 # 任务请求/响应
│   ├── routers/
│   │   ├── __init__.py
│   │   └── content.py                 # /api/v1/content/* 路由
│   ├── services/
│   │   ├── __init__.py
│   │   ├── comfyui_client.py          # ComfyUI WebSocket API
│   │   ├── midjourney_client.py       # Midjourney API 代理
│   │   ├── kling_client.py            # Kling 视频 API
│   │   ├── ffmpeg_service.py          # FFmpeg 视频处理
│   │   └── task_manager.py            # 异步任务管理
│   ├── workflows/
│   │   ├── __init__.py
│   │   ├── image_gen.py               # 图片生成工作流
│   │   └── video_gen.py               # 视频生成工作流
│   └── celery_tasks/
│       ├── __init__.py
│       ├── celery_app.py
│       └── content_tasks.py           # Celery 内容生成任务
├── comfyui_workflows/
│   ├── txt2img_sdxl.json              # SDXL 文生图工作流
│   └── img2img_sdxl.json              # SDXL 图生图工作流
└── tests/
    └── test_content.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/4: [ComfyUI 客户端 + 图片生成工作流]**

```
角色：你是一名 AI 图像工程师，精通 ComfyUI API。

上下文：Content Factory 需要通过 ComfyUI 的 WebSocket API 进行本地图片生成。

请生成：

1. `app/services/comfyui_client.py`：
   - ComfyUIClient 类
   - 方法：
     - async queue_prompt(workflow_json: dict) -> str（返回 prompt_id）
     - async get_progress(prompt_id: str) -> ProgressInfo
     - async get_result(prompt_id: str) -> list[ImageResult]
     - async txt2img(prompt: str, negative_prompt: str, width: int, height: int, steps: int, cfg: float, seed: int) -> list[bytes]
   - 通过 WebSocket 连接 ComfyUI 获取进度
   - 通过 HTTP 获取生成的图片

2. `comfyui_workflows/txt2img_sdxl.json`：
   - SDXL 标准文生图工作流模板
   - 支持参数化替换（prompt, negative_prompt, width, height, steps, cfg, seed）

3. `app/workflows/image_gen.py`：
   - ImageGenWorkflow 类
   - generate(request: ImageGenRequest) -> ImageResult
   - 流程：
     1. 加载工作流模板
     2. 替换参数
     3. 提交到 ComfyUI
     4. 等待完成
     5. 下载并保存结果

技术约束：
- ComfyUI API 地址通过环境变量配置
- WebSocket 超时 300 秒
- 生成结果保存到 OUTPUT_DIR
- 使用 httpx + websockets

输出：完整文件内容。
```

---

**Prompt 2/4: [Midjourney + Kling 客户端 + FFmpeg 服务]**

```
角色：你是一名多媒体工程师。

请生成：

1. `app/services/midjourney_client.py`：
   - MidjourneyClient 类（通过第三方 API 代理）
   - imagine(prompt, aspect_ratio, style) -> TaskID
   - upscale(task_id, index) -> ImageURL
   - get_status(task_id) -> TaskStatus
   - 轮询等待结果

2. `app/services/kling_client.py`：
   - KlingClient 类
   - generate_video(prompt, duration, aspect_ratio) -> TaskID
   - img2video(image_url, prompt) -> TaskID
   - get_status(task_id) -> TaskStatus
   - download_video(task_id) -> bytes

3. `app/services/ffmpeg_service.py`：
   - FFmpegService 类
   - add_watermark(video_path, watermark_path, position) -> output_path
   - concat_videos(video_paths, output_path) -> output_path
   - add_subtitles(video_path, srt_path) -> output_path
   - extract_audio(video_path) -> audio_path
   - compress_video(video_path, target_size_mb) -> output_path
   - 使用 subprocess 调用 ffmpeg 命令

技术约束：
- 所有外部 API 调用使用 httpx
- FFmpeg 使用 subprocess.run，处理 stderr 输出
- 超时和重试配置

输出：完整文件内容。
```

---

**Prompt 3/4: [Celery 任务 + API 路由 + 任务管理]**

```
角色：你是一名后端工程师。

请生成：

1. `app/models/content_task.py`：
   - ContentTask 模型：id, user_id, type(enum: image/video/edit), provider, params_json, status, result_url, error_message, progress, created_at, completed_at

2. `app/celery_tasks/content_tasks.py`：
   - generate_image_task.delay(task_id, params)
   - generate_video_task.delay(task_id, params)
   - process_video_task.delay(task_id, params)
   - 每个 Celery 任务更新 ContentTask 状态和进度

3. `app/services/task_manager.py`：
   - create_task(user_id, type, params) -> ContentTask
   - get_task(task_id) -> ContentTask
   - list_tasks(user_id, status, page, size) -> list[ContentTask]

4. `app/routers/content.py`：
   - POST /api/v1/content/generate-image （提交图片生成任务）
   - POST /api/v1/content/generate-video （提交视频生成任务）
   - POST /api/v1/content/process-video （提交视频后处理任务）
   - GET /api/v1/content/tasks （查询任务列表）
   - GET /api/v1/content/tasks/{id} （查询任务状态/结果）
   - GET /api/v1/content/tasks/{id}/download （下载生成结果）

5. `app/schemas/content.py`：全部 Schema

6. `app/main.py`：完整入口

输出：完整文件内容。
```

**验证方式**：
```bash
# 提交图片生成任务
curl -X POST http://localhost:8004/api/v1/content/generate-image \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a beautiful sunset over mountains","provider":"comfyui","width":1024,"height":1024}'

# 查询任务状态
curl http://localhost:8004/api/v1/content/tasks/<task_id>
```

---

**Prompt 4/4: [Dockerfile + README]** — 略（同模式）

### 2.4 / 2.5 — 同前述模式

---

## SP#7: market-intelligence — 全域电商情报

### 2.1 项目初始化指令

```bash
mkdir -p services/market-intelligence
cd services/market-intelligence

cat > pyproject.toml << 'EOF'
[project]
name = "market-intelligence"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "celery[redis]>=5.4.0",
    "redis>=5.0.0",
    "DrissionPage>=4.1.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "httpx>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
    "structlog>=24.1.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
REDIS_URL=redis://:changeme_redis@localhost:6379/0
KNOWLEDGE_ENGINE_URL=http://localhost:8002
AI_PROVIDER_HUB_URL=http://localhost:8001
CHROME_PATH=/usr/bin/chromium-browser
SERVICE_NAME=market-intelligence
SERVICE_PORT=8005
EOF

python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 2.2 核心文件清单

```
services/market-intelligence/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── crawl_task.py              # 爬取任务模型
│   │   └── product.py                 # 商品 + 评论模型
│   ├── schemas/
│   │   └── intel.py
│   ├── routers/
│   │   └── intel.py                   # /api/v1/intel/*
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base_scraper.py            # 爬虫基类
│   │   ├── taobao_scraper.py          # 淘宝爬虫
│   │   ├── jd_scraper.py              # 京东爬虫
│   │   └── amazon_scraper.py          # Amazon 爬虫
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── sentiment.py               # 情感分析
│   │   ├── competitor.py              # 竞品分析
│   │   └── price_monitor.py           # 价格监控
│   ├── celery_tasks/
│   │   ├── celery_app.py
│   │   └── crawl_tasks.py
│   └── services/
│       ├── crawl_service.py
│       └── analysis_service.py
└── tests/
    └── test_scrapers.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/3: [DrissionPage 爬虫框架 + 多平台爬虫]**

```
角色：你是一名网络爬虫工程师，精通 DrissionPage。

上下文：Market Intelligence 模块需要爬取多个电商平台的商品和评论数据。

请生成：

1. `app/scrapers/base_scraper.py`：
   - BaseScraper 抽象类
   - 方法：
     - async scrape_product(url) -> ProductData
     - async scrape_reviews(product_id, pages) -> list[ReviewData]
     - async search_products(keyword, max_results) -> list[ProductData]
   - 内置：随机延迟、User-Agent 轮换、代理支持
   - 使用 DrissionPage 的 ChromiumPage 模式

2. `app/scrapers/taobao_scraper.py`：继承 BaseScraper
   - 搜索商品
   - 抽取：标题、价格、销量、店铺名、评分
   - 评论抽取

3. `app/scrapers/jd_scraper.py`：继承 BaseScraper（类似结构）

4. `app/scrapers/amazon_scraper.py`：继承 BaseScraper

5. `app/models/product.py`：
   - Product 模型：id, platform, product_id, title, price, sales, rating, shop_name, url, metadata_json, last_crawled
   - Review 模型：id, product_id, reviewer, rating, content, date, sentiment_score

技术约束：
- DrissionPage 4.1+
- 每次请求间隔 2-5 秒随机延迟
- 爬取失败时自动重试 3 次
- 所有数据存 PostgreSQL (schema: market_intel)
- 不硬编码任何选择器（通过配置文件管理）

输出：完整文件内容。
```

---

**Prompt 2/3: [分析服务 + 知识入库]**

```
角色：你是一名数据分析工程师。

请生成：

1. `app/analyzers/sentiment.py`：
   - 调用 AI Provider Hub 进行评论情感分析
   - 批量处理评论（每批 50 条）
   - 输出：positive/neutral/negative + 评分 0-1
   - 提取关键卖点和痛点

2. `app/analyzers/competitor.py`：
   - 竞品对比分析
   - 价格区间、销量分布、评分对比
   - 生成分析报告（调用 AI 总结）

3. `app/analyzers/price_monitor.py`：
   - 价格历史记录
   - 价格变动检测 + 通知
   - 支持设置价格阈值告警

4. `app/services/analysis_service.py`：
   - 分析完成后自动将商品和评论数据入库 Knowledge Engine
   - 调用 /api/v1/knowledge/ingest

输出：完整文件内容。
```

---

**Prompt 3/3: [Celery 定时任务 + API 路由]**

```
角色：你是一名后端工程师。

请生成：

1. `app/celery_tasks/crawl_tasks.py`：
   - crawl_product_task（爬取指定商品）
   - crawl_search_task（搜索并爬取结果）
   - scheduled_price_check（定时价格检查 - Celery Beat）

2. `app/routers/intel.py`：
   - POST /api/v1/intel/crawl （提交爬取任务）
   - POST /api/v1/intel/analyze （提交分析任务）
   - GET /api/v1/intel/products （查询已爬取商品）
   - GET /api/v1/intel/products/{id}/reviews （查询商品评论）
   - GET /api/v1/intel/products/{id}/price-history （价格历史）
   - GET /api/v1/intel/reports （分析报告列表）

3. 完整的 Schema、main.py 和 Dockerfile

输出：完整文件内容。
```

**验证方式**：
```bash
curl -X POST http://localhost:8005/api/v1/intel/crawl \
  -H "Content-Type: application/json" \
  -d '{"platform":"amazon","keyword":"wireless earbuds","max_results":10}'
```

### 2.4 / 2.5 — 同前述模式

---

## SP#8: ops-assistant — 运营自动化助手

### 2.1 项目初始化指令

```bash
mkdir -p services/ops-assistant
cd services/ops-assistant

cat > pyproject.toml << 'EOF'
[project]
name = "ops-assistant"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "celery[redis]>=5.4.0",
    "redis>=5.0.0",
    "DrissionPage>=4.1.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "httpx>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
    "structlog>=24.1.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
REDIS_URL=redis://:changeme_redis@localhost:6379/0
AI_PROVIDER_HUB_URL=http://localhost:8001
WECHATY_TOKEN=your-wechaty-puppet-token
WECHATY_ENDPOINT=http://localhost:8788
SERVICE_NAME=ops-assistant
SERVICE_PORT=8006
EOF
```

### 2.2 核心文件清单

```
services/ops-assistant/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── reply_template.py          # 回复模板
│   │   ├── price_rule.py              # 定价规则
│   │   └── ops_log.py                 # 操作日志
│   ├── schemas/
│   │   └── ops.py
│   ├── routers/
│   │   └── ops.py                     # /api/v1/ops/*
│   ├── rpa/
│   │   ├── __init__.py
│   │   ├── base_bot.py                # RPA 基类
│   │   ├── reply_bot.py               # 自动回复机器人
│   │   └── price_bot.py               # 自动改价机器人
│   ├── wechaty/
│   │   ├── __init__.py
│   │   └── wechat_bot.py              # Wechaty 微信机器人
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── reply_strategy.py          # 回复策略（模板 + AI）
│   │   └── pricing_strategy.py        # 定价策略（规则 + AI）
│   ├── celery_tasks/
│   │   ├── celery_app.py
│   │   └── ops_tasks.py
│   └── services/
│       └── ops_service.py
└── tests/
    └── test_ops.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/3: [RPA 机器人框架]**

```
角色：你是一名 RPA 工程师，精通浏览器自动化。

请生成：

1. `app/rpa/base_bot.py`：
   - BaseBot 抽象类（使用 DrissionPage）
   - login(credentials) / execute_action(action) / screenshot()
   - 内置：操作日志记录、截图存档、错误恢复

2. `app/rpa/reply_bot.py`：
   - AutoReplyBot（电商后台自动回复）
   - 流程：登录 → 获取未回复消息 → AI 生成回复 → 发送
   - 支持多平台配置（淘宝/拼多多/抖音）

3. `app/rpa/price_bot.py`：
   - AutoPriceBot（电商后台自动改价）
   - 流程：登录 → 获取当前价格 → 应用定价策略 → 修改价格
   - 改价前截图存档（审计追踪）

4. `app/strategies/reply_strategy.py`：
   - TemplateReply（基于模板匹配）
   - AIReply（调用 AI Provider Hub 生成回复）
   - HybridReply（先匹配模板，无匹配则用 AI）

5. `app/strategies/pricing_strategy.py`：
   - RuleBasedPricing（基于规则：不低于成本价、跟随竞品）
   - AIPricing（AI 分析市场后给出建议价）

技术约束：
- 所有 RPA 操作记录到 ops_log 表
- 改价操作需要二次确认（除非配置为自动模式）
- 每次操作截图保存

输出：完整文件内容。
```

---

**Prompt 2/3: [Wechaty 私域管理]**

```
角色：你是一名微信生态开发者。

请生成：

1. `app/wechaty/wechat_bot.py`：
   - WechatBot 类（通过 Wechaty HTTP API 通信）
   - 功能：
     - on_message(callback) 消息监听
     - send_message(contact_id, content)
     - send_group_message(room_id, content)
     - get_contacts() 获取联系人列表
     - get_rooms() 获取群组列表
   - AI 自动回复集成
   - 关键词触发特定操作

注意：Wechaty 作为 Node.js sidecar 运行，Python 通过 HTTP API 通信。

输出：完整文件内容。
```

---

**Prompt 3/3: [API 路由 + Celery 任务]**

```
请生成：

1. `app/routers/ops.py`：
   - POST /api/v1/ops/auto-reply/start （启动自动回复）
   - POST /api/v1/ops/auto-reply/stop （停止自动回复）
   - POST /api/v1/ops/price-adjust （提交改价任务）
   - GET /api/v1/ops/price-rules （获取定价规则）
   - PUT /api/v1/ops/price-rules/{id} （更新定价规则）
   - POST /api/v1/ops/wechat/send （发送微信消息）
   - GET /api/v1/ops/logs （操作日志）

2. Celery 任务、Schema、模型、Dockerfile、README

输出：完整文件内容。
```

**验证方式**：
```bash
curl -X POST http://localhost:8006/api/v1/ops/auto-reply/start \
  -H "Content-Type: application/json" \
  -d '{"platform":"taobao","mode":"hybrid"}'
```

### 2.4 / 2.5 — 同前述模式
