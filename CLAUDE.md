# omni-vibe Claude Code 指令

> 这文件是给 Claude Code（agent 主大脑）看的，不是产品文档。
> **施工历史 / 实现文件清单 / doctor 计数流水账 / 实测踩坑 / 数据流图 → 见 `docs/build-log.md`**（不进 agent 上下文，要追溯时翻档）。

## omni MCP server

omni 暴露 **78 个 tool**。以 `services/knowledge-engine/app/mcp/doctor.py` 的 `wanted` 集为权威清单（自检 `all 78 ok`）；实现见 `services/knowledge-engine/app/mcp/tools/`。

- 查询：`list_skus`, `get_sku`, `list_kbs`, `search_kb`, `list_briefs`, `query_costs`
- 算账：`compute_margin`
- 编排辅助：`gather_brief_context`
- 生成（旧链，无血缘）：`generate_brief`, `generate_image`, `generate_video`, `generate_image_compare`
- sku-pipeline LLM：`generate_selling_points_matrix`（step 2）, `generate_audience_match`（step 3）, `generate_audience_pack`（step 4，phase B）, `generate_keyword_pack`（500 词扩展，phase B+）, `generate_creative_pack`（step 5 创意素材 6 类，phase C）
- sku-pipeline 出片（新链，挂血缘，见下"新旧两条出片链分流"）：`generate_storyboard_images`（step 6 分镜图，挂 pipeline.assets）, `generate_character_sheets`（step 6.5 角色定妆白底像锁脸）, `generate_video_segments`（step 7 视频段：分镜图当 first_frame + character_sheet 锁脸）
- 真人视频（绕 Seedance content_sensitive）：`realman_create_avatar`, `realman_generate_portrait_video`, `generate_video_anchor`（t2v 模式角色锚点）
- 反推故事板（直调 Gemini Files API）：`reverse_storyboard_video`（视频→可喂回 AI 的 image/video i2v/video t2v 三类 prompt 包）
- KB 写入：`kb_upload_doc`, `kb_set_role`
- 抓数：`fetch_compass_*` (3), `fetch_yuntu_5a`, `fetch_yuntu_brand_mind`
- 通用：`summarize_text`, `parse_long_doc_with_gemini`, `query_template_chunks`
- Agent 进化：`rate_tool_call`, `agent_self_review`, `codify_pattern_to_skill`, `refresh_project_context`
- 反馈飞轮（migration 031）：`rate_message`（消息级 👍👎 入 mcp.message_feedback）
- Bug 记忆库 + 客户端日志（migration 032）：`log_client_event`（批量记客户端运行事件）, `report_bug`（一键报 bug，自动 dedupe）, `list_bugs`（拉 bug 列表）, `update_bug`（标修复/补根因）
- 竞品调研（淘宝）：`competitor_search`（搜词抓前 50 榜单 + 相关性过滤）, `competitor_decompose`（主图/详情页拆卖点/构图/配色/设计/内容 5 维度）
- 阶段0 L0-2 成本闸：`query_monthly_spend`（omni 自身月度运行成本 + 软上限超额检测）
- 诊断官（§6.2）：`diagnose`（content 聚类两路反馈 / analysis 聚类趋势异动出《改进提议》，R-14 分层/R-15 样本量/R-20 生命周期，只提议不碰开关）, `list_proposals`（看待办提议+消化率）, `resolve_proposal`（三态 accept/ignore=不再提醒同类/snooze）, `explain_anomaly`（解释某条趋势异动：分层归因+近28天序列）, `query_metric_trend`（某指标近N天序列+基线mean/std）
- W4 加分：`save_decision`, `schedule_observation`, `send_wecom_message`, `dy_publish_creative`
- 字典查询：`list_product_prices`（工厂出厂价）, `list_channel_fees`（渠道扣点）
- 链路血缘（W4-B 切片 14.3 phase A）：`pipeline_list_matrix_runs`, `pipeline_get_matrix_run`, `pipeline_list_audience_runs`, `pipeline_get_audience_run`, `pipeline_list_audience_records`, `pipeline_get_audience_record`, `pipeline_adopt`
- 投后回传闭环：`record_ad_metrics`（测试投放后把 ROI/GMV/完播率写回素材血缘）, `pipeline_get_asset_lineage`（按 asset 反查 SKU/卖点/人群/脚本全链路）, `pipeline_list_asset_performance`（"哪套内容真带货"榜）
- 三平台实时取数底座（经 scout-agent）：`platform_fetch`（单端点真取数）, `platform_batch_fetch`（一会话连打多端点）, `platform_list_endpoints`（检索端点目录）, `platform_auth_status`（三平台 cookies 有效性）
- 落库桥：`ingest_platform_metrics`（手动触发一次全量落库——实时取 10 端点 → 抽取器落 95 指标 + 同行标杆 → upsert mvp_daily_metric + mvp_industry_benchmark；日级 cron 也自动跑）
- 综合经营分析 + 临时问数（§6 分析半）：`generate_business_analysis`（读 mvp_daily_metric 近 N 天序列 + mvp_industry_benchmark 同行 + mvp_anomaly 异动 → R-14 强制分层《综合经营分析》：观察到的 vs 可能的原因；按 face=owner 经营诊断 / operator 投放选品建议两面分别出；确定性为主、polish=True 可选 LLM 润色过 R-14）, `query_metric_nl`（口语问句 → metric_name+时间窗+维度 → 查 mvp_daily_metric 返序列+简述；确定性不归因，覆盖已落库 95 指标）
- 人群包投前诊断 + 提纯（方法论沉淀）：`diagnose_audience_pack`（候选包画像 vs 行业 A4 真需求标尺 → 逐维度看方向不算总相似分 → 投前诊断卡：价值维正向偏离/购买行为软硬/需求重叠真需求指纹/身份维差异不计 → 漏斗定位 + 内容策略定调 + **提纯优先级阶梯施工单**（不限刀数、按漏斗定位排序、每刀标 ✅非电商/⚠电商 资格 + 预计收窄力度 强/中/弱（粗估自画像占比·非云图真值，想快掉一个量级先挑「强」刀）——⚠电商刀只能上品牌广告不能上非品牌广告；老板一刀一刀切看云图真实覆盖人数、不满意重导出做二次提纯）；确定性为主、polish=True 巨量云图 KB grounding LLM 叙事过 R-14；详见下「人群包投前诊断」节）
- 巨量云图标签体系确定性查询：`query_yuntu_taxonomy`（圈包/提纯/答疑的标签 ground truth——总览两大入口+各维度 / dimension=某维度全量树 / search=某标签的真实层级路径+勾选菜单 / section=字段全集·行业特色·固定清单·提纯三刀法；**回答标签体系问题优先调它，别去硬读 30k 大文件 v2 字典、别靠 lossy RAG**。数据源 config/audience 画像 CSV + dump v1 常量，确定性不截断不虚构）
- 写入（require_approval=True）：`record_cost`, `disable_cost_item`

## 工具路由总则（撞车消歧 · 选 skill/tool 前必读）

老板自用环境里 12 个业务 skill 跟 50+ 通用英文 skill 同池竞争，**最常见的错是把中文业务话术路由给通用英文 skill（copywriting / competitive-landscape / pricing-strategy / market-sizing / apify-* 等）→ 它们不调 omni 真实数据，凭空编卖点/价格（违反反幻觉）或调 omni 没接的后端空跑**。铁律：

- **元规则**：凡有对应业务 skill 的话术，**优先走业务 skill**，不走通用英文 marketing/strategy/finance skill，也别裸调底层 tool。业务话术 = 和田宽 / SKU / 酱油醋 / 调味品 / 店铺 / 人群包 / 竞品 / 经营。
- **写文案/脚本/直播话术/带货内容** → `script-writer`（**不走** copywriting/content-creator/social-content/copy-editing）
- **找卖点/产品力/差异化** → `selling-point-finder`（**不走** marketing-psychology/competitive-landscape）
- **竞品/对标/扒别人怎么做的** → `competitor-product-research`（**不走** competitive-landscape/apify-*/market-sizing）
- **成本/出厂价/利润/这单赚多少/定价** → `cost-luru`（**不走** pricing-strategy/startup-financial-*）
- **分析（按粒度分）**：句中有 SKU 号/名 → `product-analysis`（单 SKU 体检）；"今天/今日大盘/店铺日报" → `daily-store-pulse`；"经营/这个月/趋势/综合" → `generate_business_analysis`(owner/operator)；只问单指标数/走势 → `query_metric_nl`；"为啥异动/解释异常" → `explain_anomaly`，"最近反馈/趋势异动模式" → `diagnose(mode=analysis)`。（**不走** startup-metrics-framework/product-manager-toolkit）
- **取数（三层）**：要此刻实时真值 → `platform_fetch`（platform-data skill）；要结构化日报+异动判断 → `daily-store-pulse`；要已落库历史序列 → `query_metric_nl`（不触发抓取）。`fetch_compass_*`/`fetch_yuntu_*` 是读存量底层端点、日常话术别直点（除非 skill 内部调）。
- **人群包**：从 0 生成圈人策略 → `crowd-sop`；step4 圈包 SOP（有 audience_record_id）→ `generate_audience_pack`；**投前诊断/提纯一个已有包** → `diagnose_audience_pack`（audience-pack-diagnosis）。**"包"字 + 生成动词（圈/做/出/写一个…包、受众咋定、圈人策略）= 生成侧，不是诊断**（见下「诊断路由硬规则」的生成例外）。
- **出片**：正式出片挂血缘 → `generate_storyboard_images`/`generate_video_segments`；无血缘临时/试拍 → `generate_image`/`generate_video`；只要脚本 → `script-writer`；要成片/全链路（烧 token）→ `sku-pipeline`（明确要全链路才触发）。
- **标签体系 / 某标签在哪个维度 / 圈包提纯用哪些标签** → `query_yuntu_taxonomy`（确定性全量不截断），**别用** `search_kb` RAG（只返碎片）。
- **禁**：`brainstorming`/`using-superpowers`/`test-driven-development` 等工程元 skill **不要**在业务话术（出片/脚本/人群包/分析/成本）上触发，直接进对应业务 skill。

> 这张总则是「老板说→走哪个」的唯一权威；下面各 section 的细表只是它的展开。新增/改 skill 后回这里补一行。

## 新旧两条出片链分流

sku-pipeline 出图/出视频有两条链，**进 pipeline（要血缘、要投后回溯）默认走新链**：

| 链 | tool | 血缘 | 落库 | 投后回溯 | 何时用 |
|---|---|---|---|---|---|
| **旧链** | `generate_image` / `generate_video` | 无 | 不挂 pipeline.assets | 不可回溯 | 无血缘的临时/兜底产物（老板临时要张图、单测、一次性试拍）——一次性产物，不进正式链路 |
| **新链** | `generate_storyboard_images`（step 6）/ `generate_character_sheets`（step 6.5）/ `generate_video_segments`（step 7） | 有，全 denorm sku_id | 挂 `pipeline.assets`（ad_metrics 投后回传字段就在这表） | 可（`pipeline_get_asset_lineage` 一句 SQL 反查 SKU/卖点/人群/脚本全链路 + `v_asset_full_lineage` 视图） | sku-pipeline 正式出片，要投后 `record_ad_metrics` 回传 ROI/GMV 反查"哪套内容真带货" |

**默认约定**：跑 sku-pipeline 正式出片 → 走**新链**，产物自动挂血缘可投后回溯。旧链是**无血缘的临时/兜底**通路（仍可正常调，没弃用），只在不需要进正式链路的一次性场景用。

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
audience_run_id + matrix_run_id + sku_id 全 denorm。多版本（重跑 = 新行 + parent_pack_id 串前后）。

## sku-pipeline 关键词扩展（W4-B 切片 14.3 phase B+）

`generate_keyword_pack(seed_keywords, target_count=500, sku_id?, audience_record_id?,
audience_pack_id?, extra_context?)` —— 输入种子词，输出 N 个**纯文本一行一词无标点**
的关键词（向量近邻词，**不是 SKU 商品维度词、不是人群属性词、不是元话题词**）。

**用途**：导入「云图 → 数据工厂 → 关键词夹 → 新建关键词包」 → 标签工厂转成
人群标签 → 回自定义人群引用 → 推千川。**不是直接进千川计划关键词定向**。

落库 `pipeline.keyword_packs`（migration 022），可挂 sku/audience_record/audience_pack。
后处理 `_clean_keyword_pack` 强制清掉标点/数字/重复，保证格式纯净。

## sku-pipeline step 5 创意素材（W4-B 切片 14.4 phase C）

`generate_creative_pack(kind, sku_id?, audience_record_id?, audience_pack_id?, extra_context?)`
—— 1 个 tool 路由 6 类素材，按 `kind` 选对应 system prompt
（`config/prompts/creative_pack.<kind>.system.md` 各 1 套，user 共用 1 套）。

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

**链路落库**：跑完落 `pipeline.scripts`（migration 023 加 `kind` 字段 + 弹性挂改 nullable）。多版本（同 sku+kind 的 version 自增 + parent_script_id 串前后）。

**老板话术 → tool**：
- "给 sku-X 写个种草脚本" → `generate_creative_pack(kind='video_planting', audience_record_id=...)`
- "给 X 出收割图文" → `generate_creative_pack(kind='graphic_harvest', sku_id='X')`
- "给 X 设计 5 张主图" → `generate_creative_pack(kind='product_main_image', sku_id='X')`
- "给 X 写详情页文案" → `generate_creative_pack(kind='product_detail_page', audience_record_id=...)`

**前端 /sku-pipeline step 5 tab**：左侧选模式（record / sku）+ 6 个 kind chip + extra_context；右侧输出 markdown + 复制 + 下载 .md + trace 折叠。pack 模式 v1 暂未开放。

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
- **优先用 mvp_sku 真实字段**（specifications/price_min/owner_selling_points 全抓全），不让老板手报已有信息

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
失败容忍（log warning 不挂），容器停就停（不是 SLA 服务）。实现 `app/mcp/cron.py`。

| cron | 周期 | 动作 | 写文件 |
|---|---|---|---|
| `weekly_self_review` | 7 天 | 调 `agent_self_review(period_days=7)` | `data/agent_state/weekly_review.md` |
| `daily_pulse` | 1 天 | 调 `fetch_compass_store_daily` + `fetch_yuntu_brand_mind` | `data/agent_state/daily_pulse.md` |
| `dynamic_block_refresh` | 7 天 | 调 `agent_meta._refresh_impl`（绕 require_approval）| `data/agent_state/dynamic_block.md` |
| `feedback_digest` | 7 天 | 聚类负反馈(消息级+工具级)+ 30 天投后数据 → 改进草稿（只聚类不自动改）**+ 调 diagnose 把提议结构化入库（进 /insights）** | `data/agent_state/feedback_digest.md` + `mcp.improvement_proposals` |

每个 cron 各一个 `last_*.txt` 文件持久化时间戳。**老板手动**把 dynamic_block.md
新内容粘到本文件 `<!-- omni-dynamic:start ... :end -->` marker 之间（cron 不
自动改 CLAUDE.md，因为 CLAUDE.md 入 git 老板要审）。

## 已知约束

- 不调 `run_sku_orch` —— 没这个 tool，编排靠对话
- LLM tool 必返 `trace` 字段，老板要看 final_prompt 才能调 prompt 重跑
- video 多段并发跑（asyncio.gather），typically 30-60s 每段；并发后总时间 ≈ 单段
- W2 5 个 LLM tool 不走 Human Gate；W3a 加的 `record_cost` / `disable_cost_item` 走 Gate（CLI 批）
- cron 跑数据来自 DB（scout-agent 最近一次 runbook 抓的）；cron 本身**不**主动跑 scout runbook（罗盘 cookie 浮动，runbook 老板手动跑）

## 调试常用命令

- **容器内自检**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"` —— 应输出 `all 78 ok` 的 tool 列表
- **审计表**：`docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT tool_name, status, duration_ms FROM mcp.tool_calls ORDER BY created_at DESC LIMIT 20"`
- **ai-provider-hub 状态**：`curl http://localhost:8001/api/v1/ai/providers`
- **Human Gate 批/驳**（W3a）：
  - 列待批：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve list`
  - 批：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <short_id> --note "OK"`
  - 驳：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve reject <short_id> --note "原因"`
  - 持续看：`docker exec -it omni-knowledge-engine python -m app.mcp.cli_approve tail`（Ctrl-C 退）
- **prompt 模板列表**：`docker exec omni-knowledge-engine python -c 'from app.mcp import prompts; [print(t) for t in prompts.list_templates()]'`
- **CSV 导入 cost_items**：`docker exec omni-knowledge-engine python /app/scripts/import_costs.py /app/scripts/cost_template.csv`（先 `--dry-run` 预演）

## omni 三端协同（W6 multi-device）

老板要在 Win 主机 / Mac / OPPO Find N6 三端协同使用 omni。基建：nginx 绑 `0.0.0.0:80` 经反代；`/chat` PWA 可"添加到主屏"（移动端响应式 + safe-area）；长任务推企业微信（KE `POST /api/v1/notify/task-done`，>=10s 才推）；网络层 Tailscale 三端同账号走 tailnet P2P 加密 0 公网暴露。实现清单见 `docs/build-log.md`。

**老板话术触发**:
- "我要在路上用 omni" → 文档 `docs/multi-device/setup.md`（Tailscale 装机 + Mac DMG + OPPO PWA 全步骤）
- "怎么配企业微信推送" → `WECOM_WEBHOOKS=task_done=https://qyapi.weixin.qq.com/...` 写进 KE .env 重启
- "推送 endpoint 有问题" → `curl http://localhost:8002/api/v1/notify/health` 看 channels_configured 是否非空

**老板手动步骤**（我代不了）：Tailscale 注册 + 三端装客户端；企业微信群机器人申请 webhook；Mac `npm run pack:mac` 出 DMG；OPPO Chrome "添加到主屏"。

## 反馈飞轮（Phase A · 4 层架构）

老板自用 omni 要"越用越聪明"，4 层架构（可观测/可反馈/可归因/可改进）。不引强化学习（API 模型改不了权重），走 harness engineering / data flywheel。

**4 条铁律**（任何新 tool / 新功能都必须遵守，自动并入飞轮）：

| 铁律 | 怎么强制 |
|---|---|
| A. 必须留痕 | tool 函数加 `@tool_with_audit` → 自动落 `mcp.tool_calls` |
| B. 必须返 trace | LLM tool 返 `{trace: {final_prompt, params, cost_estimate}}`（doctor 检查）|
| C. prompt 外置 | 放 `config/prompts/<tool>.{system,user}.md`，不硬编码（prompts.render()）|
| D. 必须有反馈出口 | desktop MessageBubble 自动给 AI 消息加 👍👎，不用各功能各自实现 |

**反馈分类 7 类**（`category` 字段）：`prompt_bad` 提示词不对 / `tradeoff_wrong` 取舍重点错 / `factual_error` 事实数据错 / `tone_off` 语气风格不对 / `wrong_tool` 调错/漏调 tool / `incomplete` 答得不完整 / `other`。

**数据通路**：消息级 👍👎（desktop MessageBubble → IPC `rate-message` → `rate_message` tool → `mcp.message_feedback`）；工具级 👍👎（desktop ToolCallChip → `POST /api/v1/mcp/tool-calls/rate-recent` 按 tool_name 取最近一条 → `mcp.tool_calls.user_rating+rating_category`）。每周 `feedback_digest` cron 聚类 + 诊断官结构化入库（只聚类不自动改，决定权留老板）。

| 老板说 | Claude 应做 |
|---|---|
| "这条回复不行" / "答错了" | 提醒老板点桌面 app 消息右下角 👎 选分类（飞轮要的就是这数据）|
| "看一下最近的负反馈" | SQL `SELECT category, count(*), array_agg(distinct substr(message_text_snapshot,1,80)) FROM mcp.message_feedback WHERE rating='bad' AND created_at > now()-interval '7 days' GROUP BY category` |
| "为啥老答不好 X" | 按 category 聚类 SQL + 看 message_text_snapshot 找模式 |

## Bug 记忆库 + 客户端日志（migration 032）

老板痛点：**bug 第一次修了第二次还要修**（根因：没有 agent 长期 bug 记忆 + 没有客户端运行日志留痕）。

**数据流要点**：desktop 所有操作经 IPC `wrapHandler` / main process 异常捕获 / claude-runner spawn 异常 → 批量落 `mcp.client_logs`（20 条/5s，丢弃容忍）。老板按 🐛 报 bug → `mcp.bug_memory`（自动 dedupe，同 title Jaccard ≥0.6 同 30 天内合并 occurrences++）。下次 spawn claude 拉 `GET /api/v1/mcp/bugs/inject-summary`（60s 缓存）→ `--append-system-prompt "已知未修 bug 列表"` → Claude 主动避坑。`fix_applied=true` 退出 inject 池。

**4 个 MCP tool**（全 @tool_with_audit · require_approval=False）：`log_client_event(events)` / `report_bug(title, symptom, ...)` / `list_bugs(unfixed_only?, tags?)` / `update_bug(bug_id, fix_applied?, ...)`。tags：`ui/ipc/ke/claude/electron/data/other`。

**omni-desktop 关键约定**：
- **所有 ipcMain.handle 必须走 wrapHandler**（IPC 调用自动落 client_logs）——加新 IPC 必须包
- **SessionManager.spawn() 是 async**（返 Promise）——调用方 await
- claude-runner spawn 60s 缓存 bug summary；`fix_applied=true` 的 bug 不再 inject（避免 system prompt 膨胀）

| 老板说 | Claude 应做 |
|---|---|
| "这又出 bug 了" / "记录这个问题" | 调 `report_bug(title, symptom, ...)`，deduped 看是不是老 bug |
| "看看还有哪些 bug 没修" | 调 `list_bugs(unfixed_only=True)` |
| "bug-X 修了" / "这个标记已修" | 调 `update_bug(bug_id, fix_applied=True)` |
| "最近客户端有啥异常" | SQL `SELECT severity, channel, count(*) FROM mcp.client_logs WHERE created_at > now()-interval '1 day' AND severity IN ('warn','error','critical') GROUP BY severity, channel` |

## 检索增强 + KB 旋钮（W1 切片 · 2026-05-29）

- **检索增强**：agent 路（`search_kb`/`gather_brief_context`/`query_template_chunks`）走简配 `retrieve_multi_kb`，加了**交叉编码重排 + HyDE + 上下文窗口扩展**可选开关。`search_kb` 默认开 `rerank`；`gather_brief_context` 默认开 `rerank + context_window`（`use_hyde` opt-in）。HyDE/重排整链只跑一次复用到每 KB。（豪华 `rag_query` LangGraph 仅 web `/chat` 问答用。）
- **KB chunk_size 旋钮**：`kb_upload_doc(chunk_size=, chunk_overlap=)`（人群/5A KB 想"1 chunk=1 完整人群画像"传更大值重灌）。默认 settings 768。ingestion 已加非空过滤。
- **KB-prompt 写法对照**：写新"结合 KB 输出/检索"的 prompt 前先看 `docs/kb-prompt-guide.md`（复用 gather_brief_context 管线 + 范例）。

## 竞品调研：淘宝抓取 + 视觉拆解（2026-06-01）

`reverse_storyboard` 的"竞品镜像"：把别人淘宝的**主图/详情页**拆成卖点/构图/配色/设计/内容，反过来喂自己的 selling-point-finder / generate_creative_pack。范围：**两段式 · 只出 md 报告（不落库）· 搜索页显示价+月销**。话术触发走 skill `competitor-product-research`（每步停等反馈）。

- `competitor_search(query, top_n=50, platform='taobao', relevance_filter=True, headless?, max_pages=3)`
  —— 搜词 → scout-agent 抓前 N 卡片（标题/显示价/月销/店铺/链接/主图）→ LLM 相关性过滤 → markdown 榜单。老板挑要深拆的。
- `competitor_decompose(item_url? / item_urls?, focus_product?, headless?, max_main_images=6, max_detail_images=8, model?)`
  —— scout-agent 抓主图组+详情页长图（alicdn url）→ KE 下载转 base64 **data URI**（hub gemini chat 只把 `data:` 块转 inline_data）→ 多模态 gemini → 5 维度 md。一次最多 12 个。

**详情页 = 淘宝最硬的墙，`competitor_decompose` 三层兜底**：① 先试 scout `/taobao/detail_shots`（移动 H5 滚动截图喂视觉）② 被挡 → 退用**搜索主图**（传 `items` 带 main_image_url）拆 4 维度，"内容"标缺 ③ `local_images=["/host/Desktop/x.jpg",...]`：老板手动截详情页**100% 可靠全 5 维**。**调用优先传 `items`；要真详情页用 `local_images`**。

**三个现实**（避免误判为 bug）：到手价≈搜索页显示价（可能券前/预估）；月销淘宝常隐藏（缺标 —）；选择器启发式可能要调几轮。**老板手动**：淘宝登录走 `POST /api/v1/scout/taobao/relogin` 扫码 → cookie 落 `sessions/taobao/`。抓取硬配方（headed+xvfb / storage_state / 国内 IP / `&page=N`）见记忆 [[project-taobao-scraping-recipe]] + `docs/build-log.md`。

## 诊断官·分析面趋势归因 + 问数（§6.2 + R-14 + R-15）

诊断官分析面（`diagnose(mode='analysis', platform='douyin')`）读近 N 天 `mvp_anomaly`，按 metric 聚合成提议，**全程确定性，归因走模板化映射不调 LLM**（R-14：LLM 最会编"逻辑自洽实则编造"的归因，所以归因按 metric/rule 查表）。强制分层：observation（客观相关，不含因果）/ hypothesis（模板化 `_ANALYSIS_METRIC_HYPOTHESIS` 查表，每条"假设 + 未排除混杂因子 + 要证实需对比 X"，禁"主因是 X"断言）/ R-15 样本量（n<5 标 preliminary 待验证）。落 `mcp.improvement_proposals` 复用 content mode 同基建。

2 个问数工具（确定性查询，query_costs 风格：@tool_with_audit、不返 trace、不走 Gate）：
- `explain_anomaly(anomaly_id)`：该异动 + 指标近 28 天序列 → 分层归因（observation/hypothesis/unaddressed_confounders/falsification + recent_series + baseline）。
- `query_metric_trend(metric_name, sku_id?, platform='douyin', days=28)`：指标近 days 天序列（sku_id 省略=同日聚合大盘）+ 基线 mean/std/min/max/latest。`mvp_daily_metric` 真实数据原样返回，不编造不归因。

REST（桌面经 IPC→http 调，与 tool 共用同一 service 禁漂移）：`GET /api/v1/mcp/explain-anomaly?anomaly_id=` + `GET /api/v1/mcp/metric-trend?metric_name=&sku_id=&platform=&days=`。

| 老板说 | Claude 应做 |
|---|---|
| "诊断一下 / 最近反馈啥模式 / 本周改进建议" | `diagnose`（content 反馈 / analysis 趋势）→ 看 `/insights` 改进建议 tab |
| "接受第 N 条 / 这条忽略别再提 / 先放放" | `resolve_proposal`（accept/ignore/snooze，或前端按钮）|
| "这月 omni 烧了多少 / 超预算没" | `query_monthly_spend`（软上限读 `OMNI_MONTHLY_SPEND_CAP_USD`，缺省回退 500）|
| "分析一下趋势 / 为啥指标掉了 / 看看异动" | `diagnose(mode='analysis')` |
| "为啥这条异动 / 解释下这个异常" | `explain_anomaly(anomaly_id)` |
| "看看 X 指标最近趋势 / gmv 走势" | `query_metric_trend(metric_name='X')` |

## 落库桥 + 综合经营分析（§6 分析半，2026-06-03）

### 落库桥
`ingest_platform_metrics()`（KE，require_approval=False）→ httpx 调 scout REST，实时取 10 端点 → 跑抽取器落 95 指标 + 同行标杆 → upsert 两表。全程纯加法、fail-open。触发三路：① MCP tool（老板"落库一次 / 把今天数据入库 / 刷新指标库"，需 cookies 有效先 `platform_auth_status` 查）② scout REST `POST /api/v1/scout/metrics/ingest` + `GET /metrics/series?metric=&days=` ③ scout scheduler 每天 09:00 自动跑（失败容忍）。一次全量约 metric 428 行 + benchmark 377 行。

### 共享契约（落库目标 + 哨兵 + 口径，**所有分析读取严格对齐**）
- `mvp_daily_metric(sku_id, date, metric_name, value, platform)`：全店行哨兵 `sku_id='_SHOP_'`、`platform='douyin'`（云图/罗盘/抖店同属抖音生态）；`UNIQUE(sku_id,date,metric_name)` upsert。series 端点落整段历史每天一行，snap 端点落今日一行（趋势靠 cron 日累积）。
- `mvp_industry_benchmark(date, category_id, metric_name, industry_avg, industry_top, shop_value, percentile, industry_rank)`，category_id `'14'`（"你 vs 同行"）。
- **口径**：罗盘金额「分」→ ÷100 元；rate/sov/占比 存原始 0-1；rank 越小越好。

### 综合经营分析 `generate_business_analysis(face, days=28, platform='douyin', polish=False, focus=None)`
读 `mvp_daily_metric` 序列 + `mvp_industry_benchmark` 同行 + `mvp_anomaly` 异动，**R-14 强制四段分层**：
- 一、**观察到的**：客观事实带数据（每指标最新值 / 窗口首尾 % / 后半段 vs 前半段环比 / vs 同行均值·分位·排名），**不含因果**。
- 二、**异动**：异动引擎检出的未处理/非预期异常（同 diagnose analysis 口径）。
- 三、**可能的原因**：模板化假设（`_match_analysis_hypothesis`，禁"主因是 X"，每条"假设 + 未排除混杂因子 + 要证实需对比 X"）。
- 四、**口径与样本量警示**：R-15 样本不足（序列点 <5）标待验证 / R-17 单平台抖音口径 / 缺数据指标。

**两面分别出**（`face`）：`owner`=经营诊断（北极星 gmv/buyer/转化/uv/体验分/行业排名/SOV + 同行分位）；`operator`=投放选品建议（5A 分层 A1-A5/新增/流失/排名 + 货品结构爆款/常规品占比 + 商品卡 + 搜索排名）。

`polish=False` 默认纯确定性零 token；`polish=True` 在确定性骨架之上跑 LLM 叙事层——把骨架当 **ground truth** 喂 hub，按外置提示词 `config/prompts/business_analysis.{system,user}.md`（命门·热加载可调）写成可读经营分析：允许把分散指标连成"形态"（相关性）、指出重点、给"待验证的下一步"，但**禁新增任何数值、禁伪因果**（观察/假设严格分层，假设必带"要证实需对比 X"），保留 R-15 警示，反 AI 腔。失败 fail-open 回退骨架（`narrated=False`）。`focus`=老板临时关注点（仅 polish 生效）。返回 `markdown` 叙事 + `sections`（桌面分层卡片下钻）+ `as_of`。

### 临时问数 `query_metric_nl(question, default_days=28, platform='douyin')`
口语问句 → 解析 `metric_name`（`metric_registry.resolve_metric`，空白不敏感）+ 时间窗 + 维度（含 'SKU-xxxx' → 该 SKU；否则全店 `_SHOP_`）→ 查 `mvp_daily_metric` 返**序列 + 一句话简述**（确定性，不调 LLM、不归因）。没听出指标 → 返 95 指标候选清单让老板再说清。

| 老板说 | Claude 应做 |
|---|---|
| "出一份经营分析 / 综合分析一下 / 这个月经营咋样" | `generate_business_analysis(face='owner')` |
| "投放选品建议 / 操盘手看一下 / 5A 货品结构咋样" | `generate_business_analysis(face='operator')` |
| "最近 gmv 多少 / 本月转化率走势 / 看下 SKU-X 近 7 天点击" | `query_metric_nl(question=原话)` |

## 人群包投前诊断 + 提纯（《和田宽人群包评估方法论》沉淀，2026-06-08）

老板痛点：和田宽**出厂价已 ≥ 竞品线上零售价，打不了价格战**，投放靠"做用户喜欢的内容 → 软植入 → 深度种草 → 收割"。所以做内容/投放**之前**必须判断一个候选人群包适不适合——这群"会被内容打动"的人必须是**真需求**。方法论备忘 + 两份说明书见 `docs/audience-pack/`。

> **⚠️ 「诊断」路由硬规则（两个工具别搞混，已多次踩坑——必须机械执行，不准凭感觉）**：
> 1. 句子里**只要出现下列任一**：`包` / `人群包` / `候选包` / `这个包` / `适不适合投` / `提纯` / `圈的人` / **任何包名（地域寻味人 / 行业A4 / diyu_xunwei / 候选包名…）** / **本轮带了 CSV 附件** → **一律直接调 `diagnose_audience_pack`**。**禁止反问、禁止走 `diagnose`（诊断官）、禁止说"无包字"**。先扫一遍整句再判，别只看"诊断"两个字。**⚠️生成侧例外**：句中同时含**生成动词**（圈/做/出/写/搞「一个…包」、"受众咋定"、"出个圈人策略"）→ 这是**生成意图、不是诊断**，走 `crowd-sop`（纯口头要策略）或 `generate_audience_pack`（有 audience_record_id），**不走 diagnose_audience_pack**。只有"诊断/提纯/适不适合投/太大了帮我切/缩量级"这类**评估已有包**的才走诊断。
> 2. 句子里**完全没有上述词**、只是「诊断一下 / 最近反馈啥模式 / 本周改进建议 / 趋势异动 / 为啥指标掉了」→ 才走 `diagnose`（诊断官）。
> 3. 真·两可（既无包名也无明确反馈/异动语境）→ **默认按人群包走 `diagnose_audience_pack`**（老板自用最高频是诊人群包），别反问。

### tool `diagnose_audience_pack(candidate, baseline='baseline_a4', with_purify_plan=True, polish=False, focus=None)`
读候选包画像 + 行业 A4 画像（`标签类型,标签,占比,tgi`，巨量引擎/云图人群分析导出），**确定性逐维度比对**（镜像 generate_business_analysis 的"确定性骨架 + 可选 polish"+ R-14 分层）。

**方法论主线铁律（确定性映射，不靠 LLM 编）——比对看方向，不算总相似分**：
- **价值维（付得起：消费力/城市层级/手机价位）** → 期望**正向偏离 A4 高端尾部**；贴近 A4 均值是**反的**（A4 大多价格敏感，恰是和田宽最打不动的人，要主动往高端偏）。
- **购买行为维（线上客单/购买频次）** → 比 A4 软 = **种草信号**（非扣分，定漏斗位）。
- **需求维（品类成交/品牌/抖音头条西瓜兴趣/触点）** → 期望**重叠 A4 真需求指纹**（品类锚 TGI 1300+ / 兴趣锚 220–280 / 触点锚 300–490），重叠高 = 真需求强。
- **身份维（八大消费群体/年龄/性别/职业/人生阶段/地域）** → **差异不计**（构成不同 ≠ 质量缺口，A4 是真需求标尺，不是模仿对象）。
- **噪音维（手机品牌/活跃用户）** → 忽略。
- → **漏斗定位**（种草型 / 即投收割型 / 价值流失·慎投）+ **内容策略定调** + 可选**《提纯施工单·优先级阶梯》**（**不限刀数、按漏斗定位排序**——种草型先非电商需求/内容刀、收割型先高客单/品类成交刀；每刀落到画像里**真实可勾的巨量云图标签** `数据工厂 → 维度 → 标签` + 标 **✅非电商/⚠电商** 资格：⚠电商刀含电商成交数据**只能上品牌广告、不能上非品牌广告**，要走非品牌广告就只切非电商刀；**每刀再标预计收窄力度 强/中/弱**（这刀保留的标签覆盖画像多少占比，强=切得狠约掉一个量级/中=切小半/弱=微调；**粗估自画像占比·非云图真实覆盖人数**，仅排刀序用）。老板**想快掉一个量级先挑「强」刀，按刀序一刀一刀切、每刀去云图看真实覆盖人数**，量级不满意把缩窄后画像重导出再跑一次做**二次提纯**）。

**输入约定**：`candidate` 传内置/dropbox 文件名（`diyu_xunwei`、`x.csv`）/ 容器可达绝对路径 / 原始 CSV 文本。老板新包从巨量云图导出 CSV → 丢进 `services/knowledge-engine/config/audience/`（或配 `OMNI_AUDIENCE_PACK_DIR`）→ 按文件名调。内置 `baseline_a4`（行业 A4 真需求标尺，静态）+ `diyu_xunwei`（范例）。

**⚠️ 老板从客户端上传 CSV 时（铁律，否则卡死）**：上传落 `C:\Users\Administrator\.omni-desktop\uploads\<sid>\<uuid>.csv`（KE 容器读不到该目录）。**绝不 `Read` 整个画像 CSV**（~3000 行 / 200KB 撑爆 Read 25k 上限，会翻不完卡死——已踩）。正确做法：用 Bash `Copy-Item` 把上传文件 copy 进 `config/audience/<干净名>.csv` 再 `diagnose_audience_pack(candidate='<干净名>')`（工具容器内直接读、不进上下文、秒出）；上传的若是 地域寻味人/行业A4 直接用内置 `diyu_xunwei`/`baseline_a4` 不用 copy。

**polish=False** 默认纯确定性零 token；**polish=True** 在骨架上跑 LLM 叙事层——把骨架当 **ground truth** + **巨量云图 KB grounding**（召回 methodology/authoritative，内容打法标 `[KB]`/`[行业推理]`），按外置提示词 `config/prompts/audience_pack_diagnose.{system,user}.md`（命门·热加载）写成**小白可操作**的诊断卡，**禁新增数值/伪因果**（R-14），失败 fail-open 回退骨架。

**铁律（写进每份诊断卡）**：**画像比对只是投前的冷启动代理**——能判断圈选合不合理、生成"先测哪些细分"的假设，但**判断不了真实投放价值**；真实价值只有 CTR/CVR/ROI/GMV 说了算，有了转化数据转化永远压过画像相似度。提纯**之后**再跑一次诊断（诊断的是最终真投出去那个包）。

### skill `audience-pack-diagnosis`
| 老板说 | Claude 应做 |
|---|---|
| "诊断一下 X 这个包 / X 包适不适合投 / 帮我看看地域寻味人这个包" | `diagnose_audience_pack(candidate='X')` 出投前诊断卡 + 漏斗定位 |
| "提纯一下 X 包 / X 包该怎么收窄 / 太大了帮我切 / 缩一个量级" | `diagnose_audience_pack(candidate='X', with_purify_plan=True)` 出**优先级阶梯施工单**（按漏斗定位排序的 N 刀 + 电商资格标记 + 每刀预计收窄力度 强/中/弱）；想快掉一个量级先挑「强」刀，切完不满意把缩窄后画像重导出再跑做二次提纯 |
| "把诊断写细点 / 给我能落地的内容打法" | 加 `polish=True`（巨量云图 KB grounding 叙事，小白可操作）|
