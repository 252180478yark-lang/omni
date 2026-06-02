# omni-vibe Claude Code 指令

> 这文件是给 Claude Code（agent 主大脑）看的，不是产品文档。

## omni MCP server

omni 暴露 46 个 tool（W1+W2+W3a+W3b+W3c+W4-A+W4-B 切片 5/8/9/14）：
- 查询：`list_skus`, `get_sku`, `list_kbs`, `search_kb`, `list_briefs`, `query_costs`
- 算账：`compute_margin`
- 编排辅助：`gather_brief_context`
- 生成：`generate_brief`, `generate_image`, `generate_video`, `generate_image_compare`
- sku-pipeline LLM：`generate_selling_points_matrix`（step 2）, `generate_audience_match`（step 3）, `generate_audience_pack`（step 4，phase B）, `generate_keyword_pack`（500 词扩展，phase B+）, `generate_creative_pack`（step 5 创意素材 6 类，phase C）
- KB 写入：`kb_upload_doc`, `kb_set_role`
- 抓数：`fetch_compass_*` (3), `fetch_yuntu_5a`, `fetch_yuntu_brand_mind`
- 通用：`summarize_text`, `parse_long_doc_with_gemini`, `query_template_chunks`
- Agent 进化：`rate_tool_call`, `agent_self_review`, `codify_pattern_to_skill`, `refresh_project_context`
- W4 加分：`save_decision`, `schedule_observation`, `send_wecom_message`, `dy_publish_creative`
- 字典查询：`list_product_prices`（工厂出厂价）, `list_channel_fees`（渠道扣点）
- 链路血缘（W4-B 切片 14.3 phase A）：`pipeline_list_matrix_runs`, `pipeline_get_matrix_run`, `pipeline_list_audience_runs`, `pipeline_get_audience_run`, `pipeline_list_audience_records`, `pipeline_get_audience_record`, `pipeline_adopt`
- 投后回传闭环（W1 phase D，2026-05-29）：`record_ad_metrics`（测试投放后把 ROI/GMV/完播率写回素材血缘）, `pipeline_get_asset_lineage`（按 asset 反查 SKU/卖点/人群/脚本全链路）, `pipeline_list_asset_performance`（"哪套内容真带货"榜）
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

## sku 出片链路血缘（W4-B 切片 14.3 phase A）

`pipeline` schema 6 张表，**每步落库 + 多版本 + denorm sku_id**，目的是投后视频
回传 ad_metrics 时一句 SQL 反查全链路（不用上传 SKU/卖点/人群）。

```
matrix_run (step 2) → audience_run (step 3) → audience_record (拆 N 行)
  → audience_pack (step 4 phase B 加) → script (step 5/6 phase C)
  → asset (image/video，挂 ad_metrics 投后回传)
```

**核心约定**：
- **状态两态**：`status='draft'` 跑完即落 → 老板手点采纳变 `'adopted'` → 下游只跟 adopted 走
- **多版本**：每次重跑 = 新一行（`version` 自增 + `parent_run_id` 串前后），不覆盖
- **拆 N 人群**：step 3 跑完整段 markdown 入 `audience_runs` 同时 regex 拆每个 `#### 1.X [人群名]` 段入 `audience_records`（`selected_for_pack` 标位标"老板选了挂下游"）
- **denorm `sku_id`**：6 张表都直接挂 sku_id，复盘 SQL 不用 6 join
- **反查视图**：`pipeline.v_asset_full_lineage`（按 asset_id 一句 SELECT 拉全链路）

**老板话术 → tool**：
- "看 sku-X 跑过几版卖点矩阵"  → `pipeline_list_matrix_runs(sku_id)`
- "看那次人群报告拆了几个" → `pipeline_list_audience_records(audience_run_id)`
- "选第 3 个人群挂下游" → `pipeline_adopt(table='audience_records', run_id=..., set_selected=True)`
- "把这版 matrix 采纳" → `pipeline_adopt(table='matrix_runs', run_id=...)`

**前端 /sku-pipeline**：step 3 输出已改卡片化（N 个人群独立可选）；step 2 输出
带 `matrix_run_id` 标签自动喂给 step 3。

实现：
- `migrations/021_pipeline_lineage.sql`（schema + 6 表 + 视图）
- `migrations/022_keyword_packs.sql`（关键词扩展包表，挂 sku/audience_record/pack）
- `services/knowledge-engine/app/services/pipeline_lineage.py`（save/list/get/adopt + regex 拆）
- `services/knowledge-engine/app/mcp/tools/pipeline.py`（7 个 lineage 查询/采纳 tool）

## sku-pipeline step 4 圈包 SOP（W4-B 切片 14.3 phase B）

`generate_audience_pack(audience_record_id, extra_context?)` —— 输入老板已勾选
的某个 audience_record，自动拉它关联的 matrix_run + sku + 巨量云图/千川 KB 召回，
LLM 翻译成可在巨量云图后台一步步勾选 + 可推到千川的圈人 SOP。

**输出固定 5 节**（`config/prompts/audience_pack.{system,user}.md`）：
- 第 0 部分 4 维度人群画像扩展（生活方式 / 消费习惯 / 痛点 / 触发场景，每句标 [KB] / [matrix X.Y] / [行业推理]）
- 第 1 部分 1.1 概览表 + 1.2 ASCII 圈人架构图（前置工具 → 单元 → 组合 ∩∪- → 推千川）
- 第 2 部分 N 个圈人单元（N 由 LLM 判断、无上下限），每个细到三级菜单 + 大白话理由 + 跟其他单元的关系
- 第 3 部分 交并排拓配方（只在 1 单元不够精准时给，禁止凑数）
- 第 4 部分 关键词扩展（按 4.7 判定表，目的地是云图数据工厂关键词夹）

**严禁**：脚本/钩子/文案 / 预算（测试期/放量期）/ A/B 测试矩阵 / P0-P2 优先级 /
预测 ROI 或 GMV / 推计划类型 / 重写 KB 原文 / 虚构 KB 不存在的标签
（IP 偏好只 5 类、内容偏好/行业品类兴趣三级树没给清单时让老板查实际可选项）。

**链路落库**：跑完即落 `pipeline.audience_packs`，挂 audience_record_id +
audience_run_id + matrix_run_id + sku_id 全 denorm。多版本（重跑 = 新行 +
parent_pack_id 串前后）。

## sku-pipeline 关键词扩展（W4-B 切片 14.3 phase B+）

`generate_keyword_pack(seed_keywords, target_count=500, sku_id?, audience_record_id?,
audience_pack_id?, extra_context?)` —— 输入种子词，输出 N 个**纯文本一行一词无标点**
的关键词（向量近邻词，**不是 SKU 商品维度词、不是人群属性词、不是元话题词**）。

**用途**：导入「云图 → 数据工厂 → 关键词夹 → 新建关键词包」 → 标签工厂转成
人群标签 → 回自定义人群引用 → 推千川。**不是直接进千川计划关键词定向**。

落库 `pipeline.keyword_packs`（migration 022），可挂 sku/audience_record/audience_pack。
后处理 `_clean_keyword_pack` 强制清掉标点/数字/重复，保证格式纯净。

下一步（phase D）：step 6 分镜图/视频生成挂 `pipeline.assets`、视频回传
ad_metrics 自动反查（`v_asset_full_lineage` 已建好）。

## sku-pipeline step 5 创意素材（W4-B 切片 14.4 phase C）

`generate_creative_pack(kind, sku_id?, audience_record_id?, audience_pack_id?, extra_context?)`
—— 1 个 tool 路由 6 类素材，按 `kind` 选对应 system prompt。

**6 类素材**（`config/prompts/creative_pack.<kind>.system.md` 各 1 套，user 共用 1 套）：

| kind | 媒体 | 漏斗位置 | 时长/尺寸 | 输出特点 |
|---|---|---|---|---|
| `video_soft_ad` | 视频 | A2 触动 | 25-30s | 内容娱乐化软植入 / 主脚本 + 3 钩子 + 5-7 分镜 |
| `video_planting` | 视频 | A3 共鸣 | 30-45s | 痛点+卖点串 / 主脚本 + 3 钩子 + 6-9 分镜 |
| `video_harvest` | 视频 | A4 行动 | 15-25s | 强 CTA + 限时利益 / 主脚本 + 3 钩子 + 4-6 分镜 |
| `graphic_harvest` | 图文 | A4 行动 | 300-500 字 | 标题党 + 5 段正文 + 4-6 张配图 brief |
| `product_main_image` | 商品视觉 | 列表点击 | 5-9 张主图 | 每张 1 卖点 + 大字 ≤ 8 字 + 风格关键词 |
| `product_detail_page` | 商品视觉 | 详情页 | 8-12 段长图 | 叙事 + 卖点闭环 + 信任锚（资质段没真数据就跳过） |

**弹性挂链路**（按可用性自动选）：
- 给 `audience_pack_id` → 拉 pack + record + matrix + sku（最完整链路）
- 给 `audience_record_id` → 拉 record + matrix + sku（绕过 step 4）
- 都没但给 `sku_id` → 单 SKU 模式，audience/pack 段写"通用画像"

**严禁**（所有 6 类共用）：
- 编 SKU 没有的卖点 / 资质 / 检测 / 价格 / 赠品
- AI 化套话：赋能 / 打通 / 闭环 / 抢占心智 / 极致 / 匠心 / 一站式
- 各类型独有禁忌：
  - `video_soft_ad`：直接卖货话术、价格/折扣
  - `video_harvest`：编假"已 10w+ 售出""仅剩 50 件"
  - `graphic_harvest`："宝子们""家人们" 烂俗开头
  - `product_main_image`：把多个卖点塞 1 张图、文艺词如"留白哲学"
  - `product_detail_page`："百年传承""非遗工艺" 等无依据描述

**链路落库**：跑完落 `pipeline.scripts`（migration 023 加 `kind` 字段 +
弹性挂改 nullable）。多版本（同 sku+kind 的 version 自增 + parent_script_id 串前后）。

**老板话术 → tool**：
- "给 sku-X 写个种草脚本" → `generate_creative_pack(kind='video_planting', audience_record_id=...)`
- "给 X 出收割图文" → `generate_creative_pack(kind='graphic_harvest', sku_id='X')`
- "给 X 设计 5 张主图" → `generate_creative_pack(kind='product_main_image', sku_id='X')`
- "给 X 写详情页文案" → `generate_creative_pack(kind='product_detail_page', audience_record_id=...)`

**前端 /sku-pipeline step 5 tab**：左侧选模式（record / sku）+ 6 个 kind chip
+ extra_context；右侧输出 markdown + 复制 + 下载 .md + trace 折叠。pack 模式
v1 暂未开放（老板要时再加 list_audience_packs tool + UI）。

下一步（phase D）：step 6 分镜图/视频生成挂 `pipeline.assets`，从
`pipeline.scripts.scenes` JSONB 拉分镜清单 + 首帧 hint 喂给 generate_image。

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

## 业务 skill 全集（cost-luru + 5 业务 + 1 编排，W4-B 切片 10/12/13）

`.claude/skills/` 下 7 个话术触发的 skill。**单点 skill** 5 个 + **数据/录入** skill 1 个 + **编排型** skill 1 个：

| skill | 老板话术触发 | 类型 | 串什么 tool | 输出 |
|---|---|---|---|---|
| `cost-luru` | "录 X 成本" / "算 X 出厂价" / "重录 X" | 录入（双路径）| record_cost / disable_cost_item / list_product_prices / query_costs | 成本入库（路径 A 单笔 / 路径 B 工厂出厂价桥接）|
| `selling-point-finder` | "找 X 卖点" | 单点 | get_sku（owner_selling_points 优先）→ search_kb / query_template_chunks | 三类卖点（功能/情绪/场景）|
| `script-writer` | "给 X 写脚本/直播话术/文案" | 单点 | get_sku（specifications/price 真实字段）→ search_kb → generate_brief | 脚本草稿（kb_context 注入防裸跑）|
| `product-analysis` | "分析 X / X 卖得咋样 / X 还能推不" | 单点 | get_sku（platform_status 7 态警告）→ query_costs → compute_margin → fetch_compass_sku_detail → search_kb | 健康度报告 + 3 条建议 |
| `crowd-sop` | "圈一个 X 的人群包/X 受众咋定" | 单点 | get_sku(growth_class) → search_kb(authoritative+methodology) → query_template_chunks | 可复制进抖店/巨量后台的圈人策略 |
| `daily-store-pulse` | "看店铺/今日大盘" | 单点 | fetch_compass_store_daily → fetch_yuntu_brand_mind → search_kb(methodology) | 店铺脉搏日报 + 异动判断 |
| `sku-pipeline` | "X 全链路 / 给 X 出片 / 跑通 X" | **编排** | 5 步走串：query_costs → compute_margin → script-writer 子流程 → generate_image*3 → generate_video*3 → save_decision | 完整出片 + 入档 |

通用约束（7 个 skill 都遵守）：
- **每步停下等反馈**，不一气呵成（cost-luru 5 步走风格 + sku-pipeline 烧钱 step）
- 输出**带来源**（哪条 KB / 哪个 mvp_sku 字段），feedback memory 强反幻觉
- **说人话**，禁 AI 化套话（赋能/打通/闭环/抢占心智 等）
- gmv 字段统一 `gmv_paid`（用户支付金额）
- **优先用 mvp_sku 真实字段**（W4-B 切片 12 起 specifications/price_min/owner_selling_points 全抓全），不让老板手报已有信息

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

KE 容器 lifespan 启动期起 4 个 asyncio loop，每小时唤醒一次检查 last_run。
失败容忍（log warning 不挂），容器停就停（不是 SLA 服务）。

| cron | 周期 | 动作 | 写文件 |
|---|---|---|---|
| `weekly_self_review` | 7 天 | 调 `agent_self_review(period_days=7)` | `data/agent_state/weekly_review.md` |
| `daily_pulse` | 1 天 | 调 `fetch_compass_store_daily` + `fetch_yuntu_brand_mind` | `data/agent_state/daily_pulse.md` |
| `dynamic_block_refresh` | 7 天 | 调 `agent_meta._refresh_impl`（绕 require_approval）| `data/agent_state/dynamic_block.md` |
| `feedback_digest` | 7 天 | 聚类负反馈(消息级+工具级)+ 30 天投后数据 → 改进草稿（只聚类不自动改） | `data/agent_state/feedback_digest.md` |

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

## omni 三端协同 (W6 multi-device)

老板要在 Win 主机 / Mac / OPPO Find N6 三端协同使用 omni。基建落地于 2026-05-17:

- **后端**: nginx 已绑 `0.0.0.0:80` (docker-compose.yml),其他服务保持 127.0.0.1 经 nginx 反代
- **前端 PWA**: `/chat` 路由加了 manifest.json + icon SVG + viewport meta + appleWebApp meta — OPPO Chrome 可"添加到主屏",带启动屏 + 全屏 + safe-area 适配
- **/chat 移动端响应式**: ChatLayout 加 hamburger button + mobileNavOpen state; SessionList 小屏抽屉模式 (`fixed translate-x` 滑入,backdrop click 关); InputBar `paddingBottom: max(0.75rem, env(safe-area-inset-bottom))` 适配全面屏 home indicator
- **长任务推企业微信**: KE 新增 `POST /api/v1/notify/task-done` endpoint (不走 Human Gate); frontend ws-handler 在 Claude Code task_done 时 fire-and-forget fetch 推送 (>=10s 任务才推,避免骚扰); 没配 `WECOM_WEBHOOKS` 时返 `skipped:true` 不影响业务
- **网络层**: 老板装 Tailscale (Win + Mac + OPPO 三端同账号),走 100.x.x.x tailnet IP P2P 加密,0 公网暴露

**老板话术触发**:
- "我要在路上用 omni" → 文档 `docs/multi-device/setup.md` (Tailscale 装机 + Mac DMG + OPPO PWA 全步骤)
- "怎么配企业微信推送" → `WECOM_WEBHOOKS=task_done=https://qyapi.weixin.qq.com/...` 写进 KE .env 重启
- "推送 endpoint 有问题" → `curl http://localhost:8002/api/v1/notify/health` 看 channels_configured 是否非空

**老板手动步骤** (我代不了):
- Tailscale 注册 + 三端装客户端
- 企业微信群机器人申请 webhook URL
- Mac 上 `npm run pack:mac` 出 DMG + 装 Applications
- OPPO Chrome "添加到主屏"

实现:
- `frontend/public/manifest.json` + `icon{,-192,-512}.svg`
- `frontend/src/app/layout.tsx` (metadata.manifest + viewport export)
- `frontend/src/components/agent-chat/{ChatLayout,SessionList,InputBar}.tsx` (移动端响应式)
- `frontend/src/lib/agent-chat/ws-handler.ts` (task_done fetch notify endpoint)
- `services/knowledge-engine/app/routers/notify.py` (POST /api/v1/notify/task-done + human-gate + health)
- `docker-compose.yml` nginx 端口绑定改 `0.0.0.0`
- `docs/multi-device/setup.md` (装机指南)

## 反馈飞轮地基(Phase A · 2026-05-28)

老板自用 omni 要"越用越聪明",4 层架构(可观测/可反馈/可归因/可改进)。Phase A 补齐**第 2 层"可反馈"**:客户端到 DB 的反馈通路。不引强化学习(API 模型改不了权重),走 **harness engineering / compound AI system / data flywheel** 这条路。

### 4 条铁律(任何新 tool / 新功能都必须遵守,自动并入飞轮)

| 铁律 | 怎么强制 | 状态 |
|---|---|---|
| A. 必须留痕 | tool 函数加 `@tool_with_audit` → 自动落 `mcp.tool_calls` | ✅ 框架强制 |
| B. 必须返 trace | LLM tool 返 `{trace: {final_prompt, params, cost_estimate}}` | ✅ doctor 检查 |
| C. prompt 外置 | 放 `config/prompts/<tool>.{system,user}.md`,不硬编码 | ✅ prompts.render() |
| D. 必须有反馈出口 | desktop MessageBubble 已**自动**给 AI 消息加 👍👎,不用各功能各自实现 | ✅ Phase A 补齐 |

### 数据流

- **消息级反馈**(老板说"这条 AI 回复不行"):desktop MessageBubble 👍👎 → IPC `rate-message` → main process fetch → KE `POST /api/v1/mcp/messages/rate` → tool `rate_message` → `mcp.message_feedback` 表
- **tool 级反馈**(老板说"这个 tool 调错了"):web `/agent-log` 👍👎🔁 → `rate_tool_call`(MCP)→ `mcp.tool_calls.user_rating + rating_category`;desktop 也通了 `rate-tool-call` IPC channel 但 UI 暂未挂(Phase 后续做 ToolCallChip 反馈)

### 表 + tool

- migration 031:
  - 新 `mcp.message_feedback`(`session_id+message_id` UNIQUE,覆盖更新;`category` 7 类 + `message_text_snapshot` ≤4KB + `tool_use_ids[]` 反查涉及的 tool)
  - `mcp.tool_calls` 加 `rating_category` 归因字段
- MCP tool:
  - `rate_message(session_id, message_id, rating, category?, note?, message_text_snapshot?, tool_use_ids?, client?)` — `session_id` 自动兼容 uuid / claude_session_id 文本
  - `rate_tool_call(call_id, rating, note?, category?)` — 加 `category` 可空入参向后兼容

### 反馈分类 7 类(`category` 字段集合)

- `prompt_bad` 提示词不对
- `tradeoff_wrong` 取舍/重点错了
- `factual_error` 事实/数据错
- `tone_off` 语气/风格不对
- `wrong_tool` 调错 tool / 漏调 tool
- `incomplete` 答得不完整
- `other` 其他

### 老板话术 → Claude 应做

| 老板说 | Claude 应做 |
|---|---|
| "这条回复不行" / "答错了" | 提醒老板点桌面 app 消息右下角 👎 选分类(实际飞轮要的就是这数据) |
| "看一下最近的负反馈" | SQL `SELECT category, count(*), array_agg(distinct substr(message_text_snapshot,1,80)) FROM mcp.message_feedback WHERE rating='bad' AND created_at > now()-interval '7 days' GROUP BY category` |
| "为啥老答不好 X" | 按 category 聚类 SQL + 看 message_text_snapshot 找模式 |
| "客户端没反馈入口" | 已有(Phase A 已补);hover 消息右下角出现 👍👎 |

### 后续 Phase(等老板拍板)

- **Phase B**:负反馈聚类 → prompt 改进建议草稿(tool 自进化)
- **Phase C**:codify_pattern_to_skill cron 真触发 + skill 评分入库(skill/sop 自进化)
- **Phase D**:sku-pipeline 各 step 加 run 级评分(pipeline 自进化)
- **Phase E**:web `/agent-log` 加 7 天趋势仪表盘 + 模式归因日志

### 实现

- `migrations/031_feedback_flywheel.sql`
- `services/knowledge-engine/app/services/agent_log_service.py`(rate_message_logic + _resolve_session_uuid)
- `services/knowledge-engine/app/mcp/tools/feedback.py`(rate_message tool + rate_tool_call 加 category)
- `services/knowledge-engine/app/routers/mcp_tool_calls.py`(POST `/api/v1/mcp/messages/rate`)
- `services/knowledge-engine/app/schemas/mcp_tool_calls.py`(MessageRateRequest)
- `services/knowledge-engine/app/mcp/doctor.py`(wanted set 加 `rate_message`,总数 54)
- omni-desktop:`src/shared/{ipc-channels,types}.ts` + `src/main/ipc-handler.ts` + `src/preload/preload.ts` + `src/renderer/components/MessageFeedback.tsx`(新)+ `MessageBubble.tsx` + `MessageStream.tsx`

## Bug 记忆库 + 客户端日志(Phase A+/A++ · 2026-05-28)

老板痛点:**bug 第一次修了第二次还要修**(根因:omni 没有 agent 长期 bug 记忆 + 没有客户端运行日志留痕)。Phase A+/A++ 补齐第 3 层(可归因)+ 第 4 层(可改进)的地基。

### 数据流

```
desktop 任何操作
    ↓
[IPC handler 包装层 wrapHandler] —— 所有 28 个 IPC 自动落 client_logs
[main process uncaughtException/unhandledRejection] —— Electron 异常全捕获
[claude-runner spawn stderr/exit] —— Claude CLI 子进程异常全捕获
    ↓
mcp.client_logs(批量 20 条 / 5s 推 KE,丢弃容忍)
    ↓
老板按 🐛 报 bug → mcp.bug_memory(自动 dedupe 同 title 相似 ≥0.6 Jaccard,occurrences++)
    ↓
下次 spawn claude 时 → 拉 GET /api/v1/mcp/bugs/inject-summary(60s 缓存)
    ↓
--append-system-prompt "已知未修 bug 列表" → Claude 主动避坑
    ↓
老板修了 → PATCH bugs/{id} fix_applied=true → 退出 inject 池
```

### 表(migration 032)

- `mcp.client_logs` — 客户端所有运行时事件留痕(IPC/fetch/spawn/error/crash/startup);severity 5 级;`user_marked_bug` 标位关联 `bug_memory_id`
- `mcp.bug_memory` — bug 长期记忆;`fix_applied` 标位决定是否进入启动期 inject;`occurrences` 自动累计;`tags` 数组(`ui/ipc/ke/claude/electron/data/other`)

### 4 个 MCP tool(全 @tool_with_audit · require_approval=False)

- `log_client_event(events)` 批量记客户端事件
- `report_bug(title, symptom, ...)` 一键报 bug,自动 dedupe
- `list_bugs(unfixed_only?, tags?)` 拉 bug 列表
- `update_bug(bug_id, fix_applied?, ...)` 标修复/补根因/补 fix_recipe

### 5 个 REST endpoint(`mcp_tool_calls.py` 同级新 router `bug_memory.py`)

- `POST /api/v1/mcp/client-logs/batch`
- `POST /api/v1/mcp/bugs` + `GET /api/v1/mcp/bugs` + `PATCH /api/v1/mcp/bugs/{id}`
- `GET /api/v1/mcp/bugs/inject-summary` — desktop spawn 时拉,渲染成 system prompt 注入文本(≤2000 字符)

### 老板话术 → Claude 应做

| 老板说 | Claude 应做 |
|---|---|
| "这又出 bug 了" / "记录这个问题" | 调 `report_bug(title, symptom, ...)`,deduped 看是不是老 bug |
| "看看还有哪些 bug 没修" | 调 `list_bugs(unfixed_only=True)` |
| "bug-X 修了" / "这个标记已修" | 调 `update_bug(bug_id, fix_applied=True)` |
| "最近客户端有啥异常" | SQL `SELECT severity, channel, count(*) FROM mcp.client_logs WHERE created_at > now()-interval '1 day' AND severity IN ('warn','error','critical') GROUP BY severity, channel` |
| "bug 库重复太多怎么办" | dedupe 已自动(Jaccard ≥0.6 同 30 天内合并 occurrences++);不够准就改 service `_dedup_score_threshold` |

### omni-desktop 关键约定

- **所有 ipcMain.handle 必须走 wrapHandler**(IPC 调用自动落 client_logs)— 加新 IPC 必须包,28/28 已覆盖
- **SessionManager.spawn() 是 async**(返 Promise) — 调用方 await
- **claude-runner spawn 60s 缓存 bug summary** — 高频 send_prompt 不打 KE,但新 bug 60s 内能进 Claude 视野
- **fix_applied=true 的 bug 不再 inject** — 标修后退池,避免 system prompt 膨胀

### 实现

- `migrations/032_bug_memory_and_logs.sql`(2 表 + 索引 + FK)
- `services/knowledge-engine/app/services/bug_memory_service.py`(5 个 async 函数 + dedupe Jaccard 算法)
- `services/knowledge-engine/app/mcp/tools/bug_memory.py`(4 个 MCP tool)
- `services/knowledge-engine/app/routers/bug_memory.py`(5 个 REST endpoint)
- `services/knowledge-engine/app/mcp/server.py` + `main.py`(import + router 挂载)
- `services/knowledge-engine/app/mcp/doctor.py`(wanted set 加 4 个,总数 58)
- omni-desktop:
  - `src/main/client-logger.ts`(新,buffer 20/5s)
  - `src/renderer/components/{BugReportButton,BugLibraryModal}.tsx`(新)
  - `src/main/ipc-handler.ts`(wrapHandler 包装层 + 3 个 bug handler)
  - `src/main/claude-runner.ts`(fetchBugInjectSummary 60s 缓存 + --append-system-prompt 注入)
  - `src/main/session-manager.ts`(spawn 改 async)
  - `src/main/main.ts`(uncaughtException/unhandledRejection + startup event + beforeExit flush)
  - `src/main/{http-server,resume-scheduler}.ts`(await mgr.spawn)
  - `src/preload/preload.ts` + `src/shared/{ipc-channels,types}.ts`
  - `src/renderer/components/{MessageBubble,ToolCallChip,MessageStream,Sidebar,ChatLayout}.tsx`(挂入口)

### 后续 Phase

A+/A++ 是地基,数据攒起来后开 B/C/D/E:
- **Phase B**:负反馈聚类 → prompt 改进建议草稿(tool 自进化)
- **Phase C**:codify_pattern_to_skill cron 真触发 + skill 评分(skill/sop 自进化)
- **Phase D**:sku-pipeline 各 step 加 run 级评分(pipeline 自进化)
- **Phase E**:web `/agent-log` 加 7 天趋势 + bug 解决率仪表盘 + 模式归因日志

## W1 切片：检索增强 + 投后回传闭环 + 飞轮 Phase B + 工具反馈（2026-05-29）

老板自用"越用越聪明且有记录"四闭环补齐。本切片落地四块：

### 1. 检索增强（豪华 LangGraph 组件下放 agent 路）
检索两条路：豪华 `rag_query` LangGraph（HyDE/子查询/重排/CRAG，仅 web `/chat` 问答用）vs
简配 `retrieve_multi_kb`（agent 的 `search_kb`/`gather_brief_context`/`query_template_chunks` 走这条，原本只裸召回）。
本次把**交叉编码重排 + HyDE + 上下文窗口扩展**做成 `retrieve_multi_kb` 的可选开关（默认关，零影响现有调用）：
- `search_kb`：默认开 `rerank`（HyDE/window opt-in）
- `gather_brief_context`：默认开 `rerank + context_window`（出 brief 质量路径），`use_hyde` opt-in
- HyDE/重排**整链只跑一次**（HyDE 假设答案跟 KB 无关 → 生成一次复用到每 KB）
- 实现：`rag_chain.py`（retrieve_only 加 precomputed_embedding；retrieve_multi_kb 加 rerank/use_hyde/context_window + _mk 透传 document_id/chunk_index）

### 2. KB chunk_size 旋钮 + 空块兜底
- `kb_upload_doc(chunk_size=, chunk_overlap=)` 穿参到切块（人群/5A KB 想"1 chunk=1 完整人群画像"传更大值，重灌该 KB）。默认仍 settings 768。
- ingestion 加非空过滤（"17 空 chunks"历史问题兜底；现库已 0 空块）
- 实现：`ingestion.py`（submit_ingestion_task→_guarded_pipeline→_run_pipeline 穿 chunk_size/overlap）

### 3. 投后 ad_metrics 回传闭环（phase D）
`pipeline.assets.ad_metrics`（migration 021 已有字段 + `v_asset_full_lineage` 视图）此前只有读侧、缺写侧。本次补：
- 3 tool：`record_ad_metrics` / `pipeline_get_asset_lineage` / `pipeline_list_asset_performance`（见上"投后回传闭环"）
- 定位三选一（asset_id > external_video_id > external_creative_id），jsonb `||` 合并可多次累积回传
- 实现：`pipeline_lineage.py`（record_ad_metrics/get_asset_lineage/list_asset_performance）+ `pipeline.py`（3 tool）

### 4. 飞轮 Phase B + 工具级反馈
- **feedback_digest cron**（见 cron 表）：每周聚类消息级负反馈(7 类) + 工具级负反馈(tool×分类) + 30 天投后数据，写改进草稿。**只聚类不自动改 prompt**（决定权留老板）。实现 `cron.py` + `main.py`（注册第 4 loop）
- **桌面工具级 👍👎**：`mcp.tool_calls` 没存 tool_use_id 也无 session 链 → 新 `POST /api/v1/mcp/tool-calls/rate-recent`**按 tool_name 取最近一条**解析 call_id（单人场景：评的就是刚看到那条）。写 `user_rating+rating_category` → feedback_digest 能聚类。实现：KE `mcp_tool_calls.py`(router)+`schemas/mcp_tool_calls.py`(RateRecentRequest)；omni-desktop `ToolFeedback.tsx`(新)+`ToolCallChip.tsx`(挂入)+`ipc-handler.ts`(改调 rate-recent)+`shared/types.ts`(IpcRateToolCallArg 改 tool_name)

四闭环现状：bug 避坑(原有) + 投后数据→血缘(本次) + 负反馈+投后→周报草稿(本次) + 工具级反馈→聚类(本次)。**数据全流进来，digest 周摊给老板拍板改 prompt/skill**（自动收集 + 人工拍板）。

**KB-prompt 写法对照**：`docs/kb-prompt-guide.md`（写新"结合 KB 输出/检索"的 prompt 前先看，复用 gather_brief_context 管线 + generate_brief/audience_match/selling_points_matrix 范例）。

doctor 总数 58 → **61**（投后 3 tool）。

**注意**：桌面侧改动（工具反馈 + 之前 DevTools/消息ID/resume-scheduler 修复）要 `npm run build` 重新打包桌面 app 才生效（KE 改动已随容器重启生效）。
