# Part 2 (续): SP#9 - SP#11 构建指南

---

## SP#9: second-brain — 个人第二大脑

### 2.1 项目初始化指令

```bash
mkdir -p services/second-brain
cd services/second-brain

cat > pyproject.toml << 'EOF'
[project]
name = "second-brain"
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
    "faster-whisper>=1.0.0",
    "paddleocr>=2.8.0",
    "paddlepaddle>=2.6.0",
    "PyMuPDF>=1.24.0",
    "python-docx>=1.1.0",
    "python-multipart>=0.0.9",
    "structlog>=24.1.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
REDIS_URL=redis://:changeme_redis@localhost:6379/0
KNOWLEDGE_ENGINE_URL=http://localhost:8002
AI_PROVIDER_HUB_URL=http://localhost:8001
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cuda
OCR_LANG=ch
UPLOAD_DIR=/app/uploads
SERVICE_NAME=second-brain
SERVICE_PORT=8007
EOF

python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 2.2 核心文件清单

```
services/second-brain/
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
│   │   └── upload.py                  # Upload 记录模型
│   ├── schemas/
│   │   └── brain.py
│   ├── routers/
│   │   └── brain.py                   # /api/v1/brain/*
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── base.py                    # 处理器基类
│   │   ├── ocr_processor.py           # OCR 处理器
│   │   ├── whisper_processor.py       # 语音转写处理器
│   │   ├── pdf_processor.py           # PDF 解析处理器
│   │   ├── docx_processor.py          # DOCX 解析处理器
│   │   └── markdown_processor.py      # Markdown 解析处理器
│   ├── services/
│   │   ├── __init__.py
│   │   ├── upload_service.py          # 文件上传管理
│   │   ├── process_service.py         # 统一处理管道
│   │   └── summary_service.py         # AI 摘要 + 关键词提取
│   └── celery_tasks/
│       ├── celery_app.py
│       └── brain_tasks.py             # 异步处理任务
└── tests/
    └── test_processors.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/3: [文件处理器 + OCR + Whisper]**

```
角色：你是一名文档处理工程师，精通 OCR 和语音识别。

上下文：Second Brain 需要将各种格式的非结构化数据（图片、音频、PDF、文档）转化为结构化文本并入库知识引擎。

请生成：

1. `app/processors/base.py`：
   - BaseProcessor 抽象类
   - process(file_path: Path, **kwargs) -> ProcessResult
   - ProcessResult(text: str, metadata: dict, chunks: list[str])
   - supported_extensions: list[str]

2. `app/processors/ocr_processor.py`：
   - OCRProcessor（使用 PaddleOCR）
   - 支持格式：.png, .jpg, .jpeg, .bmp, .tiff
   - 中英文混合识别
   - 输出带坐标的文本结构
   - GPU 加速（如可用）

3. `app/processors/whisper_processor.py`：
   - WhisperProcessor（使用 faster-whisper）
   - 支持格式：.mp3, .wav, .m4a, .flac, .ogg
   - 支持中英文自动检测
   - 输出带时间戳的逐句转写
   - 模型可配置（tiny/base/small/medium/large-v3）
   - GPU 加速

4. `app/processors/pdf_processor.py`：
   - PDFProcessor（使用 PyMuPDF/fitz）
   - 提取文本 + 表格 + 图片中的文字（调用 OCR）
   - 保留页码和段落结构

5. `app/processors/docx_processor.py`：
   - DocxProcessor（使用 python-docx）
   - 提取文本 + 表格 + 标题层级

6. `app/processors/markdown_processor.py`：
   - MarkdownProcessor
   - 直接读取文本

技术约束：
- PaddleOCR 使用 PP-OCRv4 模型
- faster-whisper 使用 CTranslate2 后端
- 文件大小限制 100MB
- 处理超时 600 秒
- 中英双语注释

输出：完整文件内容。
```

---

**Prompt 2/3: [处理管道 + AI 摘要 + 知识入库]**

```
角色：你是一名 NLP 工程师。

请生成：

1. `app/services/upload_service.py`：
   - 文件上传 + 保存
   - 根据扩展名路由到对应处理器
   - 创建 Upload 记录

2. `app/services/process_service.py`：
   - ProcessPipeline 类
   - process(upload_id) -> ProcessResult
   - 流程：
     1. 读取文件
     2. 路由到对应处理器
     3. 生成文本
     4. AI 摘要 + 关键词提取
     5. 调用 Knowledge Engine 入库

3. `app/services/summary_service.py`：
   - summarize(text, max_length) -> str（调用 AI Provider Hub）
   - extract_keywords(text, top_k) -> list[str]
   - generate_title(text) -> str

4. `app/models/upload.py`：
   - Upload 模型：id, user_id, filename, file_path, file_type, file_size, status, processed_text(摘要), metadata_json, created_at

输出：完整文件内容。
```

---

**Prompt 3/3: [API 路由 + Celery 任务 + Dockerfile]**

```
请生成：

1. `app/routers/brain.py`：
   - POST /api/v1/brain/upload （上传文件，返回 upload_id）
   - POST /api/v1/brain/transcribe （上传音频并转写）
   - POST /api/v1/brain/ocr （上传图片并 OCR）
   - GET /api/v1/brain/uploads （查询上传记录）
   - GET /api/v1/brain/uploads/{id} （获取处理结果）
   - POST /api/v1/brain/batch-upload （批量上传）

2. `app/celery_tasks/brain_tasks.py`：
   - process_upload_task.delay(upload_id)
   - batch_process_task.delay(upload_ids)

3. `Dockerfile`：
   - 基于 python:3.11-slim
   - 安装 PaddlePaddle + PaddleOCR 依赖
   - 安装 ffmpeg（Whisper 需要）
   - 非 root 用户

4. 完整 Schema + main.py + README

输出：完整文件内容。
```

**验证方式**：
```bash
# 上传 PDF
curl -X POST http://localhost:8007/api/v1/brain/upload \
  -F "file=@test.pdf"

# 语音转写
curl -X POST http://localhost:8007/api/v1/brain/transcribe \
  -F "file=@meeting.mp3"

# OCR
curl -X POST http://localhost:8007/api/v1/brain/ocr \
  -F "file=@screenshot.png"
```

### 2.4 集成测试方案

**关键 API 端点：**
```
POST /api/v1/brain/upload       → 上传并处理文件
POST /api/v1/brain/transcribe   → 语音转写
POST /api/v1/brain/ocr          → 图片 OCR
GET  /api/v1/brain/uploads      → 上传记录
```

**依赖验证：**
```bash
curl http://knowledge-engine:8002/health
curl http://ai-provider-hub:8001/health
```

### 2.5 Git 操作指令

```bash
git checkout -b feat/sp9-second-brain
git add services/second-brain/
git commit -m "feat(brain): add second brain with OCR/Whisper/PDF processing

- PaddleOCR for image text extraction
- faster-whisper for audio transcription
- PyMuPDF for PDF parsing
- AI-powered summarization + keyword extraction
- Auto-ingest to knowledge engine"

git push origin feat/sp9-second-brain
```

---

## SP#10: evolution-engine — 自进化引擎

### 2.1 项目初始化指令

```bash
mkdir -p services/evolution-engine
cd services/evolution-engine

cat > pyproject.toml << 'EOF'
[project]
name = "evolution-engine"
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
    "structlog>=24.1.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
REDIS_URL=redis://:changeme_redis@localhost:6379/0
AI_PROVIDER_HUB_URL=http://localhost:8001
LLAMA_FACTORY_PATH=/opt/LLaMA-Factory
LORA_OUTPUT_DIR=/app/lora_adapters
TRAINING_GPU_DEVICE=0
NIGHTLY_TRAIN_CRON="0 2 * * *"
SERVICE_NAME=evolution-engine
SERVICE_PORT=8008
EOF
```

### 2.2 核心文件清单

```
services/evolution-engine/
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
│   │   ├── feedback.py                # 反馈日志模型
│   │   ├── training_job.py            # 训练任务模型
│   │   └── lora_adapter.py            # LoRA 适配器模型
│   ├── schemas/
│   │   └── evolution.py
│   ├── routers/
│   │   └── evolution.py               # /api/v1/evolution/*
│   ├── services/
│   │   ├── __init__.py
│   │   ├── feedback_service.py        # 反馈收集 + 数据集构建
│   │   ├── dataset_builder.py         # 对话 → SFT 数据集格式
│   │   ├── training_service.py        # LLaMA-Factory 调用封装
│   │   ├── adapter_manager.py         # LoRA 版本管理 + 热加载
│   │   └── ab_test_service.py         # A/B 测试框架
│   └── celery_tasks/
│       ├── celery_app.py
│       └── training_tasks.py          # 夜间训练任务
├── training_configs/
│   ├── sft_qwen2.5_lora.yaml         # QWen2.5 LoRA 微调配置
│   └── dpo_config.yaml                # DPO 训练配置
└── tests/
    └── test_evolution.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/3: [反馈收集 + 数据集构建]**

```
角色：你是一名 MLOps 工程师，精通 LLM 微调。

上下文：Evolution Engine 收集用户对 AI 回答的反馈，构建 SFT 数据集用于夜间微调。

请生成：

1. `app/models/feedback.py`：
   - Feedback 模型：id, user_id, task_id, query, response, rating(1-5), comment, is_used_for_training, created_at

2. `app/models/training_job.py`：
   - TrainingJob 模型：id, dataset_size, model_name, adapter_name, status(pending/running/completed/failed), metrics_json, started_at, completed_at, error_message

3. `app/models/lora_adapter.py`：
   - LoRAAdapter 模型：id, training_job_id, adapter_name, adapter_path, base_model, version, is_active, metrics_json, created_at

4. `app/services/feedback_service.py`：
   - submit_feedback(user_id, task_id, query, response, rating, comment)
   - get_training_candidates(min_rating, limit) -> list[Feedback]
   - 高评分(4-5)作为正例，低评分(1-2)作为负例

5. `app/services/dataset_builder.py`：
   - build_sft_dataset(feedbacks) -> Path（生成 JSON Lines 格式）
   - 格式：{"instruction": "...", "input": "...", "output": "..."}
   - build_dpo_dataset(positive, negative) -> Path
   - 格式：{"prompt": "...", "chosen": "...", "rejected": "..."}
   - 数据清洗：去重、过滤敏感内容、截断过长文本

技术约束：
- SFT 数据格式兼容 LLaMA-Factory
- DPO 数据格式兼容 LLaMA-Factory
- 每次构建记录数据集统计信息

输出：完整文件内容。
```

---

**Prompt 2/3: [LLaMA-Factory 训练封装 + LoRA 管理]**

```
角色：你是一名 MLOps 工程师。

请生成：

1. `app/services/training_service.py`：
   - TrainingService 类
   - start_training(dataset_path, config) -> TrainingJob
   - 调用 LLaMA-Factory CLI：
     llamafactory-cli train config.yaml
   - 监控训练进度（读取日志文件）
   - 训练完成后自动注册 LoRA 适配器

2. `training_configs/sft_qwen2.5_lora.yaml`：
   - LLaMA-Factory 配置文件
   - 模型：Qwen2.5-7B
   - 方法：LoRA (r=16, alpha=32, dropout=0.05)
   - 训练参数：lr=2e-4, epochs=3, batch_size=4, gradient_accumulation=4
   - 参数化模板（dataset_path, output_dir 可替换）

3. `app/services/adapter_manager.py`：
   - AdapterManager 类
   - register_adapter(training_job_id, adapter_path) -> LoRAAdapter
   - activate_adapter(adapter_id) （设为当前活跃适配器）
   - deactivate_adapter(adapter_id)
   - list_adapters(model_name, is_active) -> list[LoRAAdapter]
   - get_active_adapter(model_name) -> LoRAAdapter | None
   - 通知 AI Provider Hub 加载新适配器（通过 HTTP 回调）

4. `app/services/ab_test_service.py`：
   - ABTestService
   - create_test(adapter_a_id, adapter_b_id, sample_size) -> ABTest
   - record_result(test_id, variant, user_rating)
   - evaluate_test(test_id) -> ABTestResult（含统计显著性检验）

输出：完整文件内容。
```

---

**Prompt 3/3: [Celery Beat 夜间任务 + API 路由]**

```
请生成：

1. `app/celery_tasks/training_tasks.py`：
   - nightly_training_task（Celery Beat 定时任务）：
     1. 收集当天新反馈
     2. 构建 SFT 数据集
     3. 启动 LLaMA-Factory 训练
     4. 注册新 LoRA 适配器
     5. 记录训练指标

2. `app/routers/evolution.py`：
   - POST /api/v1/evolution/feedback （提交反馈）
   - GET /api/v1/evolution/feedback （查询反馈列表）
   - POST /api/v1/evolution/train （手动触发训练）
   - GET /api/v1/evolution/jobs （训练任务列表）
   - GET /api/v1/evolution/jobs/{id} （训练任务详情）
   - GET /api/v1/evolution/adapters （LoRA 适配器列表）
   - PUT /api/v1/evolution/adapters/{id}/activate （激活适配器）
   - POST /api/v1/evolution/ab-test （创建 A/B 测试）
   - GET /api/v1/evolution/ab-test/{id} （A/B 测试结果）

3. 完整 Schema + main.py + Dockerfile + README

输出：完整文件内容。
```

**验证方式**：
```bash
# 提交反馈
curl -X POST http://localhost:8008/api/v1/evolution/feedback \
  -H "Content-Type: application/json" \
  -d '{"task_id":"xxx","query":"什么是LoRA","response":"LoRA是...","rating":5,"comment":"非常好"}'

# 手动触发训练
curl -X POST http://localhost:8008/api/v1/evolution/train \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5","min_dataset_size":100}'
```

### 2.4 / 2.5 — 同前述模式

---

## SP#11: frontend-dashboard — Next.js 统一仪表盘

### 2.1 项目初始化指令

```bash
mkdir -p services/frontend-dashboard
cd services/frontend-dashboard

# 创建 Next.js 项目
npx create-next-app@latest . \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir \
  --import-alias "@/*" \
  --use-npm

# 安装 Shadcn UI
npx shadcn@latest init -d

# 安装核心依赖
npm install @tanstack/react-query zustand axios lucide-react \
  react-markdown remark-gfm date-fns zod react-hook-form \
  @hookform/resolvers

# 安装常用 Shadcn 组件
npx shadcn@latest add button card dialog input label \
  select tabs toast sidebar avatar badge dropdown-menu \
  table textarea tooltip progress sheet separator

# 创建 .env.local
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_BASE_URL=http://localhost/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost/ws
EOF
```

### 2.2 核心文件清单

```
services/frontend-dashboard/
├── README.md
├── Dockerfile
├── next.config.ts
├── tailwind.config.ts
├── .env.example
├── src/
│   ├── app/
│   │   ├── layout.tsx                 # 根布局
│   │   ├── page.tsx                   # Dashboard 首页
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx         # 登录页
│   │   │   └── register/page.tsx      # 注册页
│   │   ├── (dashboard)/
│   │   │   ├── layout.tsx             # Dashboard 布局（Sidebar）
│   │   │   ├── chat/page.tsx          # AI 对话页
│   │   │   ├── content/page.tsx       # 内容工厂页
│   │   │   ├── intelligence/page.tsx  # 全域情报页
│   │   │   ├── ops/page.tsx           # 运营中台页
│   │   │   ├── brain/page.tsx         # 第二大脑页
│   │   │   ├── evolution/page.tsx     # 进化引擎页
│   │   │   └── settings/page.tsx      # 设置页
│   │   └── globals.css
│   ├── components/
│   │   ├── ui/                        # Shadcn UI 组件
│   │   ├── layout/
│   │   │   ├── app-sidebar.tsx        # 侧边栏
│   │   │   ├── top-bar.tsx            # 顶栏
│   │   │   └── breadcrumb.tsx
│   │   ├── chat/
│   │   │   ├── chat-interface.tsx     # 对话界面
│   │   │   ├── message-bubble.tsx     # 消息气泡
│   │   │   └── streaming-text.tsx     # 流式文本渲染
│   │   ├── dashboard/
│   │   │   ├── stats-card.tsx         # 统计卡片
│   │   │   └── system-status.tsx      # 系统状态
│   │   └── shared/
│   │       ├── file-upload.tsx        # 文件上传组件
│   │       └── data-table.tsx         # 数据表格
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts             # Axios 实例 + 拦截器
│   │   │   ├── auth.ts               # 认证 API
│   │   │   ├── ai.ts                 # AI 对话 API
│   │   │   ├── content.ts            # 内容工厂 API
│   │   │   ├── intel.ts              # 情报 API
│   │   │   ├── ops.ts                # 运营 API
│   │   │   ├── brain.ts              # 大脑 API
│   │   │   └── evolution.ts          # 进化 API
│   │   └── utils.ts                  # 工具函数
│   ├── hooks/
│   │   ├── use-auth.ts               # 认证 Hook
│   │   ├── use-sse.ts                # SSE 流式连接 Hook
│   │   └── use-toast.ts
│   ├── store/
│   │   ├── auth-store.ts             # Zustand 认证状态
│   │   └── chat-store.ts             # 对话状态
│   └── types/
│       └── index.ts                   # TypeScript 类型定义
└── public/
    └── logo.svg
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/6: [项目骨架 + 布局 + Sidebar]**

```
角色：你是一名前端工程师，精通 Next.js 14 App Router + Shadcn UI。

上下文：为 Omni-Vibe OS 创建统一仪表盘前端。

请生成：

1. `src/app/layout.tsx`：
   - 根布局，设置字体、主题
   - TanStack Query Provider
   - Toast Provider

2. `src/app/(dashboard)/layout.tsx`：
   - Dashboard 布局
   - 左侧 Sidebar + 顶栏 + 主内容区
   - 使用 Shadcn Sidebar 组件
   - 响应式：移动端 Sidebar 可收起

3. `src/components/layout/app-sidebar.tsx`：
   - 导航菜单：
     - 🏠 Dashboard
     - 💬 AI 对话
     - 🎨 内容工厂
     - 📊 全域情报
     - 🤖 运营中台
     - 🧠 第二大脑
     - 🔄 进化引擎
     - ⚙️ 设置
   - 底部：用户信息 + 登出

4. `src/components/layout/top-bar.tsx`：
   - 面包屑导航
   - 搜索框
   - 通知图标
   - 用户头像菜单

技术约束：
- Next.js 14 App Router
- Shadcn UI 组件
- Tailwind CSS
- TypeScript strict 模式
- 暗色主题

输出：完整文件内容。
```

---

**Prompt 2/6: [认证系统 (登录/注册 + JWT 管理)]**

```
角色：你是一名前端工程师。

请生成：

1. `src/lib/api/client.ts`：
   - Axios 实例
   - 请求拦截器：自动添加 Bearer Token
   - 响应拦截器：401 自动刷新 Token，失败跳转登录页
   - 统一错误处理

2. `src/lib/api/auth.ts`：
   - register(email, password, displayName)
   - login(email, password) -> TokenResponse
   - refreshToken(refreshToken) -> TokenResponse
   - getMe() -> User

3. `src/store/auth-store.ts`：
   - Zustand store
   - 状态：user, accessToken, refreshToken, isAuthenticated
   - 动作：login, logout, refreshAuth
   - 持久化到 localStorage

4. `src/hooks/use-auth.ts`：
   - useAuth() -> { user, login, logout, isLoading }
   - 自动检查 Token 有效性

5. `src/app/(auth)/login/page.tsx`：
   - 登录表单（email + password）
   - 使用 react-hook-form + zod 校验
   - 登录成功跳转 dashboard

6. `src/app/(auth)/register/page.tsx`：
   - 注册表单

7. `src/middleware.ts`：
   - Next.js 中间件
   - 未认证用户重定向到 /login

输出：完整文件内容。
```

---

**Prompt 3/6: [Dashboard 首页 + 系统状态]**

```
请生成 Dashboard 首页：

1. `src/app/(dashboard)/page.tsx`：
   - 统计卡片行：总任务数、今日生成内容、爬取商品数、待处理文件
   - 系统状态区：各子系统健康状态
   - 最近活动列表
   - 快捷操作按钮

2. `src/components/dashboard/stats-card.tsx`：
   - 可复用统计卡片（图标 + 数值 + 趋势百分比）
   - 使用 Lucide React 图标

3. `src/components/dashboard/system-status.tsx`：
   - 各后端服务状态指示灯
   - 每 30 秒自动刷新
   - 状态：健康(绿) / 降级(黄) / 离线(红)

输出：完整文件内容。
```

---

**Prompt 4/6: [AI 对话页面 (SSE 流式)]**

```
角色：你是一名精通实时通信的前端工程师。

请生成 AI 对话界面：

1. `src/hooks/use-sse.ts`：
   - useSSE(url, body) Hook
   - 使用 fetch + ReadableStream 解析 SSE
   - 返回：{ data, isStreaming, error }

2. `src/store/chat-store.ts`：
   - Zustand store
   - 消息列表、当前对话 ID、Provider 选择
   - addMessage, updateStreamingMessage, clearMessages

3. `src/app/(dashboard)/chat/page.tsx`：
   - 消息列表区（滚动，自动到底部）
   - 输入区（文本框 + 发送按钮 + Provider 选择下拉）
   - 流式输出动画
   - Markdown 渲染（含代码高亮）

4. `src/components/chat/chat-interface.tsx`：主对话组件
5. `src/components/chat/message-bubble.tsx`：消息气泡
6. `src/components/chat/streaming-text.tsx`：流式文本 + 打字动画

技术约束：
- SSE 解析使用原生 fetch（不用 EventSource，以支持 POST）
- Markdown 使用 react-markdown + remark-gfm
- 代码块支持复制按钮
- 消息支持重新生成

输出：完整文件内容。
```

---

**Prompt 5/6: [业务模块页面骨架]**

```
请为以下页面生成骨架代码（数据表格 + 操作按钮 + 模态框）：

1. `src/app/(dashboard)/content/page.tsx`：内容工厂
   - 图片/视频生成表单
   - 任务列表 + 状态指示 + 进度条
   - 结果预览画廊

2. `src/app/(dashboard)/intelligence/page.tsx`：全域情报
   - 爬取任务提交
   - 商品列表 + 价格趋势图
   - 评论分析面板

3. `src/app/(dashboard)/ops/page.tsx`：运营中台
   - 自动回复开关 + 模板管理
   - 定价规则配置
   - 操作日志时间线

4. `src/app/(dashboard)/brain/page.tsx`：第二大脑
   - 文件上传区（拖拽上传）
   - 已处理文件列表
   - 知识库搜索

5. `src/app/(dashboard)/evolution/page.tsx`：进化引擎
   - 反馈统计图表
   - 训练任务列表 + 指标
   - LoRA 适配器管理
   - A/B 测试面板

每个页面使用 Shadcn 的 Tabs 组件组织功能区。

输出：完整文件内容。
```

---

**Prompt 6/6: [API 层 + Dockerfile + README]**

```
请生成：

1. `src/lib/api/` 下所有 API 模块（content.ts, intel.ts, ops.ts, brain.ts, evolution.ts）
2. `src/types/index.ts`：所有 TypeScript 类型定义
3. `Dockerfile`：多阶段构建 Next.js 应用
4. `README.md`：项目说明 + 开发指南

输出：完整文件内容。
```

**验证方式**：
```bash
cd services/frontend-dashboard
npm run dev
# 浏览器打开 http://localhost:3000
```

### 2.4 集成测试方案

**与后端联调：**
- API 基础地址通过 `NEXT_PUBLIC_API_BASE_URL` 配置
- 开发环境通过 Nginx 代理避免 CORS 问题
- SSE 流式连接需要 Nginx 配置 `proxy_buffering off`

### 2.5 Git 操作指令

```bash
git checkout -b feat/sp11-frontend-dashboard
git add services/frontend-dashboard/
git commit -m "feat(frontend): add Next.js 14 dashboard with Shadcn UI

- App Router with sidebar layout
- JWT auth (login/register/auto-refresh)
- AI chat with SSE streaming
- Content factory / Intel / Ops / Brain / Evolution pages
- Dark theme with Tailwind CSS"

git push origin feat/sp11-frontend-dashboard
```
