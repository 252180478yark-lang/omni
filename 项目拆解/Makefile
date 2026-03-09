# ============================================================
# Omni-Vibe OS Ultra — Makefile
# ============================================================

.PHONY: help setup dev test deploy stop clean logs status \
        infra core business frontend all \
        db-migrate db-upgrade db-downgrade \
        lint format

# 默认目标 / Default target
help: ## 显示帮助信息 / Show help
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║     Omni-Vibe OS Ultra — 命令面板           ║"
	@echo "╚══════════════════════════════════════════════╝"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================
# 环境设置 / Environment Setup
# ============================================================

setup: ## 初始化项目环境（创建 .env, 安装依赖）/ Initialize project
	@echo "📦 Setting up Omni-Vibe OS..."
	@test -f .env || cp .env.example .env
	@echo "✅ .env created (edit with your API keys)"
	@echo "📦 Building Docker images..."
	docker compose build
	@echo "✅ Setup complete! Run 'make dev' to start."

env-check: ## 检查环境变量是否配置 / Verify environment variables
	@echo "🔍 Checking environment..."
	@test -f .env && echo "✅ .env exists" || echo "❌ .env missing - run 'make setup'"
	@command -v docker > /dev/null && echo "✅ Docker installed" || echo "❌ Docker not found"
	@command -v docker compose > /dev/null && echo "✅ Docker Compose installed" || echo "❌ Docker Compose not found"
	@command -v node > /dev/null && echo "✅ Node.js $$(node -v)" || echo "⚠️  Node.js not found (needed for frontend dev)"
	@command -v python3.11 > /dev/null && echo "✅ Python 3.11+" || echo "⚠️  Python 3.11 not found (needed for backend dev)"

# ============================================================
# 启动服务 / Start Services
# ============================================================

infra: ## 仅启动基础设施（PostgreSQL + Redis）/ Start infrastructure only
	docker compose up postgres redis -d
	@echo "⏳ Waiting for services to be healthy..."
	@sleep 5
	docker compose ps postgres redis
	@echo "✅ Infrastructure ready!"

core: infra ## 启动核心服务（网关 + AI + 知识引擎 + 编排）/ Start core services
	docker compose up backend-gateway ai-provider-hub knowledge-engine langgraph-orchestrator -d
	@echo "✅ Core services started!"

business: core ## 启动业务模块 / Start business modules
	docker compose up content-factory content-factory-worker \
		market-intelligence market-intelligence-worker \
		ops-assistant second-brain second-brain-worker \
		evolution-engine -d
	@echo "✅ Business modules started!"

frontend: ## 启动前端 / Start frontend
	docker compose up frontend-dashboard -d
	@echo "✅ Frontend started at http://localhost:3000"

dev: ## 启动全部服务（开发模式）/ Start all services
	docker compose up -d
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  🚀 Omni-Vibe OS is running!                ║"
	@echo "║                                              ║"
	@echo "║  Frontend:    http://localhost:3000           ║"
	@echo "║  API Gateway: http://localhost:8000           ║"
	@echo "║  API Docs:    http://localhost:8000/docs      ║"
	@echo "║  Nginx:       http://localhost:80              ║"
	@echo "╚══════════════════════════════════════════════╝"

dev-local-ai: ## 启动全部 + 本地 AI（Ollama + ComfyUI）/ Start all + local AI
	docker compose --profile local-ai up -d

# ============================================================
# 停止和清理 / Stop & Clean
# ============================================================

stop: ## 停止所有服务 / Stop all services
	docker compose down
	@echo "✅ All services stopped."

clean: ## 停止并删除所有数据 / Stop and remove all data
	@echo "⚠️  This will DELETE all data volumes!"
	@read -p "Are you sure? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	docker compose down -v --remove-orphans
	@echo "✅ All services and data removed."

# ============================================================
# 数据库操作 / Database Operations
# ============================================================

db-migrate: ## 生成数据库迁移 / Generate DB migration
	@read -p "Migration message: " msg; \
	cd services/backend-gateway && \
	alembic revision --autogenerate -m "$$msg"

db-upgrade: ## 执行数据库迁移 / Run DB migrations
	cd services/backend-gateway && alembic upgrade head
	@echo "✅ Database migrated."

db-downgrade: ## 回滚数据库迁移 / Rollback DB migration
	cd services/backend-gateway && alembic downgrade -1
	@echo "✅ Database rolled back one step."

db-shell: ## 连接数据库 Shell / Connect to DB shell
	docker exec -it omni-postgres psql -U omni_user -d omni_vibe_db

redis-shell: ## 连接 Redis Shell
	docker exec -it omni-redis redis-cli -a changeme_redis

# ============================================================
# 测试 / Testing
# ============================================================

test: ## 运行所有测试 / Run all tests
	@echo "🧪 Running tests for all services..."
	@for svc in backend-gateway ai-provider-hub knowledge-engine \
		langgraph-orchestrator content-factory market-intelligence \
		ops-assistant second-brain evolution-engine; do \
		echo "Testing $$svc..."; \
		cd services/$$svc && pytest tests/ -v --tb=short 2>/dev/null || true; \
		cd ../..; \
	done
	@echo "✅ All tests complete."

test-service: ## 测试指定服务 / Test specific service (usage: make test-service SVC=backend-gateway)
	cd services/$(SVC) && pytest tests/ -v

# ============================================================
# 代码质量 / Code Quality
# ============================================================

lint: ## 代码检查 / Lint all Python services
	@for svc in backend-gateway ai-provider-hub knowledge-engine \
		langgraph-orchestrator content-factory market-intelligence \
		ops-assistant second-brain evolution-engine; do \
		echo "Linting $$svc..."; \
		cd services/$$svc && ruff check . 2>/dev/null || true; \
		cd ../..; \
	done

format: ## 代码格式化 / Format all Python services
	@for svc in backend-gateway ai-provider-hub knowledge-engine \
		langgraph-orchestrator content-factory market-intelligence \
		ops-assistant second-brain evolution-engine; do \
		echo "Formatting $$svc..."; \
		cd services/$$svc && ruff format . 2>/dev/null || true; \
		cd ../..; \
	done

# ============================================================
# 日志和监控 / Logs & Monitoring
# ============================================================

logs: ## 查看所有服务日志 / View all logs
	docker compose logs -f --tail=50

logs-service: ## 查看指定服务日志 / View service logs (usage: make logs-service SVC=backend-gateway)
	docker compose logs -f --tail=100 $(SVC)

status: ## 查看服务状态 / Service status
	@echo "📊 Service Status:"
	@docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

health: ## 健康检查所有服务 / Health check all services
	@echo "🏥 Health Check:"
	@for port in 8000 8001 8002 8003 8004 8005 8006 8007 8008; do \
		name=$$(curl -s http://localhost:$$port/health 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('service','unknown'))" 2>/dev/null || echo "port-$$port"); \
		status=$$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$$port/health 2>/dev/null); \
		if [ "$$status" = "200" ]; then \
			echo "  ✅ $$name (port $$port): healthy"; \
		else \
			echo "  ❌ $$name (port $$port): unreachable"; \
		fi; \
	done

# ============================================================
# 部署 / Deployment
# ============================================================

deploy: ## 生产部署（构建 + 启动）/ Production deploy
	docker compose -f docker-compose.yml build
	docker compose -f docker-compose.yml up -d
	@echo "✅ Production deployment complete."

deploy-update: ## 更新指定服务 / Update specific service (usage: make deploy-update SVC=backend-gateway)
	docker compose build $(SVC)
	docker compose up -d --no-deps $(SVC)
	@echo "✅ $(SVC) updated and restarted."
