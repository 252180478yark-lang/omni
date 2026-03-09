# Part 2: 逐个子项目构建指南

---

## 0. Debug 调试优先（当前仓库版本）

> 先说明：本文件后续章节包含的是「目标蓝图指引」，与当前仓库的最小可运行实现存在差异。  
> **当前仓库实际服务名**：`identity-service`、`ai-provider-hub`、`knowledge-engine`（不是 `backend-gateway`）。

### 0.1 一键排错顺序（PowerShell）

```powershell
# 1) 在仓库根目录
cd E:\agent\omni

# 2) 先创建外部网络（未创建会导致 compose 启动失败）
docker network inspect omni-network > $null 2>&1
if ($LASTEXITCODE -ne 0) { docker network create omni-network }

# 3) 启动基础设施
docker compose -f services/infra-core/docker-compose.infra.yml up -d

# 4) 启动 SP1-SP4 服务组
docker compose -f services/docker-compose.sp1-sp4.yml up -d --build

# 5) 查看服务状态
docker compose -f services/docker-compose.sp1-sp4.yml ps
```

### 0.2 健康检查与最小联调

```powershell
# 服务健康检查
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# 身份服务：注册 + 登录
curl -Method POST http://localhost:8000/api/v1/auth/register `
  -ContentType "application/json" `
  -Body '{"email":"test@example.com","password":"Test1234!","display_name":"Test User"}'

curl -Method POST http://localhost:8000/api/v1/auth/login `
  -ContentType "application/json" `
  -Body '{"email":"test@example.com","password":"Test1234!"}'

# AI Provider Hub（OpenAI 兼容路由）
curl -Method POST http://localhost:8001/v1/chat/completions `
  -ContentType "application/json" `
  -Body '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}'

# Knowledge：建库 -> 入库 -> 查询
curl -Method POST http://localhost:8002/api/v1/knowledge/bases `
  -ContentType "application/json" `
  -Body '{"name":"test-kb","description":"debug kb"}'
```

### 0.3 常见报错对照表

- `network omni-network declared as external, but could not be found`  
  先执行：`docker network create omni-network`
- `Cannot connect to the Docker daemon`  
  启动 Docker Desktop 后重试
- `Port ... is already allocated`  
  释放占用端口或改 `.env.example`/compose 端口映射
- `404 on /api/v1/ai/*`  
  当前 `ai-provider-hub` 使用 OpenAI 兼容前缀：`/v1/*`，不是 `/api/v1/ai/*`
- 按蓝图调用 `backend-gateway` 失败  
  当前仓库对应服务是 `identity-service`（端口 `8000`）

---

## SP#1: infra-core — 基础设施层

### 2.1 项目初始化指令

```bash
# 在项目根目录下创建
mkdir -p services/infra-core/{postgres,redis,nginx}
cd services/infra-core

# 创建环境变量模板
cat > .env.example << 'EOF'
# === Database / 数据库 ===
POSTGRES_USER=omni_user
POSTGRES_PASSWORD=changeme_in_production
POSTGRES_DB=omni_vibe_db
POSTGRES_PORT=5432

# === Redis ===
REDIS_PASSWORD=changeme_redis
REDIS_PORT=6379

# === Nginx ===
NGINX_PORT=80
NGINX_SSL_PORT=443
EOF

cp .env.example .env
```

### 2.2 核心文件清单

```
services/infra-core/
├── README.md                          # 快速启动说明
├── docker-compose.infra.yml           # 基础设施编排
├── .env.example                       # 环境变量模板
├── .env                               # 实际环境变量（gitignore）
├── postgres/
│   ├── Dockerfile                     # PostgreSQL + pgvector 镜像
│   ├── init.sql                       # 初始化脚本（创建扩展、schema）
│   └── pg_hba.conf                    # 访问控制（可选）
├── redis/
│   └── redis.conf                     # Redis 配置（密码、持久化）
├── nginx/
│   ├── nginx.conf                     # 主配置
│   └── conf.d/
│       └── default.conf               # 反向代理路由
└── scripts/
    ├── healthcheck.sh                 # 健康检查脚本
    └── wait-for-it.sh                 # 服务启动等待脚本
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/3: [基础设施 Docker Compose + PostgreSQL 初始化]**

```
角色：你是一名 DevOps 工程师，精通 Docker Compose 和 PostgreSQL。

上下文：我正在构建一个名为 Omni-Vibe OS 的系统，需要先搭建基础设施层。

请生成以下文件：

1. `docker-compose.infra.yml`，包含：
   - PostgreSQL 15 服务，基于自定义 Dockerfile（安装 pgvector 扩展）
   - Redis 7 服务，带密码认证和持久化
   - 所有服务使用 `omni-network` bridge 网络
   - 健康检查配置（postgres 用 pg_isready，redis 用 redis-cli ping）
   - Volume 持久化（postgres_data, redis_data）
   - 从 .env 文件读取所有敏感配置

2. `postgres/Dockerfile`：基于 postgres:15，安装 pgvector 扩展

3. `postgres/init.sql`：
   - CREATE EXTENSION IF NOT EXISTS vector;
   - CREATE SCHEMA IF NOT EXISTS market_intel;
   - CREATE SCHEMA IF NOT EXISTS content;
   - CREATE SCHEMA IF NOT EXISTS ops;
   - CREATE SCHEMA IF NOT EXISTS brain;
   - CREATE SCHEMA IF NOT EXISTS evolution;
   - 每个 schema 添加注释说明用途

4. `redis/redis.conf`：
   - 密码认证（requirepass 从环境变量）
   - AOF 持久化
   - maxmemory 512mb + allkeys-lru

技术约束：
- Docker Compose 版本用 v2 语法（不要 version 字段）
- 网络名称统一为 omni-network
- 所有端口映射可通过 .env 自定义
- 中英双语注释

输出：直接输出每个文件的完整内容，用文件路径作为标题。
```

**验证方式**：
```bash
docker compose -f docker-compose.infra.yml up -d
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT * FROM pg_extension WHERE extname='vector';"
docker exec omni-redis redis-cli -a changeme_redis ping
```

---

**Prompt 2/3: [Nginx 反向代理配置]**

```
角色：你是一名 DevOps 工程师，精通 Nginx 配置。

上下文：Omni-Vibe OS 有以下后端服务，都运行在 Docker 网络 omni-network 中：
- backend-gateway: 端口 8000
- ai-provider-hub: 端口 8001
- knowledge-engine: 端口 8002
- langgraph-orchestrator: 端口 8003
- content-factory: 端口 8004
- market-intelligence: 端口 8005
- ops-assistant: 端口 8006
- second-brain: 端口 8007
- evolution-engine: 端口 8008
- frontend: 端口 3000

请生成：

1. `nginx/nginx.conf`：主配置，worker 进程、日志格式

2. `nginx/conf.d/default.conf`：
   - 前端路由：/ → frontend:3000
   - API 路由：/api/v1/auth/* → backend-gateway:8000
   - API 路由：/api/v1/ai/* → ai-provider-hub:8001
   - API 路由：/api/v1/knowledge/* → knowledge-engine:8002
   - API 路由：/api/v1/orchestrate/* → langgraph-orchestrator:8003
   - API 路由：/api/v1/content/* → content-factory:8004
   - API 路由：/api/v1/intel/* → market-intelligence:8005
   - API 路由：/api/v1/ops/* → ops-assistant:8006
   - API 路由：/api/v1/brain/* → second-brain:8007
   - API 路由：/api/v1/evolution/* → evolution-engine:8008
   - WebSocket 支持（SSE 流式输出）
   - CORS 头配置
   - 健康检查端点 /health

技术约束：
- 使用 upstream 块定义后端
- 支持 SSE（proxy_buffering off）
- 请求体大小限制 100MB（支持文件上传）
- 超时配置：proxy_read_timeout 300s

输出：完整的 nginx.conf 和 default.conf 文件内容。
```

**验证方式**：
```bash
docker compose -f docker-compose.infra.yml up nginx -d
curl http://localhost/health
```

---

**Prompt 3/3: [健康检查和工具脚本]**

```
角色：你是一名 DevOps 工程师。

请生成以下工具脚本：

1. `scripts/healthcheck.sh`（Bash）：
   - 检查 PostgreSQL 连接
   - 检查 Redis 连接
   - 检查 pgvector 扩展是否安装
   - 检查各 schema 是否存在
   - 输出彩色状态报告
   - 从 .env 文件读取配置

2. `scripts/wait-for-it.sh`：
   - 经典的 wait-for-it 脚本
   - 支持 --timeout 参数
   - 用于 Docker 启动顺序控制

3. `README.md`：
   - 项目说明（中英双语）
   - 前置依赖（Docker 24+, Docker Compose v2）
   - 快速启动命令
   - 环境变量说明表格
   - 常见问题排查

输出：完整的文件内容。
```

**验证方式**：
```bash
chmod +x scripts/*.sh
./scripts/healthcheck.sh
```

### 2.4 集成测试方案

**与其他子项目的联调：**
- 所有后端服务通过 Docker 网络 `omni-network` 连接 PostgreSQL 和 Redis
- 连接字符串格式：`postgresql://omni_user:password@postgres:5432/omni_vibe_db`
- Redis 连接：`redis://:password@redis:6379/0`

**关键验证命令：**
```bash
# 验证 PostgreSQL + pgvector
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "CREATE TABLE test_vec (id serial, embedding vector(384)); DROP TABLE test_vec;"

# 验证 Redis
docker exec omni-redis redis-cli -a changeme_redis SET test_key "hello" && \
docker exec omni-redis redis-cli -a changeme_redis GET test_key

# 验证网络连通性
docker exec omni-nginx curl -s http://backend-gateway:8000/health || echo "Gateway not started yet (expected)"
```

### 2.5 Git 操作指令

```bash
cd /path/to/omni-vibe-os
git checkout -b feat/sp1-infra-core

# 添加文件
git add services/infra-core/
git commit -m "feat(infra): add PostgreSQL + pgvector + Redis + Nginx infrastructure

- PostgreSQL 15 with pgvector extension
- Redis 7 with AOF persistence and auth
- Nginx reverse proxy for all services
- Health check scripts
- Schema isolation per business module"

git push origin feat/sp1-infra-core
# 创建 PR 合并到 main
```

---

## SP#2: backend-gateway — FastAPI 统一网关

### 2.1 项目初始化指令

```bash
mkdir -p services/backend-gateway
cd services/backend-gateway

# Python 项目初始化
python3.11 -m venv .venv
source .venv/bin/activate

# 创建 pyproject.toml
cat > pyproject.toml << 'EOF'
[project]
name = "backend-gateway"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "celery[redis]>=5.4.0",
    "redis>=5.0.0",
    "python-multipart>=0.0.9",
    "structlog>=24.1.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "ruff>=0.5.0",
]
EOF

pip install -e ".[dev]"

# Alembic 初始化
alembic init alembic

# 创建 .env
cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
REDIS_URL=redis://:changeme_redis@localhost:6379/0
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
SERVICE_NAME=backend-gateway
SERVICE_PORT=8000
LOG_LEVEL=INFO
EOF
```

### 2.2 核心文件清单

```
services/backend-gateway/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── alembic/
│   ├── alembic.ini
│   ├── env.py                         # 异步迁移配置
│   └── versions/                      # 迁移脚本
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI 应用入口
│   ├── config.py                      # Pydantic Settings 配置
│   ├── database.py                    # 异步数据库引擎 + Session
│   ├── dependencies.py                # 通用依赖注入
│   ├── exceptions.py                  # 统一异常处理
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── logging.py                 # 请求/响应日志
│   │   └── cors.py                    # CORS 配置
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                    # SQLAlchemy Base + 通用 Mixin
│   │   └── user.py                    # User 模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                  # 通用响应 Schema
│   │   └── auth.py                    # 认证 Schema
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py                  # 健康检查路由
│   │   └── auth.py                    # 认证路由
│   ├── services/
│   │   ├── __init__.py
│   │   └── auth_service.py            # 认证业务逻辑
│   └── utils/
│       ├── __init__.py
│       └── security.py                # JWT + 密码 Hash 工具
├── celery_app/
│   ├── __init__.py
│   ├── celery_config.py               # Celery 配置
│   └── tasks/
│       └── __init__.py
└── tests/
    ├── conftest.py
    └── test_auth.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/5: [FastAPI 应用骨架 + 配置 + 数据库]**

```
角色：你是一名精通 FastAPI 和 SQLAlchemy 的 Python 后端工程师。

上下文：我正在构建 Omni-Vibe OS 的后端网关服务 (backend-gateway)。这是所有业务模块的入口。

请生成以下文件（production-ready，含类型注解、错误处理、structlog 日志）：

1. `app/config.py`：
   - 使用 pydantic-settings v2 的 BaseSettings
   - 从 .env 读取 DATABASE_URL, REDIS_URL, JWT_SECRET_KEY 等
   - 支持 test / dev / prod 环境切换
   - 所有配置项有类型注解和默认值

2. `app/database.py`：
   - create_async_engine（使用 asyncpg）
   - async_sessionmaker
   - get_db_session 异步生成器（用于依赖注入）
   - 连接池配置：pool_size=20, max_overflow=10

3. `app/models/base.py`：
   - SQLAlchemy DeclarativeBase
   - TimestampMixin（created_at, updated_at 自动管理）
   - UUIDMixin（id 字段使用 UUID）

4. `app/main.py`：
   - FastAPI 应用实例
   - lifespan 事件（启动时创建表、关闭时释放连接池）
   - 注册所有 router
   - 全局异常处理器
   - CORS 中间件

5. `app/exceptions.py`：
   - 自定义 AppException(code, message, detail)
   - 统一错误响应处理器
   - 输出格式 {"code": int, "message": str, "detail": str}

6. `app/schemas/common.py`：
   - ResponseModel[T]（通用成功响应）
   - ErrorResponse（错误响应）
   - PaginationParams（分页参数）

技术约束：
- Python 3.11+，所有函数都有类型注解
- 使用 structlog 进行结构化日志
- 异步优先（async/await）
- 中英双语注释（关键逻辑中文 + 英文 docstring）
- 不要使用已废弃的 API（如 SQLAlchemy 1.x 风格）

输出：每个文件的完整内容，以文件路径为标题。
```

**验证方式**：
```bash
cd services/backend-gateway
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
# 应返回 {"status": "healthy", "service": "backend-gateway"}
```

---

**Prompt 2/5: [JWT 认证系统]**

```
角色：你是一名安全工程师，精通 JWT 和 FastAPI 认证。

上下文：基于已有的 FastAPI 骨架（app/config.py, app/database.py, app/main.py），
需要添加完整的 JWT 认证系统。

请生成以下文件：

1. `app/models/user.py`：
   - User SQLAlchemy 模型
   - 字段：id(UUID), email(unique), hashed_password, display_name, is_active, role(enum: admin/user)
   - 继承 UUIDMixin, TimestampMixin

2. `app/utils/security.py`：
   - hash_password(password: str) -> str （使用 bcrypt）
   - verify_password(plain: str, hashed: str) -> bool
   - create_access_token(data: dict, expires_delta: timedelta) -> str
   - create_refresh_token(data: dict) -> str
   - decode_token(token: str) -> dict

3. `app/schemas/auth.py`：
   - RegisterRequest(email, password, display_name)
   - LoginRequest(email, password)
   - TokenResponse(access_token, refresh_token, token_type)
   - UserResponse(id, email, display_name, role, created_at)

4. `app/services/auth_service.py`：
   - register(db, data) -> User
   - authenticate(db, email, password) -> User
   - refresh_tokens(db, refresh_token) -> TokenResponse

5. `app/routers/auth.py`：
   - POST /api/v1/auth/register
   - POST /api/v1/auth/login
   - POST /api/v1/auth/refresh
   - GET /api/v1/auth/me （需要 Bearer Token）

6. `app/dependencies.py`：
   - get_current_user 依赖（解析 JWT Token）
   - require_admin 依赖（检查 admin 角色）

技术约束：
- 密码至少 8 位
- Access Token 过期 30 分钟，Refresh Token 过期 7 天
- 所有密码错误返回 401，不透露具体原因（安全最佳实践）
- 使用 python-jose 处理 JWT
- 中英双语注释

输出：每个文件的完整内容。
```

**验证方式**：
```bash
# 注册
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test1234!","display_name":"Test User"}'

# 登录
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test1234!"}'

# 获取当前用户
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

---

**Prompt 3/5: [Alembic 迁移 + 请求日志中间件]**

```
角色：你是一名 Python 后端工程师。

请生成：

1. `alembic/env.py`：
   - 异步迁移配置（使用 asyncpg）
   - 自动从 app.models 导入所有模型
   - 从 app.config 读取 DATABASE_URL

2. `app/middleware/logging.py`：
   - 请求/响应日志中间件
   - 记录：method, path, status_code, duration_ms, client_ip
   - 使用 structlog
   - 排除 /health 端点的日志

3. `Dockerfile`：
   - 基于 python:3.11-slim
   - 多阶段构建
   - 非 root 用户运行
   - 暴露端口 8000
   - 入口命令：uvicorn app.main:app --host 0.0.0.0 --port 8000

技术约束：
- Alembic 必须支持 async（使用 run_async）
- Dockerfile 使用 pip install -e . 安装项目

输出：完整文件内容。
```

**验证方式**：
```bash
# 生成迁移
alembic revision --autogenerate -m "initial_user_table"
# 执行迁移
alembic upgrade head
# 构建 Docker 镜像
docker build -t omni-backend-gateway .
```

---

**Prompt 4/5: [Celery 异步任务框架]**

```
角色：你是一名分布式系统工程师。

请生成 Celery 异步任务框架：

1. `celery_app/celery_config.py`：
   - Celery 实例配置
   - Redis 作为 Broker 和 Result Backend
   - 任务序列化使用 JSON
   - 任务路由配置（不同队列处理不同类型任务）
   - 队列定义：default, content, crawl, training

2. `celery_app/__init__.py`：
   - 创建 Celery 应用实例
   - 自动发现任务

3. `celery_app/tasks/__init__.py`：
   - 示例任务：health_check_task
   - 基础任务类 BaseTask（含错误处理和重试逻辑）

技术约束：
- Celery 5.4+
- 任务超时默认 300 秒
- 最大重试 3 次，指数退避

输出：完整文件内容。
```

**验证方式**：
```bash
# 启动 Worker
celery -A celery_app worker --loglevel=info -Q default

# 另一终端测试
python -c "from celery_app.tasks import health_check_task; print(health_check_task.delay().get(timeout=10))"
```

---

**Prompt 5/5: [单元测试 + README]**

```
角色：你是一名 QA 工程师。

请生成：

1. `tests/conftest.py`：
   - 异步 pytest 配置
   - 测试数据库（使用 SQLite 内存数据库或 test schema）
   - AsyncClient fixture
   - 创建测试用户 fixture

2. `tests/test_auth.py`：
   - test_register_success
   - test_register_duplicate_email
   - test_login_success
   - test_login_wrong_password
   - test_get_me_authenticated
   - test_get_me_unauthenticated

3. `README.md`：
   - 项目说明（中英双语）
   - 快速启动（开发环境 + Docker）
   - API 端点列表
   - 环境变量说明
   - 测试命令

输出：完整文件内容。
```

**验证方式**：
```bash
pytest tests/ -v
```

### 2.4 集成测试方案

**与其他子项目联调：**
- 所有子项目通过 `http://backend-gateway:8000` 验证 JWT Token
- 共享 User 模型，其他服务通过 `/api/v1/auth/me` 验证身份
- 数据库共用 PostgreSQL，通过不同 schema 隔离

**关键 API 端点：**
```
POST /api/v1/auth/register  → 注册用户
POST /api/v1/auth/login     → 登录获取 Token
POST /api/v1/auth/refresh   → 刷新 Token
GET  /api/v1/auth/me        → 获取当前用户信息
GET  /health                → 健康检查
```

**数据格式约定：**
```json
// 成功响应
{"code": 200, "message": "success", "data": {...}}

// 错误响应
{"code": 401, "message": "Unauthorized", "detail": "Invalid or expired token"}

// Token 响应
{"access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer"}
```

### 2.5 Git 操作指令

```bash
git checkout -b feat/sp2-backend-gateway
git add services/backend-gateway/
git commit -m "feat(gateway): add FastAPI backend gateway with JWT auth

- FastAPI application with async SQLAlchemy 2.0
- JWT authentication (register/login/refresh/me)
- Alembic async migrations
- Celery task framework with Redis broker
- Structured logging with structlog
- Unified error handling"

git push origin feat/sp2-backend-gateway
```

---

## SP#3: ai-provider-hub — 多模型 Provider 统一抽象层

### 2.1 项目初始化指令

```bash
mkdir -p services/ai-provider-hub
cd services/ai-provider-hub

cat > pyproject.toml << 'EOF'
[project]
name = "ai-provider-hub"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "google-genai>=1.0.0",
    "openai>=1.50.0",
    "httpx>=0.27.0",
    "sse-starlette>=2.0.0",
    "structlog>=24.1.0",
    "tiktoken>=0.7.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_CHAT_PROVIDER=gemini
DEFAULT_EMBEDDING_PROVIDER=openai
SERVICE_NAME=ai-provider-hub
SERVICE_PORT=8001
EOF

python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 2.2 核心文件清单

```
services/ai-provider-hub/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI 入口
│   ├── config.py                      # 配置（各 Provider 的 API Key）
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                    # BaseProvider 抽象类
│   │   ├── gemini_provider.py         # Google Gemini
│   │   ├── openai_provider.py         # OpenAI
│   │   ├── ollama_provider.py         # Ollama 本地
│   │   └── registry.py               # Provider 注册表 + 工厂
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── ai.py                      # ChatRequest, ChatResponse, EmbeddingRequest 等
│   ├── routers/
│   │   ├── __init__.py
│   │   └── ai.py                      # /api/v1/ai/* 路由
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat_service.py            # 聊天服务（含流式）
│   │   ├── embedding_service.py       # Embedding 服务
│   │   └── usage_tracker.py           # Token 用量追踪
│   └── utils/
│       ├── __init__.py
│       └── fallback.py                # 自动 Fallback 逻辑
└── tests/
    └── test_providers.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/4: [Provider 抽象层 + 注册表]**

```
角色：你是一名精通设计模式的 Python 架构师。

上下文：Omni-Vibe OS 需要一个统一的 AI Provider 抽象层，支持 Gemini、OpenAI、Ollama 三种后端的无缝切换。使用策略模式（Strategy Pattern）+ 工厂模式。

请生成：

1. `app/providers/base.py`：
   - ABC 抽象类 BaseProvider
   - 抽象方法：
     - async chat(messages: list[Message], model: str, **kwargs) -> ChatResponse
     - async chat_stream(messages: list[Message], model: str, **kwargs) -> AsyncIterator[str]
     - async embedding(texts: list[str], model: str) -> list[list[float]]
   - ProviderCapability 枚举：CHAT, EMBEDDING, VISION, FUNCTION_CALLING
   - 每个 Provider 声明自己支持的 capabilities

2. `app/providers/registry.py`：
   - ProviderRegistry 单例类
   - register(name: str, provider: BaseProvider)
   - get(name: str) -> BaseProvider
   - get_default(task: str) -> BaseProvider（根据任务类型返回默认 Provider）
   - list_providers() -> dict（列出所有已注册的 Provider 及其能力）

3. `app/schemas/ai.py`：
   - Message(role: str, content: str | list)
   - ChatRequest(messages, provider, model, temperature, max_tokens, stream)
   - ChatResponse(content, provider, model, usage: TokenUsage)
   - TokenUsage(prompt_tokens, completion_tokens, total_tokens)
   - EmbeddingRequest(texts, provider, model)
   - EmbeddingResponse(embeddings: list[list[float]], usage)

技术约束：
- 所有方法 async
- Pydantic V2 模型
- 完整类型注解
- 中英双语注释

输出：完整文件内容。
```

**验证方式**：`python -c "from app.providers.base import BaseProvider; print('OK')"`

---

**Prompt 2/4: [三个 Provider 实现]**

```
角色：你是一名 AI 工程师，熟悉 Gemini, OpenAI, Ollama API。

基于 BaseProvider 抽象类，请实现三个 Provider：

1. `app/providers/gemini_provider.py`：
   - 使用 google-genai SDK（新版，不是旧版 google-generativeai）
   - 支持 chat（含 system prompt）
   - 支持 chat_stream（流式输出）
   - 支持 embedding（text-embedding-004）
   - 默认模型：gemini-2.0-flash

2. `app/providers/openai_provider.py`：
   - 使用 openai SDK >= 1.50
   - 支持 chat / chat_stream / embedding
   - 默认模型：gpt-4o-mini
   - Embedding 默认：text-embedding-3-small

3. `app/providers/ollama_provider.py`：
   - 使用 httpx 直接调用 Ollama REST API
   - POST /api/chat（流式和非流式）
   - POST /api/embed
   - 默认模型：qwen2.5:7b
   - 支持模型列表查询：GET /api/tags

每个 Provider 需要：
- 完整的错误处理（API 超时、Rate Limit、模型不存在）
- Token 用量统计（从 API 响应提取或估算）
- structlog 日志记录

技术约束：
- 不要使用已废弃的 API（如 google-generativeai 的旧接口）
- OpenAI SDK 使用 AsyncOpenAI
- 超时配置可外部传入

输出：三个完整的 Provider 文件。
```

**验证方式**：
```bash
# 需要先配置对应的 API Key
python -c "
import asyncio
from app.providers.openai_provider import OpenAIProvider
p = OpenAIProvider()
result = asyncio.run(p.chat([{'role':'user','content':'Hello'}], 'gpt-4o-mini'))
print(result)
"
```

---

**Prompt 3/4: [路由 + 服务 + Fallback + 流式输出]**

```
角色：你是一名 FastAPI 工程师。

请生成：

1. `app/services/chat_service.py`：
   - 调用 ProviderRegistry 获取 Provider
   - 非流式聊天 + 流式聊天
   - 自动 Fallback：如果主 Provider 失败，按优先级切换

2. `app/utils/fallback.py`：
   - FallbackChain 类
   - 配置 fallback 顺序：gemini → openai → ollama
   - 记录失败原因和切换日志

3. `app/routers/ai.py`：
   - POST /api/v1/ai/chat （非流式）
   - POST /api/v1/ai/chat/stream （SSE 流式）
   - POST /api/v1/ai/embedding
   - GET /api/v1/ai/providers （列出可用 Provider）
   - GET /api/v1/ai/models （列出可用模型）

4. `app/services/usage_tracker.py`：
   - 记录每次 API 调用的 Token 用量到 PostgreSQL
   - UsageRecord 模型：provider, model, prompt_tokens, completion_tokens, cost, timestamp

5. `app/main.py`（更新）：
   - 应用启动时注册所有 Provider
   - 包含健康检查
   - SSE 流式输出支持

技术约束：
- SSE 使用 sse-starlette
- 流式端点返回 text/event-stream
- 每个 SSE event 的 data 格式：{"content": "...", "done": false}
- 最后一个 event：{"content": "", "done": true, "usage": {...}}

输出：完整文件内容。
```

**验证方式**：
```bash
# 非流式
curl -X POST http://localhost:8001/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"provider":"openai"}'

# 流式
curl -N -X POST http://localhost:8001/api/v1/ai/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Tell me a joke"}],"provider":"gemini"}'

# Embedding
curl -X POST http://localhost:8001/api/v1/ai/embedding \
  -H "Content-Type: application/json" \
  -d '{"texts":["hello world"],"provider":"openai"}'
```

---

**Prompt 4/4: [Dockerfile + 测试 + README]**

```
角色：你是一名 DevOps 工程师。

请生成：

1. `Dockerfile`：多阶段构建，python:3.11-slim，非 root 用户
2. `tests/test_providers.py`：Mock 测试三个 Provider（不依赖真实 API）
3. `README.md`：包含架构图（Mermaid）、快速启动、API 文档、Provider 配置说明

输出：完整文件内容。
```

### 2.4 集成测试方案

**与其他子项目联调：**
- SP#4 (knowledge-engine) 调用 `/api/v1/ai/embedding` 生成向量
- SP#5 (langgraph-orchestrator) 调用 `/api/v1/ai/chat` 进行推理
- SP#6-10 各业务模块通过此 Hub 统一调用 AI 模型

**关键 API 端点：**
```
POST /api/v1/ai/chat              → 非流式聊天
POST /api/v1/ai/chat/stream       → SSE 流式聊天
POST /api/v1/ai/embedding         → 生成 Embedding
GET  /api/v1/ai/providers         → 列出可用 Provider
GET  /api/v1/ai/models            → 列出可用模型
```

### 2.5 Git 操作指令

```bash
git checkout -b feat/sp3-ai-provider-hub
git add services/ai-provider-hub/
git commit -m "feat(ai): add unified AI provider hub with Gemini/OpenAI/Ollama

- Strategy + Factory pattern for provider abstraction
- SSE streaming support
- Auto fallback chain
- Token usage tracking
- Embedding service"

git push origin feat/sp3-ai-provider-hub
```

---

## SP#4: knowledge-engine — 知识检索引擎

### 2.1 项目初始化指令

```bash
mkdir -p services/knowledge-engine
cd services/knowledge-engine

cat > pyproject.toml << 'EOF'
[project]
name = "knowledge-engine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.30.0",
    "pgvector>=0.3.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "langchain-core>=0.3.0",
    "langchain-text-splitters>=0.3.0",
    "networkx>=3.3",
    "httpx>=0.27.0",
    "structlog>=24.1.0",
]
EOF

cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db
AI_PROVIDER_HUB_URL=http://localhost:8001
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
CHUNK_SIZE=512
CHUNK_OVERLAP=50
SERVICE_NAME=knowledge-engine
SERVICE_PORT=8002
EOF

python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 2.2 核心文件清单

```
services/knowledge-engine/
├── README.md
├── Dockerfile
├── pyproject.toml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── document.py                # Document + Chunk 模型
│   │   ├── entity.py                  # Entity + Relation 模型（GraphRAG）
│   │   └── knowledge_base.py          # KnowledgeBase 模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── knowledge.py               # 入库/检索 Schema
│   ├── routers/
│   │   ├── __init__.py
│   │   └── knowledge.py               # /api/v1/knowledge/* 路由
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ingestion.py               # 文档入库管道
│   │   ├── chunking.py                # 文本分块策略
│   │   ├── embedding_client.py        # 调用 AI Provider Hub 获取 Embedding
│   │   ├── vector_search.py           # pgvector 向量检索
│   │   ├── graph_rag.py               # GraphRAG 实体/关系抽取 + 图谱查询
│   │   └── hybrid_search.py           # 混合检索（向量 + 关键词 + 图谱）
│   └── utils/
│       └── __init__.py
└── tests/
    └── test_knowledge.py
```

### 2.3 Vibe Coding Prompt 链

---

**Prompt 1/4: [数据模型 + pgvector 向量存储]**

```
角色：你是一名搜索引擎工程师，精通向量数据库和 PostgreSQL。

上下文：Omni-Vibe OS 的知识引擎需要存储文档、向量、实体和关系。使用 PostgreSQL + pgvector。

请生成：

1. `app/models/document.py`：
   - KnowledgeBase 模型（id, name, description, created_at）
   - Document 模型（id, kb_id, title, source_url, raw_text, metadata_json, created_at）
   - Chunk 模型（id, document_id, content, chunk_index, embedding: Vector(1536), metadata_json）
   - 使用 pgvector 的 Vector 类型
   - 建立 HNSW 索引（cosine 距离）

2. `app/models/entity.py`：
   - Entity 模型（id, kb_id, name, entity_type, description, embedding: Vector(1536)）
   - Relation 模型（id, source_entity_id, target_entity_id, relation_type, weight, metadata_json）
   - Community 模型（id, kb_id, name, level, summary, entity_ids: ARRAY）

3. `app/database.py`：异步引擎 + Session
4. `app/config.py`：配置类

技术约束：
- pgvector >= 0.3.0
- SQLAlchemy 2.0 Mapped 注解风格
- 向量维度 1536（OpenAI text-embedding-3-small）
- HNSW 索引参数：m=16, ef_construction=64

输出：完整文件内容。
```

---

**Prompt 2/4: [文档入库管道]**

```
角色：你是一名 NLP 工程师。

请生成文档入库管道：

1. `app/services/chunking.py`：
   - RecursiveCharacterTextSplitter 封装
   - 支持按 chunk_size 和 overlap 配置
   - 保留段落结构（不在句子中间切割）
   - 返回 list[ChunkData(content, chunk_index, metadata)]

2. `app/services/embedding_client.py`：
   - 通过 httpx 调用 AI Provider Hub 的 /api/v1/ai/embedding
   - 批量处理（每批最多 100 条）
   - 重试机制（3 次，指数退避）

3. `app/services/ingestion.py`：
   - IngestPipeline 类
   - ingest_text(kb_id, title, text, source_url) -> Document
   - 流程：分块 → 生成 Embedding → 存储到 pgvector
   - 同时进行实体/关系抽取（调用 graph_rag）
   - 事务性：要么全部成功，要么全部回滚

4. `app/services/graph_rag.py`：
   - 使用 AI Provider Hub 的 chat API 抽取实体和关系
   - extract_entities_and_relations(text) -> list[Entity], list[Relation]
   - 使用结构化提示词让 LLM 输出 JSON 格式
   - 构建 NetworkX 图 + 社区检测（Leiden 算法简化版）

技术约束：
- 所有外部调用使用 httpx AsyncClient
- 错误处理：Embedding 失败时记录并跳过该 chunk
- 日志记录每步耗时

输出：完整文件内容。
```

---

**Prompt 3/4: [检索服务 + API 路由]**

```
角色：你是一名搜索系统工程师。

请生成：

1. `app/services/vector_search.py`：
   - search_by_vector(query_embedding, kb_id, top_k=10) -> list[ChunkResult]
   - 使用 pgvector 的 cosine_distance 运算符
   - 支持过滤条件（metadata 过滤）

2. `app/services/hybrid_search.py`：
   - hybrid_search(query, kb_id, top_k=10) -> list[SearchResult]
   - 步骤：
     1. 向量检索（语义相似）
     2. 关键词检索（PostgreSQL full-text search）
     3. 图谱遍历（从命中实体出发找相关实体）
   - RRF（Reciprocal Rank Fusion）融合排序
   - 返回结果包含来源标记（vector / keyword / graph）

3. `app/routers/knowledge.py`：
   - POST /api/v1/knowledge/bases （创建知识库）
   - GET /api/v1/knowledge/bases （列出知识库）
   - POST /api/v1/knowledge/ingest （入库文档 - 接受 text 或 file upload）
   - POST /api/v1/knowledge/query （混合检索）
   - GET /api/v1/knowledge/documents/{id} （获取文档详情）
   - GET /api/v1/knowledge/graph/{kb_id} （获取知识图谱数据）

4. `app/schemas/knowledge.py`：
   - 所有请求/响应 Schema

5. `app/main.py`：FastAPI 入口

输出：完整文件内容。
```

**验证方式**：
```bash
# 创建知识库
curl -X POST http://localhost:8002/api/v1/knowledge/bases \
  -H "Content-Type: application/json" \
  -d '{"name":"test-kb","description":"Test knowledge base"}'

# 入库文档
curl -X POST http://localhost:8002/api/v1/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{"kb_id":"<kb_id>","title":"Test Doc","text":"Omni-Vibe OS is an e-commerce operating system..."}'

# 查询
curl -X POST http://localhost:8002/api/v1/knowledge/query \
  -H "Content-Type: application/json" \
  -d '{"kb_id":"<kb_id>","query":"What is Omni-Vibe OS?","top_k":5}'
```

---

**Prompt 4/4: [Dockerfile + 测试 + README]**

与 SP#3 类似，略。

### 2.4 集成测试方案

**关键 API 端点：**
```
POST /api/v1/knowledge/bases       → 创建知识库
POST /api/v1/knowledge/ingest      → 入库文档
POST /api/v1/knowledge/query       → 混合检索
GET  /api/v1/knowledge/graph/{id}  → 获取知识图谱
```

**依赖服务验证：**
```bash
# 确认 AI Provider Hub 可达
curl http://ai-provider-hub:8001/health

# 确认 pgvector 可用
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT '[1,2,3]'::vector;"
```

### 2.5 Git 操作指令

```bash
git checkout -b feat/sp4-knowledge-engine
git add services/knowledge-engine/
git commit -m "feat(knowledge): add GraphRAG + pgvector knowledge engine

- Document ingestion with chunking + embedding
- pgvector HNSW index for vector search
- Entity/relation extraction (GraphRAG style)
- Hybrid search (vector + keyword + graph)
- RRF fusion ranking"

git push origin feat/sp4-knowledge-engine
```
