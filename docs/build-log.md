# omni-vibe 施工日志（build log）

> 这文件是 **CLAUDE.md 的施工档案**：每个切片改了哪些文件、doctor 工具计数怎么涨上来的、
> 当时「故意没做（T2 待老板）」清单、实测踩坑配方、数据流 ASCII 图。
>
> **这些对 agent 当下干活没用**——干活说明书在 `CLAUDE.md`（工具目录 / 老板话术路由 / SOP / 硬约束 / 调试命令）。
> 这里只为「想知道某能力当年是怎么搭起来的 / 踩了什么坑」时翻档。按时间倒序往下追加。
>
> doctor 工具总数演进：13 → 46 → 54 → 58 → 61 → 63 → 67 → 69 → 73 → 74 → **76**。

---

## BI 2.0 收尾：维表全可见 + 诊断标量 KPI 化 + migration 042（2026-06-05）

> 接 `docs/plans/2026-06-03-bi2-*` 蓝图。数据层（per-SKU + 16 维表 + bi_batch1 标量）此前已落，本次把"落库但看不见"的全补上前端，并收尾 042。

### 后端（omni · feat/competitor-research）
- **migration 042** `042_bi2_service_flow.sql` 应用到 live DB（IF NOT EXISTS 幂等）：`mvp_negative_comment_tag`（差评原因榜）/ `mvp_comment_tag_agg`（差评聚合×类目）/ `mvp_flow_entry_structure`（货架MALL vs 内容FEED GMV 占比，本店/竞品/行业）。
- `dim_ingest.py` +3 抽取器（`_extract_negative_comment_tag` / `_extract_comment_tag_agg` / `_extract_flow_entry_structure`，fail-open），`metric_ingest.py` INGEST_ENDPOINTS +3 端点（doudian.getnegativecommenttagscount / allcommenttagaggstat / yuntu.flowentrystructure）。实测已落（neg=4 / agg=2 / flow_entry=6）。scout-agent 源码 bind-mount，容器内已含 042 代码，日级 cron 自动跟跑。

### 前端（omni-desktop · feat/w1-tool-feedback）
- **诊断标量 KPI 化**：`METRIC_META` +28 条（行业排名 4 channel + 涨跌 / 体验 3 子分 / 好评率 vs 同行 / 投放 ad_cost_ratio·ad_costed_amt / 新老客 / 品牌 NSR·心智 / 搜索 / 待办），label/unit/agg/lower_is_better 全配齐。snapshot 类一律 `latest` 防跨日错误求和；rank 越小越好；rank-delta 用新 `名Δ` 单位渲染带符号不加"第"（修了 `industry_pay_rank_change`/`industry_rank_diff` 之前 -16 错渲成"第-16名"的 bug）。
- **老板面** BossPanel 加 3 组 KpiSection（行业位置 / 服务健康红线 / 品牌资产，点卡跳趋势）。**操盘手面** OperatorPanel 数据全景加 2 条 KPI（投放·转化诊断 / 搜索·货品诊断）。
- **维表全可见**：`DataPanoramaPanel`（操盘手数据全景）已用 `DimBarChart`/`DimTableCard` + 专用炫图（PriceBand/CrowdBig8/CrowdTrendLines/HotwordScatter/FlowSankey/FlowEntry）surface 全部维表；本次补 `mvp_industry_bestseller` 行业畅销榜表格（此前只被 PriceBandChart 当价格信号用）。
- 全部走既有 `window.api.analytics.dim`（IPC→PG 直查，表名白名单 + 列名正则校验 + 参数化防注入）。`npm run build` 三段全过（main+preload+renderer，2605 模块，0 error）。

### 验证
- 6-agent 对抗验证 workflow（按 dim-charts / kpi-surfacing / 042-backend / completeness 四维 review → 每条 finding 找 skeptic 反驳）：确认 1 个真 bug（rank-delta 单位，已修），其余 finding 多为 gap（见下）。9 张维表卡的列名 / kind / asOfKey 全核对过真 schema。

### 故意没做（下一批 · 需后端抽取器，各有 100x 口径风险）
- **投放 ROI**（compass.core_index_v3）→ 新维表 `mvp_ad_roi`（千川 boss 最痛，全盘唯一"投钱回报"维度）。
- **转化流失定位**（compass.flow_loss_card）→ 全店标量 + FunnelChart 每级补"流失 N 人/X%"。
- **搜索四档对标**（compass.overview_data）→ `mvp_industry_benchmark` 加 search 行，复用 kpiSnapshot 同行分位。
- **品牌市占率**（yuntu.insightbrandoccupancy）→ 全店标量 brand_market_share，进 BOSS_RANK_KPIS。

---

## 综合经营分析 + 临时问数（2026-06-03，§6 分析半）

doctor 总数 74 → **76**（generate_business_analysis + query_metric_nl）。两面叙事层均实测跑通（narrated=True，数字全 grounded、观察/假设分层、反 AI 腔）。

### 实现
- KE：`app/services/metric_registry.py`（29 指标元信息 + `resolve_metric` NL 解析【空白不敏感：'5A 总资产'/'GMV 走势' 带空格也命中】+ `BENCHMARK_METRICS` + owner/operator 两面指标清单）+
  `app/services/business_analysis_service.py`（`generate_business_analysis` 确定性分层 + `_narrate` LLM 叙事层【外置提示词 + `get_model_for_tool` 解析模型 + `focus`】+ `_build_sections` 分层卡片 + `query_metric_nl`）+
  `config/prompts/business_analysis.{system,user}.md`（命门·经营分析师提示词，确定性骨架当 ground truth，R-14 分层/反幻觉/反 AI 腔）+
  `app/mcp/tools/analytics.py`（2 tool）+ `app/routers/analytics.py`（GET 直测 `/api/v1/analytics/*` + 桌面契约 POST `/api/v1/mcp/analysis/{comprehensive,nl-query}`，range/filter/focus/face 壳→service）+
  `config/tool_models.yaml`（`generate_business_analysis`→gemini-3.1-pro-preview）+ `server.py`/`main.py`（挂 `mcp_analysis_router`）/`doctor.py`。
- omni-desktop（installer **0.2.3**）：`AiAnalysisPanel` 加 `face` prop（owner 默认 / operator）；`OperatorPanel` 顶部加 `<AiAnalysisPanel face="operator"/>`（操盘手面也有 AI 投放选品建议）；`ipc-handler.ts` comprehensive body 加 `face`；`shared/types.ts` `AnalyticsAiAnalysisArg` 加 `face`。**owner 面已在 0.2.2 装机版可用（IPC 路径早对齐）；operator 面 + 两面叙事质量需装 0.2.3**。

---

## 落库桥：实时取数 → 29 指标 + 同行标杆落库（2026-06-03）

doctor 总数 73 → **74**（ingest_platform_metrics）。

### 取数：复用 LiveFetchExecutor（绕缓存抓真返回）
`fetch()` 只返 verdict/抽字段，落库要看全结构 → 新加 `fetch_raw()` / `batch_raw()`
（返回整段 `parsed` JSON；`batch_raw` 按 host 分组复用一个浏览器会话）。10 个核心端点
（compass core_trend/flow_funnel + doudian overview/shop_overview + yuntu 6 个）一会话连打。

### 实现
- scout-agent：
  - `app/services/metric_ingest.py`（新，CFG 29 抽取器 + `_extract_benchmarks` + upsert 两表 + `_ensure_shop_sentinel` + `fetch_series`）
  - `app/services/live_fetch.py`（加 `fetch_raw` / `batch_raw` 取整段 parsed JSON）
  - `app/routers/metrics.py`（新，ingest + series 两 endpoint）+ `app/main.py`（挂 router）
  - `app/scheduler.py`（加 `daily-metric-ingest` job 09:00）
- KE：`app/mcp/tools/platform_fetch.py`（加 `ingest_platform_metrics` tool）+ `app/mcp/doctor.py`（wanted +1）

### 实测落地（2026-06-03 跑通）
- 触发一次：`metric_rows_written=428` + `benchmark_rows_written=377`，`metrics_ok=29/29`，零错误。
- 抽样核对：`gmv_paid` 06/02 = **498.5**（罗盘金额分 49850÷100）；同日同行标杆 industry_avg=874.55 / shop_value=498.5。
- 踩坑修：asyncpg DATE 列要 `datetime.date`（不吃 ISO str）、NUMERIC 列要 `Decimal`（不吃 float）—— upsert 前 `_as_date` / `_as_num` 归一。
- 需国内登录态有效（cookies 在 `sessions/{yuntu,douyin_compass,douyin_shop_admin}/storage_state.json`）。
- 调试脚本仍可干跑验证抽取器：`python services/scout-agent/scripts/_ingest_kpi.py`（读 `_kpi_raw` 缓存不落库）。

---

## 诊断官·分析面趋势归因 + 问数工具（§6.2 + R-14 + R-15，2026-06-02）

doctor 总数 67 → **69**（explain_anomaly + query_metric_trend）。

### REST endpoint（桌面经 IPC→http 调，调不了 MCP tool；与 tool 共用同一 service 函数禁漂移）
- `GET /api/v1/mcp/explain-anomaly?anomaly_id=`
- `GET /api/v1/mcp/metric-trend?metric_name=&sku_id=&platform=&days=`
（挂在 `proposals.py` 新增 `query_router`，main.py include）。

### 实现
- `app/services/diagnose_service.py`（`_ANALYSIS_METRIC_HYPOTHESIS` 模板表 + `_collect_anomalies` +
  `_build_analysis_proposals` + `run_diagnose` analysis 分支 + `query_metric_trend`/`explain_anomaly`/`_metric_series`）
- `app/mcp/tools/diagnose.py`（diagnose 加 platform 参 + `explain_anomaly`/`query_metric_trend` 2 tool）
- `app/routers/proposals.py`（DiagnoseRequest 加 platform + query_router 2 endpoint）+ `app/main.py`（挂 query_router）
- `app/mcp/doctor.py`（wanted +2）

### 故意没做（T2 待数据/老板）
跨平台归因（京东淘天数据未入库，§8.5）、滚动基线/断更守卫（A 异动引擎管）、LLM 叙事增强、诊断官接 cron。

---

## 阶段0 地基 wiring + L0-2 + 诊断官 + 运营洞察前端（2026-06-02）

蓝图 §8 阶段0 的 schema 地基（034 platform 维 / 035 tool_use_id 列 / 036 actor_id / 037 product+listing+v_metric_rollup）晨确认已 apply 到 live DB，本切片把它们接通用上 + 补 L0-2 + 上线诊断官 + 前端 surfacing。全程 T0/T1 加法可逆，未碰 STEP 2 contract / 未 commit / 未轮换密码（T2 待老板）。doctor wanted 63→**67**。

### 后端（KE）
- **L0-2 月度成本闭环**：apply migration 033（`mcp.monthly_spend` + 视图）。`app/routers/spend.py`（`POST /spend/record` 前端 task_done 归集 + `GET /spend/month` 累计+软上限）。MCP tool `query_monthly_spend`。软上限读 `OMNI_MONTHLY_SPEND_CAP_USD`（缺省回退 500，老板配才启用超额提示）。复用夜间 `cost_ledger_service`。
- **tool_use_id 焊归因链**：`app/routers/tool_uses.py`（`POST /tool-uses/link`，按 tool_name+时间窗回填最早未焊接 tool_calls 行；幂等 fail-open）。前端在 task_done 批量 POST。打通"差评→哪次调用→哪段 prompt"。
- **ad_metrics 入库校验（§1.4）**：`app/services/ad_metrics_validation.py`（白名单+上下界，R-4 拒手填 roi，未知/越界标 `_validation` 不进聚合，fail-open 不丢数据）。接入 `record_ad_metrics`。
- **诊断官（§6.2，能力即工具）**：apply migration 038（`mcp.improvement_proposals` 生命周期表）。`app/services/diagnose_service.py`（确定性生成不调 LLM，复用 cron `_collect_feedback_digest` 聚类；R-14 observation/hypothesis 分层禁伪因果、R-15 样本量 preliminary、R-17 投后口径、R-20 dedupe/priority/expiry/三态）。3 个 tool `diagnose`/`list_proposals`/`resolve_proposal` + `app/routers/proposals.py`。只提议不碰开关。
- **周期报端点**：`app/routers/agent_state.py`（`GET /agent-state/reports` 读 cron 写的 weekly_review/daily_pulse/feedback_digest/dynamic_block md）。
- doctor wanted 63→67；L0 gate 预算 env key 对齐 `OMNI_MONTHLY_SPEND_CAP_USD`；doc体检路径改 env 可配 `OMNI_CLAUDE_MD_PATH`。
- 回归网修绿（L0-7）：7 个夜间遗留过时单测（gate 超时 expired / audit tool_name kwarg / hub status_code / knowledge 分页 dict）全按已落地正确行为对齐；**268 单测全过**。

### 前端（Next.js）
- ws-handler.ts：task_done 后 fire-and-forget POST 成本归集 + tool_use_id 焊链（host-friendly KE base）。
- claude-runner.ts：stream-json 运行时形状校验（fail-open warn）+ CLI 版本一次性记日志（L0-1 部分；完整 L0-1 含三端共享 runner 包是 T2）。
- 新 `/insights` 页（运营洞察）4 tab：改进建议（诊断官 inbox + 三态拍板按钮）/ 运行成本（月度 spend + 软上限进度）/ 周期报（cron md 渲染）/ 底座状态（阶段0 就绪度 + R-8 接现成 BI 声明）。4 个 `/api/omni/{proposals,spend,cron-reports}` 代理路由 + sidebar「运营洞察」入口。

### 故意没做（T2 待老板）
STEP 2 contract（解绑 douyin 主键 / 换 UNIQUE 含 platform / NOT NULL）、GMV·ROI 归一口径、三端 runner 共享包、密码轮换/git 历史、commit、多平台京东淘天数据接入（§8.5 等数据源）、诊断官 LLM 叙事增强、诊断官接 cron。

---

## 竞品调研：淘宝抓取 + 视觉拆解（2026-06-01）

doctor 总数 61 → **63**（竞品 2 tool）。**京东后续接**（platform 已留参数，scout 加个 `/jd/*` 端点即可）。

### 数据流
```
skill competitor-product-research（话术触发，每步停等反馈）
  Stage1 → competitor_search → httpx → scout-agent POST /taobao/search（Playwright 登录态抓 50 卡片）
                              → LLM 相关性过滤 → md 榜单 → 老板挑
  Stage2 → competitor_decompose → httpx → scout-agent POST /taobao/detail（主图+详情页 alicdn url）
                              → KE fetch CDN 图→base64 data 块 → gemini 多模态 → 5 维度 md
```

### scout-agent 侧（浏览器层，纯抓取不碰 LLM）
- `app/routers/taobao.py`：`POST /api/v1/scout/taobao/search` + `/taobao/detail`。复用 persistent-context
  登录态（`sessions/taobao/user_data`）。抗变更靠"商品详情链接锚点 + 结构爬升 + 文本正则"启发式
  （`_SEARCH_EXTRACT_JS` / `_DETAIL_EXTRACT_JS`），不靠 hash 化 class。抓不到不抛 → 返
  login_required/no_items + 落 `snapshots/taobao/`（全页截图 + HTML）供调选择器。
- `app/routers/sessions.py`：加 `taobao` 平台（PLATFORMS + relogin url + 淘宝登录 cookie 检测
  `unb/tracknick/lgc/_tb_token_/...` + 首次 relogin upsert mvp_session 行）。
- 同 user_data_dir 不能并发开 context → `_TAOBAO_LOCK` 串行化。`headless` 可按请求覆盖。
- **源码已 bind-mount**（compose 新加 `./services/scout-agent/app:/app/app`）：调选择器改完
  `docker restart omni-scout-agent` 即生效，免 rebuild。

### 实现
- scout-agent：`app/routers/taobao.py`（新）+ `app/routers/sessions.py`（加 taobao）+ `app/main.py`（挂 router）
- KE：`app/services/competitor_research.py`（新，scout HTTP + alicdn 图→data URI + 榜单 md）+
  `app/mcp/tools/competitor.py`（新，2 tool）+ `config/prompts/competitor_relevance.{system,user}.md` +
  `competitor_decompose.{system,user}.md`（新）+ `config.py`（scout_agent_url）+ `server.py`/`doctor.py`/`tool_models.yaml`（注册）
- compose：scout-agent app bind-mount + NO_PROXY 加 scout-agent + KE 加 SCOUT_AGENT_URL
- skill：`.claude/skills/competitor-product-research/SKILL.md`（新）

### 实测落地（2026-06-01，踩坑后跑通）
- **必须 headed + xvfb**（headless 被 rgv587 deny）、**storage_state 明文 cookie**（Windows profile 跨 OS 解不开）、**首页热身 + `&page=N`**（`&s=` 触发 deny）、**进口 IP 不行**：淘宝要**国内 IP**——VPN 切「规则/分流」模式让淘宝走直连国内 IP，hub 继续走代理连 Gemini（否则外国机房 IP 被搜索反爬拦）。详见记忆 [[project-taobao-scraping-recipe]]。
- **chat 模型 `gemini-3.5-flash`**（`gemini-3-flash-preview`/`2.5-flash` 是无效名 → hub 旧 build 静默回退 anthropic-mock 假响应）。competitor_search/decompose 的 tool_models.yaml 已用它。
- **搜索榜单 ✅ 跑通**（标题/显示价/月销/店铺/链接/主图 + 相关性过滤）。
- **详情页 = 淘宝最硬的墙**：PC item 页"验证码拦截"（goto/referer/真点击全拦），移动 H5 不弹验证码但 SPA 抓不到 DOM、且实测也常返"访问被拒绝"。`competitor_decompose` **三层兜底**：① 先试 scout `/taobao/detail_shots`（移动 H5 滚动截图喂视觉，渲染出来就用真截图）② 被挡 → 退用**搜索主图**（传 `items` 带 main_image_url）拆 卖点/构图/配色/设计，"内容"标缺 ③ `local_images=["/host/Desktop/x.jpg",...]`：老板手动截详情页（真实登录态无反爬）**100% 可靠全 5 维**。调用优先传 `items`；要真详情页用 `local_images`。
- scout-agent 已改**不走 VPN**（compose 清空它的 proxy env；它只抓国内站 + 内网 ai-hub）。
- 调试辅助脚本：`services/scout-agent/_login_taobao.py`（host 弹窗登录淘宝写 storage_state）、`services/knowledge-engine/scripts/_test_competitor_{scrape,full}.py`。

---

## W1 切片：检索增强 + 投后回传闭环 + 飞轮 Phase B + 工具反馈（2026-05-29）

doctor 总数 58 → **61**（投后 3 tool）。

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
- 3 tool：`record_ad_metrics` / `pipeline_get_asset_lineage` / `pipeline_list_asset_performance`
- 定位三选一（asset_id > external_video_id > external_creative_id），jsonb `||` 合并可多次累积回传
- 实现：`pipeline_lineage.py`（record_ad_metrics/get_asset_lineage/list_asset_performance）+ `pipeline.py`（3 tool）

### 4. 飞轮 Phase B + 工具级反馈
- **feedback_digest cron**：每周聚类消息级负反馈(7 类) + 工具级负反馈(tool×分类) + 30 天投后数据，写改进草稿。只聚类不自动改 prompt（决定权留老板）。实现 `cron.py` + `main.py`（注册第 4 loop）
- **桌面工具级 👍👎**：`mcp.tool_calls` 没存 tool_use_id 也无 session 链 → 新 `POST /api/v1/mcp/tool-calls/rate-recent`**按 tool_name 取最近一条**解析 call_id（单人场景：评的就是刚看到那条）。写 `user_rating+rating_category` → feedback_digest 能聚类。实现：KE `mcp_tool_calls.py`(router)+`schemas/mcp_tool_calls.py`(RateRecentRequest)；omni-desktop `ToolFeedback.tsx`(新)+`ToolCallChip.tsx`(挂入)+`ipc-handler.ts`(改调 rate-recent)+`shared/types.ts`(IpcRateToolCallArg 改 tool_name)

四闭环现状：bug 避坑(原有) + 投后数据→血缘(本次) + 负反馈+投后→周报草稿(本次) + 工具级反馈→聚类(本次)。

**注意**：桌面侧改动（工具反馈 + 之前 DevTools/消息ID/resume-scheduler 修复）要 `npm run build` 重新打包桌面 app 才生效（KE 改动已随容器重启生效）。

---

## Bug 记忆库 + 客户端日志（Phase A+/A++ · 2026-05-28）

doctor 总数 → **58**（log_client_event/report_bug/list_bugs/update_bug 4 tool）。

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

### 表（migration 032）
- `mcp.client_logs` — 客户端所有运行时事件留痕(IPC/fetch/spawn/error/crash/startup);severity 5 级;`user_marked_bug` 标位关联 `bug_memory_id`
- `mcp.bug_memory` — bug 长期记忆;`fix_applied` 标位决定是否进入启动期 inject;`occurrences` 自动累计;`tags` 数组(`ui/ipc/ke/claude/electron/data/other`)

### 5 个 REST endpoint（`bug_memory.py` router）
- `POST /api/v1/mcp/client-logs/batch`
- `POST /api/v1/mcp/bugs` + `GET /api/v1/mcp/bugs` + `PATCH /api/v1/mcp/bugs/{id}`
- `GET /api/v1/mcp/bugs/inject-summary` — desktop spawn 时拉,渲染成 system prompt 注入文本(≤2000 字符)

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

---

## 反馈飞轮地基（Phase A · 2026-05-28）

老板自用 omni 要"越用越聪明",4 层架构(可观测/可反馈/可归因/可改进)。Phase A 补齐**第 2 层"可反馈"**:客户端到 DB 的反馈通路。不引强化学习(API 模型改不了权重),走 **harness engineering / compound AI system / data flywheel** 这条路。doctor 总数 → **54**（rate_message）。

### 数据流
- **消息级反馈**(老板说"这条 AI 回复不行"):desktop MessageBubble 👍👎 → IPC `rate-message` → main process fetch → KE `POST /api/v1/mcp/messages/rate` → tool `rate_message` → `mcp.message_feedback` 表
- **tool 级反馈**(老板说"这个 tool 调错了"):web `/agent-log` 👍👎🔁 → `rate_tool_call`(MCP)→ `mcp.tool_calls.user_rating + rating_category`;desktop 也通了 `rate-tool-call` IPC channel 但 UI 暂未挂(Phase 后续做 ToolCallChip 反馈)

### 表 + tool（migration 031）
- 新 `mcp.message_feedback`(`session_id+message_id` UNIQUE,覆盖更新;`category` 7 类 + `message_text_snapshot` ≤4KB + `tool_use_ids[]` 反查涉及的 tool)
- `mcp.tool_calls` 加 `rating_category` 归因字段
- `rate_message(session_id, message_id, rating, category?, note?, message_text_snapshot?, tool_use_ids?, client?)` — `session_id` 自动兼容 uuid / claude_session_id 文本
- `rate_tool_call(call_id, rating, note?, category?)` — 加 `category` 可空入参向后兼容

### 实现
- `migrations/031_feedback_flywheel.sql`
- `services/knowledge-engine/app/services/agent_log_service.py`(rate_message_logic + _resolve_session_uuid)
- `services/knowledge-engine/app/mcp/tools/feedback.py`(rate_message tool + rate_tool_call 加 category)
- `services/knowledge-engine/app/routers/mcp_tool_calls.py`(POST `/api/v1/mcp/messages/rate`)
- `services/knowledge-engine/app/schemas/mcp_tool_calls.py`(MessageRateRequest)
- `services/knowledge-engine/app/mcp/doctor.py`(wanted set 加 `rate_message`,总数 54)
- omni-desktop:`src/shared/{ipc-channels,types}.ts` + `src/main/ipc-handler.ts` + `src/preload/preload.ts` + `src/renderer/components/MessageFeedback.tsx`(新)+ `MessageBubble.tsx` + `MessageStream.tsx`

### 飞轮后续 Phase（等老板拍板，飞轮 + bug 库共用这套规划）
- **Phase B**:负反馈聚类 → prompt 改进建议草稿(tool 自进化) ← feedback_digest cron + 诊断官已落地
- **Phase C**:codify_pattern_to_skill cron 真触发 + skill 评分入库(skill/sop 自进化)
- **Phase D**:sku-pipeline 各 step 加 run 级评分(pipeline 自进化)
- **Phase E**:web `/agent-log` 加 7 天趋势仪表盘 + bug 解决率 + 模式归因日志

---

## omni 三端协同（W6 multi-device · 2026-05-17）

实现:
- `frontend/public/manifest.json` + `icon{,-192,-512}.svg`
- `frontend/src/app/layout.tsx` (metadata.manifest + viewport export)
- `frontend/src/components/agent-chat/{ChatLayout,SessionList,InputBar}.tsx` (移动端响应式)
- `frontend/src/lib/agent-chat/ws-handler.ts` (task_done fetch notify endpoint)
- `services/knowledge-engine/app/routers/notify.py` (POST /api/v1/notify/task-done + human-gate + health)
- `docker-compose.yml` nginx 端口绑定改 `0.0.0.0`
- `docs/multi-device/setup.md` (装机指南)

设计细节（移动端响应式）：
- nginx 绑 `0.0.0.0:80`，其他服务保持 127.0.0.1 经 nginx 反代
- `/chat` PWA：manifest + icon SVG + viewport meta + appleWebApp meta；OPPO Chrome 可"添加到主屏"带启动屏 + 全屏 + safe-area
- ChatLayout 加 hamburger button + mobileNavOpen state；SessionList 小屏抽屉模式（`fixed translate-x` 滑入，backdrop click 关）；InputBar `paddingBottom: max(0.75rem, env(safe-area-inset-bottom))` 适配全面屏 home indicator
- 长任务推企业微信：KE `POST /api/v1/notify/task-done`（不走 Human Gate）；frontend ws-handler 在 task_done 时 fire-and-forget fetch 推送（>=10s 任务才推）；没配 `WECOM_WEBHOOKS` 返 `skipped:true`
- 网络层：Tailscale（Win + Mac + OPPO 三端同账号），走 100.x.x.x tailnet IP P2P 加密，0 公网暴露

---

## sku 出片链路血缘（W4-B 切片 14.3 phase A）实现
- `migrations/021_pipeline_lineage.sql`（schema + 6 表 + 视图）
- `migrations/022_keyword_packs.sql`（关键词扩展包表，挂 sku/audience_record/pack）
- `services/knowledge-engine/app/services/pipeline_lineage.py`（save/list/get/adopt + regex 拆）
- `services/knowledge-engine/app/mcp/tools/pipeline.py`（7 个 lineage 查询/采纳 tool）

## 后台 cron 实现
`services/knowledge-engine/app/mcp/cron.py`
