# Win → Mac 整栈迁移 Runbook（2026-06-12）

> 目标：Mac 成为开发+使用主力机（前端 + 后端 + 桌面客户端 + 全部数据），Win 降级为备份。
> 迁移包在 Win 的 `E:\agent\mac-migration-20260612\`（数据库 dump 2.6GB + KE 数据卷 1GB + cookies + 秘密包 + Claude 环境包 + 未提交工作快照）——**整个目录先用移动硬盘 / Tailscale Taildrop / 隔空投送拷到 Mac**（建议放 `~/omni-migration/`）。

## 0. Mac 装基础（一次性）

```bash
# Docker：推荐 OrbStack（比 Docker Desktop 快且省电）
brew install orbstack
# Node 20+
brew install node@20 && brew link node@20
# Claude Code
npm i -g @anthropic-ai/claude-code
claude   # 首次启动登录你的 Max 订阅
```

## 1. 拉代码

```bash
mkdir -p ~/agent && cd ~/agent
git clone https://github.com/252180478yark-lang/omni.git
git clone https://github.com/252180478yark-lang/omni-desktop.git
cd ~/agent/omni && git checkout feat/audience-portrait-brief
cd ~/agent/omni-desktop && git checkout feat/w1-tool-feedback
```

## 2. 秘密归位

```bash
cd ~/omni-migration
unzip secrets-bundle.zip -d secrets/
# manifest.txt 列了全部相对路径；逐个放回：
# secrets/omni/.env                        → ~/agent/omni/.env
# secrets/omni/frontend/.env.local         → ~/agent/omni/frontend/.env.local
# secrets/omni/services/<服务>/.env(.dev)  → ~/agent/omni/services/<服务>/
cp -R secrets/omni/. ~/agent/omni/
```

## 3. 起数据库并恢复（核心数据：KB 向量/血缘/成本账/反馈/自建 SOP 全在这）

```bash
cd ~/agent/omni
docker compose up -d postgres redis
sleep 10
docker cp ~/omni-migration/omni-full-20260612.dump omni-postgres:/tmp/
docker exec omni-postgres pg_restore -U omni_user -d omni_vibe_db --clean --if-exists --no-owner /tmp/omni-full.dump
docker exec omni-postgres rm /tmp/omni-full-20260612.dump 2>/dev/null || docker exec omni-postgres rm /tmp/omni-full.dump
# 验收：有审计数据 = 恢复成功
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT count(*) FROM mcp.tool_calls"
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT count(*) FROM public.schema_migrations"   # 应 50
```

（pg_restore 中 "role does not exist" 类警告可忽略——`--no-owner` 已处理；恢复要几分钟。）

## 4. 恢复数据卷（cookies + KE 文件）

```bash
cd ~/omni-migration
docker run --rm -v omni_scout_sessions:/v -v "$PWD":/in alpine tar xzf /in/vol-scout_sessions.tgz -C /v
docker run --rm -v omni_knowledge_data:/v -v "$PWD":/in alpine tar xzf /in/vol-knowledge_data.tgz -C /v
```

（knowledge_data 包里剔除了 hf 模型缓存，首次用到会自动重新下载。）

## 5. 起全栈 + 验收

```bash
cd ~/agent/omni
docker compose up -d --build     # 首次 build 要几分钟
# 验收三连：
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"   # 应 all 86 ok
curl http://localhost:8001/api/v1/ai/providers | head -c 300                                        # hub 各 provider api_key_set
curl -s -X POST http://localhost:8002/api/v1/mcp/catalog/exec -H 'Content-Type: application/json' -d '{"tool_name":"list_channel_fees","args":{}}' | head -c 200
```

## 6. 未提交工作快照（Win 上另一会话的半成品）

`~/omni-migration/working-tree-uncommitted/`：含 `uncommitted-tracked.patch` + 散文件。到 Mac 的 omni 仓库里 `git apply uncommitted-tracked.patch`（或按 README.txt 手动放回），看完决定提交或丢弃。

## 7. Claude 环境归位

```bash
cd ~/omni-migration/_claude_stage
cp CLAUDE.md ~/.claude/CLAUDE.md
cp settings.json ~/.claude/settings.json 2>/dev/null
cp -R skills ~/.claude/skills
# 记忆库（按项目路径 key）：先在 ~/agent 下跑一次 claude 让它生成项目目录，
# 看 ~/.claude/projects/ 里新出现的目录名（形如 -Users-你-agent），把 memory 拷进去：
cp -R projects/E--agent/memory ~/.claude/projects/<新目录名>/memory
```

## 8. 前端（web）

```bash
cd ~/agent/omni/frontend
npm install
npm run dev          # http://localhost:3000（/sku-pipeline 等页面）
```

## 9. 桌面客户端

```bash
cd ~/agent/omni-desktop
npm install
npm run pack:mac     # 出 DMG 在 release/<版本>/，安装即用
# 开发态用 npm run dev
```
装好后打开设置：omniKeUrl = `http://localhost:8002`（整栈在本机）。

## 10. 大业务文件（按需，移动硬盘拷）

- `F:\和田宽电商\`（价格表等内部表格——cost-luru 桥接会引用）
- `E:\agent\人群\`（圈层 PDF 源档；**KB 内容已在数据库里**，源档是备查可选）
- `E:\agent\知识库备份\`、`E:\agent\测试日志\`（归档可选）

## 11. Tailscale 角色切换

Mac 跑通后：手机 PWA / 其他端把地址从 Win 的 tailnet IP 改成 Mac 的；Win 上 `docker compose stop` 降级为冷备（数据已全量带走，别再双写）。

## 12. 总验收（一条龙）

桌面 app → 🧰 技能与工具中心 → 💰 成本与利润 → 「查成本明细」选 SKU-375753-0001 → 出真数据 = 数据库/KE/客户端全链通。再跑一次「人群画像」确认 LLM 链路（hub key）也通。

## 已知注意项

- **不要两台机器同时跑全栈**：数据库会分叉。Mac 验收通过后 Win 必须停栈。
- compose 无 Windows 特定宿主机路径挂载（均为相对路径 bind + 命名卷），Mac 无需改 compose。
- scout 抓取（淘宝/罗盘）依赖国内网络环境，Mac 上网络条件变了首跑可能要重新扫码登录（`POST /api/v1/scout/taobao/relogin`）。
- `tool_models.local.yaml`（模型配置覆盖文件）在 gitignore 里不随 git 走——如果你在 Win 上改过工具模型，把 `services/knowledge-engine/config/tool_models.local.yaml` 也手动拷一下。
