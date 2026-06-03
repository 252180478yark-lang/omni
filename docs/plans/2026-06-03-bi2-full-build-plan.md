# 全量 BI 2.0 构建规格（2026-06-03，workflow 产出 + 实测校验）

> 老板验收发现桌面 BI「看不到产品/价格、维度太少」。诊断：桌面图表框架够全（15 组件、两面、放大/下钻/展开），
> 瓶颈是落库桥只落全店 `_SHOP_` 的 ~45 指标，没 per-SKU、没价格、没人群细分。本规格补齐 6 大维度。
> 真实结构已 dump 到 `services/scout-agent/catalog/_bi_probe/*.json`（12 端点全真出数）。

## 已验证的地基事实（动手前确认过）
- 三平台登录态新鲜（2026-06-03 早上老板登过），scout fetch 通（POST localhost:8009/api/v1/scout/fetch）。
- **`mvp_sku` 有 `douyin_product_id` 列且已填** → product_id(抖音19位)→内部 SKU-xxxx 映射现成（如 3689782605839990880 ↔ SKU-368978-0004）。
- **`mvp_daily_metric.sku_id` 无 FK 约束** → 落 per-SKU 不会 FK 违约（agent 担心的最高风险不存在）。
- 落库桥 `metric_ingest.py`：`INGEST_ENDPOINTS`(14) + `CFG`(抽取器, 全 `_SHOP_`) + `_extract_metrics` + `_upsert_metrics`(ON CONFLICT sku_id,date,metric_name) + `_extract_benchmarks`(mvp_industry_benchmark)。已预留 `DEFERRED_DETAIL_TABLES`（达人/商品整表标二期）。

## 进度（2026-06-03）
- ✅ **步骤1 per-SKU 产品落库 DONE+验证**：metric_ingest 加 `_resolve_or_create_sku` + `_extract_product_metrics`/`_upsert_product_metrics`，product_list 6 商品 × 3 指标（gmv_paid/gmv_net/gmv_paid_wow_ratio，**与全店同名**）落 mvp_daily_metric(sku_id=内部SKU,全命中 douyin_product_id 映射)。RankChart(`WHERE sku_id<>'_SHOP_' GROUP BY sku_id`)零改动直接出产品榜。**老板开桌面产品 tab 即见 6 商品，无需重装**（桌面直连 DB）。
- ✅ **步骤2 registry 补注册 DONE+验证**：metric_registry 29→44，补 15 个已落库指标（gmv_net/gmv_paid_wow_ratio/top_sku_*/listed_sku_*/author_*/live_product_show_uv/product_card_show_uv/category_top_band_gmv_ratio）。query_metric_nl/AI 分析现在认得达人/商品榜/直播/退款后等指标。
- ✅ **步骤3 migration 040 DONE+验证**：7 维表(flow_source/author/search_keyword/crowd_big8_profile/crowd_asset_trend/price_band_product/industry_bestseller)全 IF NOT EXISTS+UNIQUE+索引，apply 到 live DB。
- ✅ **步骤4 dim_ingest.py DONE+验证**：7 抽取器(workflow 各看真实 dump 写)+ 通用 upsert(类型配置驱动)+ 接 metric_ingest(加6端点+延迟import调 ingest_dims)。实测落库 **flow_source 78/author 108/search 10/八大人群 336/人群趋势 210/价格带 15/畅销榜 99，0 错误**。口径全核对(达人¥串禁÷100、流量÷100、畅销价已是元禁÷100、人群cnt不÷100)。日级 cron 自动跑(scout daily-metric-ingest 调 ingest_metrics 已含 dims)。
- ⏳ 步骤5-6 待续：scout `/metrics/dim` 读端点 + KE 透传 dim_rows_written；前端 BI 2.0 图表(价格带直方图/人群堆叠/达人榜/搜索词榜)挂操盘手面 + 桌面重打包。**后端数据层全建完，剩展示层**。
- **关键提醒**：scout-agent 无 --reload，改 metric_ingest/dim_ingest 后必须 `docker restart omni-scout-agent` 才生效。

## 施工顺序（按依赖 + 见效快慢）

### 步骤1（最高优先·见效最快·零新表零前端改动）—— per-SKU 产品落库
- 扩 `metric_ingest`：加 `_resolve_or_create_sku(conn, product_id, name)`——先 `SELECT id FROM mvp_sku WHERE douyin_product_id=$pid` 命中拿内部 SKU；未命中懒填 mvp_sku(id=product_id, douyin_product_id=product_id, name, source='metric_ingest_autosku', status='active') ON CONFLICT DO NOTHING。**绝不落 `_SHOP_`**。
- 加 per-product 抽取器：
  - `compass.product_list`（6 行商品榜）→ `pay_amt`/`pay_amt_exclude_refund`/`pay_amt_out_period_ratio`（÷100，环比原样 0-1 可负）。值在 `data[i].cell_info.<m>.<m>_index_values.index_values.{value|out_period_ratio}.value`，**判 `'value' in node` 跳空块(unit=6)**。product_id 在 `data[i].cell_info.product_info.product_id_value.value.value_str`。
  - `compass.sku`（规格榜，翻页）→ `sku_pay_amt`(÷100)/`sku_pay_cnt`(件)/`sku_pay_ucnt`(人)。值在 `data[i].metrics.<m>.value.value`，sku_id 在 `data[i].base_info.product_sku_info.sku_id`。
- 每行先 resolve 拿 sku_id，再产 `{sku_id, date=ingest日, metric_name, value}`，kind=snap，复用 `_upsert_metrics`。
- 补 registry 9 个 per-SKU 指标。
- **落库即见效**：现有 RankChart/DeepDrilldown 读 mvp_daily_metric 按 sku_id 分组 → 产品榜/下钻立即有数据。

### 步骤2（共享契约·全店序列·纯 registry 加法）
- CFG 加 `compass.overview_data_trend` → `search_pay_amt` 序列(÷100) + 2 搜索 snap；`_extract_benchmarks` 加搜索三档标杆(第5块, metric='search_pay_amt')。
- 补 registry：已落未注册的 16 扩展指标(top_sku_*/listed_sku_*/author_*/live_product_show_uv/product_card_show_uv/category_top_band_gmv_ratio) + 搜索指标。让 query_metric_nl/business_analysis 立即认。

### 步骤3（建维表地基）—— migration `040_bi2_dim_tables.sql`，7 张表，全 IF NOT EXISTS + UNIQUE + 索引（纯加法可逆）
1. `mvp_flow_source_metric` — 流量来源渠道归因（video/product_card/live/other + 单视频带货榜含完播率）。PK BIGSERIAL，UNIQUE(stat_date,source_channel_code,entity_type,entity_id,metric_name)。
2. `mvp_author_daily_metric` — 达人带货榜（author_id varchar! 19位超 bigint；金额是 `¥xxx` 元字符串**禁÷100**）。UNIQUE(date,author_id,metric_name)。
3. `mvp_search_keyword_rank` — 搜索词榜（宽行：5 指标 + shop_product_ids jsonb；pay_amt÷100；翻页到 318）。UNIQUE(keyword,stat_date_end,platform)。
4. `mvp_crowd_big8_profile` — 八大人群×5A×7口径快照（stage_idx 存原始 0-5 数字 stage_label 留空；cnt int 化；pct/permeab 原样 0-1；self 万级 vs 同行百万级不可混算）。UNIQUE(date,stage_idx,big8_name,profile_type)。
5. `mvp_crowd_asset_trend` — 单人群×7口径 30天序列（date 'YYYYMMDD'→date）。UNIQUE(date,crowd_name,scope)。
6. `mvp_price_band_product` — 价格带×竞品池（gmv lower/upper 区间÷100**禁当精确值**；band_label/category_id 外部注入）。UNIQUE(date,category_id,band_label,product_id)。
7. `mvp_industry_bestseller` — 云图行业畅销/新品榜（rank=数组序+1；display_price 已是元**禁÷100**；dimension 三态）。UNIQUE(snapshot_date,dimension,rank)。

### 步骤4（落库桥写维表）—— 新文件 `services/scout-agent/app/services/dim_ingest.py`
7 个 `_extract_xxx` + `_upsert_xxx`，`metric_ingest.ingest_metrics` 顶层调用并 fail-open 收 errors。`INGEST_ENDPOINTS` 加 6 端点（共用 batch_raw 会话）。干跑核对行数 + 抽样核对口径。

### 步骤5（scout 路由 + KE tool 透传 + cron）
`GET /api/v1/scout/metrics/dim?table=&date=&limit=` 通用维表读端点；KE `ingest_platform_metrics` 透传 `dim_rows_written`；接 scout scheduler 已有 daily-metric-ingest（dim 跟着跑）。

### 步骤6（前端 BI 2.0，按面+子tab分批）
- 老板面（全复用零新组件最快上）：ProductRankBar(复用 RankChart) + ProductTrendDrilldown(复用 DeepDrilldown) + SearchGmvBenchmarkLine/ChannelExposureTrendLine(复用 TrendChart 多线)。
- 操盘手面（4 张新组件）：PriceBandHistogram(价格带直方图) / Big8CrowdStackedBar(人群堆叠) / AuthorRankTable(达人榜) / SearchKeywordRankTable(搜索词榜) + PriceBandCompetitorTable/FlowSourceFunnelStacked/IndustryBestsellerTable 下钻表。
- omni-desktop 改完 `npm run build` 重打包。

## 10 条风险（务必遵守）
1. per-SKU 用 `_resolve_or_create_sku`，绝不落 `_SHOP_`；autosku 懒填标 source='metric_ingest_autosku'。（FK 已确认不存在，但仍要 resolve 以复用 SKU 名展示）
2. 三套 ID：商品榜 product_id / 规格榜平台 sku_id / 内部 SKU-xxxx；按 metric_name 前缀(pay_amt vs sku_pay_amt)区分口径勿混算。
3. **金额双轨**：compass 数值端点'分'÷100(_yuan)；compass.list 达人榜'¥xxx'元字符串(_yuan_str **禁÷100**)；yuntu bestseller/价格带商品价已是元。逐端点核对 unit 编码 + 样本是否带小数，落错偏 100 倍。
4. 脱敏区间(价格带 GMV/件数)只落 lower/upper 或中值，**禁当精确值进聚合/经营分析**（违 R-14）。
5. 空块：罗盘 index_values 带 unit 编码，unit=6 空块无 value、unit='nan' 本期无数据，必须判 `'value' in node` 再取，否则 KeyError。
6. stage_idx→A标 未锁：存原始 stage_idx 数字，stage_label 留空，待比对云图 UI 再回填。
7. snap 趋势靠 cron 日累积；首日单点，前端折线处理 n<5 数据不足态（R-15）。
8. 分页：搜索词 318/达人 18/规格榜多页，翻页到 page_result.total。
9. 维表年级别行数可观但小表（单人自用），(date desc) 索引即可，无需分区。
10. 全程纯加法、fail-open、与 `_SHOP_`/分→元÷100/rate 0-1/rank 越小越好 契约对齐。

## 抽取器精确路径
见 workflow 产出 `endpoint_specs`（12 端点逐字段 json_path + 样本佐证），临时存于本次 workflow 输出。dump 文件常驻 `catalog/_bi_probe/`，重抓 `python scripts/_probe_bi_endpoints.py`。
