# Omni runtime profiles

根目录 `docker-compose.yml` 是 canonical Compose 运行面，`config/runtime-manifest.yaml` 是 profile、服务归属、生命周期和 core required 语义的机器真源。启动前必须由 `scripts/runtime_allocation.py acquire --runtime-profile <name>` 获取 RuntimeAllocation；allocation 会同时投影 `OMNI_RUNTIME_PROFILE` 和 `COMPOSE_PROFILES`，preflight 与 live guard 会拒绝 profile 不一致的证据。

旧 allocation 没有 `runtime_profile`，只能读取和释放，不能继续启动。请先停止旧运行面并 release，再重新 acquire；禁止把历史全量运行面默认为 core。

## 精确服务集合

| profile | Compose 投影 | 常驻服务 | 一次性任务 | 浏览器入口（canonical 端口） |
|---|---|---|---|---|
| `core`（默认） | 无 profile | `postgres`、`redis`、`identity-service`、`ai-provider-hub`、`knowledge-engine`、`frontend` | `runtime-preflight`、`migrate` | 直连 frontend：`http://localhost:3000` |
| `content` | `content` | core + `video-analysis`、`livestream-analysis`、`scout-agent` | 同 core | 直连 frontend：`http://localhost:3000` |
| `full` | `full` | content + `news-aggregator`、`ad-review-service`、`nginx` | 同 core | 经 nginx：`http://localhost:80` |

Compose profile 没有继承语义，所以三个内容服务同时声明 `content` 和 `full`。nginx 只属于 full：它的配置在启动时解析全部上游 Docker DNS 名称，把 nginx 单独放进 core/content 会因缺少 optional upstream 而失败。

非 canonical allocation 使用隔离端口；以上 `3000/80` 是 canonical 默认值，实际入口以 allocation 的 `FRONTEND_PORT` 或 `NGINX_HTTP_PORT` 为准。

## 启动与验证

取得 allocation 并把返回的 `environment` 导入当前 shell 后：

```bash
# OMNI_RUNTIME_PROFILE=core，COMPOSE_PROFILES 为空
docker compose up -d

# allocation 会把 COMPOSE_PROFILES 分别投影为 content/full；显式参数也可用于人工复核
docker compose --profile content up -d
docker compose --profile full up -d

python -B scripts/runtime_guard.py verify \
  --runtime-id "$OMNI_RUNTIME_ID" \
  --runtime-profile "$OMNI_RUNTIME_PROFILE" \
  --allocation-id "$OMNI_ALLOCATION_ID"
```

`verify` 只要求所选 profile 的常驻服务，忽略已完成的一次性任务；同一 runtime 中若仍运行其他 profile 的服务，会报 `unexpected_profile_service`，不能得到假绿色。健康检查也只覆盖所选 profile，并优先使用容器真实映射端口，避免隔离 allocation 误探 canonical 端口。

Windows 入口：

```powershell
.\dev-start.ps1                              # core：host frontend，直连 FRONTEND_PORT
.\dev-start.ps1 -RuntimeProfile content      # exact content Compose，直连 FRONTEND_PORT
.\dev-start.ps1 -RuntimeProfile full         # exact full Compose，经 NGINX_HTTP_PORT
```

`content/full` 必须保持完整 Docker DNS 链，因此不接受 `-SkipDocker`、`-SkipFrontend` 或 `-Only`。这些开关只用于 core 局部调试，局部启动不得冒充 profile 已验证。`-NoOptional` 已退化为 core 兼容别名，但不会关闭必需的 `identity-service`。

## 安全降级、切换与回滚

Compose `up` 不会自动停止上一个 profile 的容器。不要在同一 active allocation 上把 `COMPOSE_PROFILES` 从 full 改成 core；profile 是 allocation 的不可变身份，变更会触发 CAS 冲突。

安全步骤：

1. 保留当前 allocation 环境，运行 `docker compose down` 停止该 Compose project；不要加 `-v`。
2. 确认没有该 runtime 的常驻容器后，按 owner 和 revision release allocation。
3. 用目标 `--runtime-profile core|content|full` 重新 acquire，再启动并运行 guard verify。

可选服务故障时也使用上述流程降级到 core。不得只停掉故障容器后继续宣称 content/full 健康，也不得用固定端口清理其他 runtime。

profile 收敛不重命名服务、API、网络或 named volume，不执行数据库迁移，不删除 Compose service。数据卷保持不变；任何情况下都不得执行 `down -v`、volume prune、image prune 或 build-cache prune。
