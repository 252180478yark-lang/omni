# SP1 infra-core / 基础设施层

Infra bootstrap for Omni SP1-SP4, including PostgreSQL, Redis and Nginx reverse proxy.

用于 Omni SP1-SP4 的基础设施启动层，包含 PostgreSQL、Redis 与 Nginx 反向代理。

## Directory / 目录

- `docker-compose.infra.yml`: infra stack compose file.
- `postgres/`: PostgreSQL image and init SQL.
- `redis/`: Redis configuration.
- `nginx/`: reverse proxy config.
- `scripts/healthcheck.sh`: quick health checks.
- `scripts/wait-for-it.sh`: wait for host:port readiness.

## Quick Start / 快速开始

```bash
cd services/infra-core
cp .env.example .env
docker compose -f docker-compose.infra.yml up -d
```

## Routes / 路由

- `/` -> `frontend:3000`
- `/api/v1/ai/*` -> `ai-provider-hub:8001`
- `/api/v1/knowledge/*` -> `knowledge-engine:8002`
- `/api/v1/news/*` -> `news-aggregator:8005`
- `/api/v1/video-analysis/*` -> `video-analysis:8006`
- `/v1/*` -> `ai-provider-hub:8001` (OpenAI compatible)

## Environment Variables / 环境变量

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_USER` | `omni_user` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `changeme_in_production` | PostgreSQL password |
| `POSTGRES_DB` | `omni_vibe_db` | PostgreSQL database |
| `POSTGRES_PORT` | `5432` | PostgreSQL exposed port |
| `REDIS_PASSWORD` | `changeme_redis` | Redis password |
| `REDIS_PORT` | `6379` | Redis exposed port |
| `NGINX_PORT` | `80` | HTTP reverse proxy port |
| `NGINX_SSL_PORT` | `443` | HTTPS reverse proxy port |

## Health Check / 健康检查

```bash
docker compose -f docker-compose.infra.yml ps
docker compose -f docker-compose.infra.yml exec nginx wget -qO- http://localhost/health
```

## FAQ

1. Q: Why is `wait-for-it.sh` included if compose has healthcheck?  
   A: It is used by dependent service entrypoints where strict startup ordering is required.

2. Q: Why keep both `/api/v1/ai/*` and `/v1/*`?  
   A: `/api/v1/ai/*` is internal native API; `/v1/*` is for OpenAI-compatible clients.
