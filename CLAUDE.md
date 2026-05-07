# omni-vibe Claude Code 指令

> 这文件是给 Claude Code（agent 主大脑）看的，不是产品文档。

## omni MCP server

omni 暴露 34 个 tool（W1+W2+W3a+W3b+W3c+W4-A+W4-B 切片 5/8/9）：
- 查询：`list_skus`, `get_sku`, `list_kbs`, `search_kb`, `list_briefs`, `query_costs`
- 算账：`compute_margin`
- 编排辅助：`gather_brief_context`
- 生成：`generate_brief`, `generate_image`, `generate_video`, `generate_image_compare`
- KB 写入：`kb_upload_doc`, `kb_set_role`
- 抓数：`fetch_compass_*` (3), `fetch_yuntu_5a`, `fetch_yuntu_brand_mind`
- 通用：`summarize_text`, `parse_long_doc_with_gemini`, `query_template_chunks`
- Agent 进化：`rate_tool_call`, `agent_self_review`, `codify_pattern_to_skill`, `refresh_project_context`
- W4 加分：`save_decision`, `schedule_observation`, `send_wecom_message`, `dy_publish_creative`
- 字典查询：`list_product_prices`（工厂出厂价）, `list_channel_fees`（渠道扣点）
- 写入（require_approval=True）：`record_cost`, `disable_cost_item`

调用见 `services/knowledge-engine/app/mcp/tools/`。

## 成本两版 + 口令解锁（W4-B 切片 7）

`accounting.cost_items.visibility` 三态：
- `public` 员工版（出厂价，对外可见）— record_cost 默认值
- `real` 老板真实成本（独占，需 passphrase 解锁）
- `shared` 两版共用（物流/平台扣点等共用成本）

`query_costs` / `compute_margin` 加 `view` 参数：
- `view='public'` 默认 → 看 public + shared 行（员工口径）
- `view='real'` + `passphrase=<...>` → 看 real + shared 行（老板真实账）
  - 口令在 `.env` 配 `COST_REAL_VIEW_PASSPHRASE='<x>'`；空则跳过校验
  - 口令错或缺 → 返 `wrong_passphrase`，**不暴露真实成本**

**老板录两版的标准操作**：
1. 录员工版：`record_cost(sku_id=..., visibility='public', unit_cost='X')`
2. 录真实版：`record_cost(sku_id=..., visibility='real', unit_cost='Y')`
3. 物流/扣点等共用项：`record_cost(..., visibility='shared')`

## 工厂出厂价字典（W4-B 切片 8）

`accounting.product_price_list` 存所有**工厂单品**的出厂价（条码维度，不绑
mvp_sku）。当前来源：`F:\和田宽电商\价格表（内部）\酱油价格表.xlsx` 的
"和田宽产品"+"辣嘴宽心系列产品" 99 行（不含锦百合）。

mcp tool：`list_product_prices(query='', vendor='', barcode='', limit=30)`
- query 模糊搜（match product_name / spec / grade）
- vendor 精确：`'和田宽产品'` 或 `'辣嘴宽心系列产品'`
- barcode 精确（命中后忽略 query/vendor）

**典型用法（agent 组 mvp_sku 成本时调）**：
1. 老板说"算 SKU-X 的出厂价" → agent 先看 mvp_sku.name 推它由哪些工厂
   单品组成（如套装 = 2×500ml + 2×200ml）
2. 调 `list_product_prices(query='米糀辣酱油', vendor='辣嘴宽心系列产品')`
   拿对应工厂 SKU 出厂价
3. 算总和（数量 × 单价 × 套装关系）
4. 录到 `cost_items(sku_id=mvp_sku, visibility='public', unit_cost=算出的)`

## 渠道扣点（W4-B 切片 9）

`accounting.channel_fees` 存各渠道当前生效的扣点率（按 GMV % 或固定每单）。
当前已录：抖音 2%（抖店技术服务费）。

`compute_margin` 不显式传 `channel_fee_rate` 时**自动 fallback** 查这表
（按 channel 找 active percentage 行）；找不到再兜底 5%。breakdown 返
`fee_rate_source` 字段表明来源：`'caller'` / `'channel_fees'` / `'default'`。

`list_channel_fees(channel='')` 查全部或某渠道的当前扣点。

老板要改/加新渠道（如天猫 5%）：
```sql
INSERT INTO accounting.channel_fees (channel, fee_type, fee_rate, description)
  VALUES ('tmall', 'percentage', 0.05, '天猫扣点');
-- 或改：旧行 valid_to=今天 + 新行 valid_from=明天
```

## sku 出片标准链路（老板说"sku-X 全链路"时按此走）

> W3a 起：第 3 步从"裸 LLM"升级为"先 KB grounding 再 LLM"。

1. 调 `query_costs(sku_id)` 拿成本（如返空，提醒老板要么 `record_cost` 录入，要么 `python /app/scripts/import_costs.py` 批量导入）
2. 调 `compute_margin(sku_id, channel)` 算利润，给老板审；老板满意进 3
3. **brief 出片三步走**：
   3a. 调 `gather_brief_context(sku_id, channel)` 拿 KB 上下文（authoritative + template + private_doc 三类）
   3b. 调 `generate_brief(sku_id, channel, kb_context=<3a 返的>, extra_context=<老板临时要求>)` 出 brief
   3c. 给老板审 brief 的 result + sources（看 KB 引用命中是否合理）；老板满意进 4
4. 调 `generate_image(prompts=[3 个分镜 prompt], face_refs/product_refs)` 出 3 张分镜图，给老板审；老板满意进 5
5. 调 `generate_video(segments=[3 段 prompt + 首尾帧链], face_refs, product_refs)` 出 3 段视频，给老板下载

每步跑完把 result + trace + next_step_hint 都给老板看。**不要一气呵成跑完整套**——每步停下来等老板反馈。

## 老板响应词约定

| 老板说 | 含义 | Claude 应做 |
|---|---|---|
| OK / 继续 / 赞 / 通过 / 进下一步 | 当前 step 满意，进下一步 | 按 next_step_hint.suggested_tool + suggested_args 调下一个 tool |
| 重来 / 改 / 不行 / 重跑 | 当前 step 不满意 | 用同 tool 重调，参数照老板新说法改（如老板说"prompt 加 X"，把 X 加进 extra_context 或改 prompts/*.md） |
| 第 N 张重来 / 第 N 段重做 | 局部重跑 | 只重调那一段（generate_image 单独一个 prompt；generate_video 单独一个 segment） |
| 跳过 X / 不要这步 | 跳一步 | 不调 X，按链路下一步走 |
| 全链路 / 跑通 | 触发标准链路 | 从 step 1 query_costs 起按上面 5 步走，每步停下等老板反馈 |
| 录成本 / 加成本 / 录入物流费 | cost 数据录入 | 调 `record_cost(...)`，老板用 `python -m app.mcp.cli_approve approve <id>` 批 |
| KB 没命中 / KB 引用不对 | 3a 返回的上下文不好 | 看 sources 哪个 kb_role 弱，提示老板"补 X 类 KB" 或换 query 重调 gather_brief_context |
| 改 prompt / 改 brief 系统提示 | 改 prompt 不改代码 | 编辑 `services/knowledge-engine/config/prompts/<tool>.{system,user}.md`，KE 容器无需 restart（mtime 自检） |

## 业务 skill 第二批（W4-B 切片 10，2026-05-07）

`.claude/skills/` 下话术触发的 5 个业务 skill（cost-luru 是切片 1 录成本专项，下面 5 个是内容/数据/分析专项）：

| skill | 老板话术触发 | 串什么 tool | 输出 |
|---|---|---|---|
| `selling-point-finder` | "找 X 卖点" | get_sku → query_template_chunks → search_kb(template) | 三类卖点（功能/情绪/场景）|
| `script-writer` | "给 X 写脚本/直播话术/文案" | get_sku → query_template_chunks → search_kb → generate_brief | 脚本草稿（kb_context 注入避免裸跑）|
| `product-analysis` | "分析 X / X 卖得咋样 / X 还能推不" | get_sku → query_costs → compute_margin → fetch_compass_sku_detail → search_kb | 5 维度健康度报告 + 3 条建议 |
| `crowd-sop` | "圈一个 X 的人群包/X 受众咋定" | search_kb(authoritative+methodology) → query_template_chunks | 可复制进抖店/巨量后台的圈人策略文 |
| `daily-store-pulse` | "看店铺/今日大盘/最近店铺咋样" | fetch_compass_store_daily → fetch_yuntu_brand_mind → search_kb(methodology) | 店铺脉搏日报 + 异动判断 |

通用约束（5 个 skill 都遵守）：
- **每步停下等反馈**，不一气呵成（同 cost-luru 5 步走风格）
- 输出**带来源**（哪条 KB / 哪个 SKU 字段），feedback memory 强反幻觉
- **说人话**，禁 AI 化套话（赋能/打通/闭环/抢占心智 等）
- gmv 字段统一 `gmv_paid`（用户支付金额）

老板用 `/<skill-name>` 也能强制触发；通常按话术 Claude 会自动判断。

## prompt 调整三通道（W3a 新）

老板"随时能调，越用越准"。三种通道并存：
1. **大改**：直接改 `config/prompts/<tool>.{system,user}.md`（永久生效）
2. **一次性**：`extra_context` 参数注入（`generate_brief(..., extra_context="这次主推健康")`，下次自动遗忘）
3. **结构化补料**：`kb_context` 参数（gather_brief_context 出，或老板手拼）

## 当前业务底色（自动刷新）

> 由 `refresh_project_context` tool 渲染到 `data/agent_state/dynamic_block.md`，老板批 Gate 后手动复制粘到下面 marker 之间的区块。Marker 行不要删——下次刷新替换的就是这两行之间的内容。

<!-- omni-dynamic:start -->
## 当前业务底色（自动刷新于 2026-05-07 03:38:06Z）

### 重点池 SKU（status=active）
- `SKU-367991-0002` — 和田宽有机本酿造特级酱油无添加提鲜生抽老抽炒菜健康老式传统
- `SKU-367994-0003` — 和田宽有机5度白米醋原料酿造炒菜凉拌蘸食醋饮（试吃装2瓶200ml）
- `SKU-368978-0004` — 和田宽有机5度黑醋有机酿造食用醋炒菜凉拌调味料
- `SKU-373910-0013` — 和田宽外卖酱油包小包辣油酱油包生抽水饺蘸料包 辣酱油10ml*10包
- `SKU-375753-0001` — 和田宽特级辣酱油500ml* 2瓶送200ml*2瓶零添加蘸食凉拌饺子酱油
- `SKU-375763-0000` — 和田宽5度米椛辣黑醋500ml *2瓶送200ml*2零添加酿造食醋蘸食拌菜
- `SKU-376253-0012` — 和田宽有机本酿造特级无添加剂日式酱油200ml
- `SKU-378043-0005` — 和田宽有机5度黑醋有机酿造食用醋炒菜凉拌调味料200ml
- `SKU-378044-0008` — 和田宽有机5度白米醋200ml有机食用醋调味料纯粮食醋进口零添加
- `SKU-378044-0009` — 和田宽有机5度白米醋200ml有机食用醋调味料纯粮食醋进口零添加
- `SKU-378044-0010` — 和田宽有机5度白米醋200ml有机食用醋调味料纯粮食醋进口零添加
- `SKU-378044-0011` — 和田宽有机5度黑醋有机酿造食用醋炒菜凉拌调味料200ml
- `SKU-380920-0006` — 和田宽寿喜烧250ml 日式风味 锅汁底料
- `SKU-380920-0007` — 和田宽寿喜烧250ml 日式风味 锅汁底料

### 缺成本 SKU（active 但 accounting.cost_items 全空）
- `SKU-368978-0004` — 和田宽有机5度黑醋有机酿造食用醋炒菜凉拌调味料（用 record_cost 录入）
- `SKU-378043-0005` — 和田宽有机5度黑醋有机酿造食用醋炒菜凉拌调味料200ml（用 record_cost 录入）
- `SKU-380920-0006` — 和田宽寿喜烧250ml 日式风味 锅汁底料（用 record_cost 录入）
- `SKU-380920-0007` — 和田宽寿喜烧250ml 日式风味 锅汁底料（用 record_cost 录入）
- `SKU-378044-0010` — 和田宽有机5度白米醋200ml有机食用醋调味料纯粮食醋进口零添加（用 record_cost 录入）
- `SKU-378044-0011` — 和田宽有机5度黑醋有机酿造食用醋炒菜凉拌调味料200ml（用 record_cost 录入）
- `SKU-376253-0012` — 和田宽有机本酿造特级无添加剂日式酱油200ml（用 record_cost 录入）
- `SKU-375763-0000` — 和田宽5度米椛辣黑醋500ml *2瓶送200ml*2零添加酿造食醋蘸食拌菜（用 record_cost 录入）
- `SKU-375753-0001` — 和田宽特级辣酱油500ml* 2瓶送200ml*2瓶零添加蘸食凉拌饺子酱油（用 record_cost 录入）
- `SKU-367994-0003` — 和田宽有机5度白米醋原料酿造炒菜凉拌蘸食醋饮（试吃装2瓶200ml）（用 record_cost 录入）

### 待批 Human Gate
- _无_
<!-- omni-dynamic:end -->

## 后台 cron 任务（W4-B 切片 4 + 11）

KE 容器 lifespan 启动期起 3 个 asyncio loop，每小时唤醒一次检查 last_run。
失败容忍（log warning 不挂），容器停就停（不是 SLA 服务）。

| cron | 周期 | 动作 | 写文件 |
|---|---|---|---|
| `weekly_self_review` | 7 天 | 调 `agent_self_review(period_days=7)` | `data/agent_state/weekly_review.md` |
| `daily_pulse` | 1 天 | 调 `fetch_compass_store_daily` + `fetch_yuntu_brand_mind` | `data/agent_state/daily_pulse.md` |
| `dynamic_block_refresh` | 7 天 | 调 `agent_meta._refresh_impl`（绕 require_approval）| `data/agent_state/dynamic_block.md` |

每个 cron 各一个 `last_*.txt` 文件持久化时间戳。**老板手动**把 dynamic_block.md
新内容粘到本文件 `<!-- omni-dynamic:start ... :end -->` marker 之间（cron 不
自动改 CLAUDE.md，因为 CLAUDE.md 入 git 老板要审）。

实现：`services/knowledge-engine/app/mcp/cron.py`

## 已知约束

- 不调 `run_sku_orch` —— 没这个 tool，编排靠对话
- LLM tool 必返 `trace` 字段，老板要看 final_prompt 才能调 prompt 重跑
- video 多段并发跑（asyncio.gather），typically 30-60s 每段；并发后总时间 ≈ 单段
- W2 5 个 LLM tool 不走 Human Gate；W3a 加的 `record_cost` / `disable_cost_item` 走 Gate（CLI 批）
- cron 跑数据来自 DB（scout-agent 最近一次 runbook 抓的）；cron 本身**不**主动跑 scout runbook（罗盘 cookie 浮动，runbook 老板手动跑）

## 调试常用命令

- **容器内自检**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"` —— 应输出 13 项全 OK 的 tool 列表
- **审计表**：`docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT tool_name, status, duration_ms FROM mcp.tool_calls ORDER BY created_at DESC LIMIT 20"`
- **ai-provider-hub 状态**：`curl http://localhost:8001/api/v1/ai/providers`
- **Human Gate 批/驳**（W3a）：
  - 列待批：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve list`
  - 批：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <short_id> --note "OK"`
  - 驳：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve reject <short_id> --note "原因"`
  - 持续看：`docker exec -it omni-knowledge-engine python -m app.mcp.cli_approve tail`（Ctrl-C 退）
- **prompt 模板列表**：`docker exec omni-knowledge-engine python -c 'from app.mcp import prompts; [print(t) for t in prompts.list_templates()]'`
- **CSV 导入 cost_items**：`docker exec omni-knowledge-engine python /app/scripts/import_costs.py /app/scripts/cost_template.csv`（先 `--dry-run` 预演）
