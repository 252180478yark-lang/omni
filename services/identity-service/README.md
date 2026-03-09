# SP2 identity-service (backend-gateway blueprint)

Identity service based on FastAPI + SQLAlchemy Async + PostgreSQL.

基于 FastAPI + SQLAlchemy Async + PostgreSQL 的身份认证服务，提供注册、登录、刷新令牌、当前用户与 JWT 验证能力。

## Features / 功能

- Async database stack (`sqlalchemy[asyncio]` + `asyncpg`)
- JWT auth (access + refresh token)
- Layered auth dependencies (`get_current_user`, `require_admin`)
- Unified response/error model
- Structured request logging via `structlog`
- Alembic async migration support
- Celery task skeleton with Redis broker/backend

## Project Layout / 目录结构

```text
services/identity-service/
├── app/
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py
│   ├── exceptions.py
│   ├── main.py
│   ├── middleware/
│   ├── models/
│   ├── routers/
│   ├── schemas/
│   ├── services/
│   └── utils/
├── alembic/
├── celery_app/
├── tests/
├── Dockerfile
├── alembic.ini
└── pyproject.toml
```

## Quick Start / 快速启动

### Local Dev / 本地开发

```bash
cd services/identity-service
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

### Database Migration / 数据迁移

```bash
alembic upgrade head
```

### Run Celery Worker / 启动 Celery Worker

```bash
celery -A celery_app.celery_app worker --loglevel=info -Q default
```

## API Endpoints / 接口列表

- `GET /health`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/verify`

All success responses use:

```json
{"code":200,"message":"success","data":{}}
```

## Environment Variables / 环境变量

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `dev` | Runtime environment |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async DB connection URL |
| `REDIS_URL` | `redis://:changeme_redis@localhost:6379/0` | Celery broker/result backend |
| `JWT_SECRET_KEY` | `change_me` | JWT secret |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token expiration |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token expiration |
| `SERVICE_NAME` | `identity-service` | Service name |
| `SERVICE_PORT` | `8000` | Service port |
| `LOG_LEVEL` | `INFO` | Log level |
| `CORS_ORIGINS` | `*` | CORS origins, comma separated |

## Testing / 测试

```bash
python -m pytest tests -v
```

Covered cases:

- register success
- register duplicate email
- login success
- login wrong password
- get current user with token
- get current user without token

## Docker / 部署

```bash
docker build -t omni-identity-service .
docker run --rm -p 8000:8000 --env-file .env omni-identity-service
```
