# 路径 A · 施工：抖店 MVP 工程实施文档

> 配套 PRD：`01-PRD-抖店MVP产品需求文档.md`
>
> 本文档面向研发，提供可直接拆 ticket 的工程细节。

---

## 文档信息

| 项 | 值 |
|---|---|
| 文档版本 | v1.0 |
| 适用阶段 | Path A 实施期（14 个工作日） |
| 编写日期 | 2026-04-30 |
| 目标读者 | 研发（1-2 人） |

---

## 一、架构总览

### 1.1 服务拓扑

```
┌───────────────────────────────────────────────────────────────────┐
│                         frontend (Next.js)                        │
│  /workspace  /products  /sku/[id]  /scout  /decisions             │
│       BFF (app/api/omni/*)                                        │
└──────────────┬─────────────────┬───────────────┬──────────────────┘
               │                 │               │
               ▼                 ▼               ▼
       ┌─────────────┐    ┌──────────────┐   ┌───────────────┐
       │ scout-agent │    │ knowledge-   │   │ ad-review-    │
       │   :8009     │    │ engine:8002  │   │ service :8008 │
       │   ★ NEW     │    │  (复用 RAG)  │   │  (复用诊断)   │
       └──────┬──────┘    └──────────────┘   └───────────────┘
              │
              ▼
       ┌─────────────┐
       │ Playwright  │
       │ (browser)   │
       └──────┬──────┘
              │
              ▼
       ┌─────────────────────────────┐
       │ 抖店罗盘 / 客户分析 / ...    │
       └─────────────────────────────┘

       ┌─────────────────────────────┐
       │ PostgreSQL :5432            │
       │   schema: mvp_*  (★ NEW)    │
       └─────────────────────────────┘
```

### 1.2 新增 vs 复用

| 类别 | 新增 | 复用 |
|---|---|---|
| **后端服务** | `services/scout-agent` (:8009) | knowledge-engine RAG / ad-review review_engine |
| **数据库** | `mvp_*` **14 张表**（v1.4，含 mvp_5a_asset_daily / _flow_daily / _stock_change_log / _industry_benchmark / _brand_mind_daily 5 张新表）| 现有 PG 实例（同 schema 存放） |
| **前端页面** | `/workspace` `/products` `/sku/[id]` `/scout` `/decisions` | sidebar / chat / roundtable |
| **前端组件** | `<SaveToDecisionButton>` `<ChangeEventForm>` `<VerificationCard>` `<AnomalyCard>` | citation-markdown / app-shell |
| **状态管理** | `decisionStore` `skuStore` `changeEventStore` | chatStore / personaStore / roundtableStore |
| **工具库** | `services/_shared/playwright_utils/` | - |

### 1.3 桥接已完成的部分（不再重复实施）

- ✅ Sidebar 5 段分组 + 4 入口
- ✅ 5 个新页面占位（workspace/products/sku/[id]/scout/decisions）
- ✅ decisionStore + persist
- ✅ SaveToDecisionButton 组件
- ✅ Chat / Roundtable 接入决策日志写入

下文施工内容假设上述桥接已就位。

---

## 二、数据库设计（完整 SQL）

### 2.1 创建 schema

```sql
-- 临时简化结构，跑完 MVP 后迁移到 omni_* schema（路径 B）
-- 字段名严格遵循 snake_case，与路径 B 表结构保持兼容
```

### 2.2 mvp_sku：5 个核心 SKU（v1.4 扩展）

> **v1.4 调研结论**：SKU 主数据权威源 = **抖店后台 g-list**（不是罗盘的 commodity-product-list）。所有 mvp_sku 行都标 `source='shop_admin'`。

```sql
CREATE TABLE IF NOT EXISTS mvp_sku (
    id                  VARCHAR(64) PRIMARY KEY,             -- "SKU-A001"
    name                VARCHAR(200) NOT NULL,
    category            VARCHAR(100),
    -- 抖店字段
    douyin_product_id   VARCHAR(64) NOT NULL UNIQUE,
    douyin_url          TEXT,
    douyin_shop_id      VARCHAR(64),
    -- v1.4 新增：从抖店后台 g-list 同步的字段
    source              VARCHAR(32) DEFAULT 'shop_admin',    -- 'shop_admin' (默认) / 'manual'
    platform_status     VARCHAR(32),                         -- 'on_sale' / 'off_sale' / 'paused'（来自 g-list "已上架/售卖中"）
    total_stock         INTEGER,                             -- 总库存（来自 g-stock-manage-list）
    available_stock     INTEGER,                             -- 未占用库存
    locked_stock        INTEGER,                             -- 占用库存
    growth_class        VARCHAR(32),                         -- 'excellent' / 'good' / 'declining' / 'optimizing'（来自 growth-common-growth-shelf）
    created_on_platform_at TIMESTAMPTZ,                      -- 平台商品创建时间（g-list "商品创建时间"）
    -- 业务状态
    status              VARCHAR(32) DEFAULT 'active',        -- active / paused / archived
    push_tier           VARCHAR(32),                         -- main / growth / declining / new
    -- 元数据
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mvp_sku_status ON mvp_sku(status);
CREATE INDEX idx_mvp_sku_growth_class ON mvp_sku(growth_class);
CREATE INDEX idx_mvp_sku_platform_status ON mvp_sku(platform_status);
```

**初始化策略（v1.5 改为系统自动同步，无需老板填占位 SKU）**：

```python
# scout-agent 启动时第一件事：跑 g-list runbook 同步全店 SKU
# 之后每天再跑增量同步
# 系统启动时不再手动 INSERT 任何 SKU 行——由 g-list 同步器创建
async def bootstrap_skus():
    """首次启动 / 每天 08:00 调用：从抖店后台 g-list 全量同步 SKU 主数据"""
    skus = await fetch_g_list_skus()  # 抖店后台返回 41 SKU
    for sku in skus:
        await db.execute("""
          INSERT INTO mvp_sku (
            id, name, category, douyin_product_id, douyin_url, douyin_shop_id,
            source, platform_status, total_stock, available_stock, locked_stock,
            growth_class, created_on_platform_at, status, push_tier
          ) VALUES (
            $1, $2, $3, $4, $5, $6,
            'shop_admin', $7, $8, $9, $10,
            $11, $12, 'active', $13
          )
          ON CONFLICT (id) DO UPDATE SET
            platform_status = EXCLUDED.platform_status,
            total_stock = EXCLUDED.total_stock,
            available_stock = EXCLUDED.available_stock,
            locked_stock = EXCLUDED.locked_stock,
            growth_class = EXCLUDED.growth_class,
            updated_at = NOW()
        """, sku.id, sku.name, sku.category, sku.douyin_product_id, sku.url, sku.shop_id,
             sku.platform_status, sku.total_stock, sku.available_stock, sku.locked_stock,
             sku.growth_class, sku.created_on_platform_at,
             classify_push_tier(sku))  # 'main' / 'growth' / 'declining' / 'new'

# id 由 douyin_product_id 派生：'SKU-' + douyin_product_id 前 6 位 + 序号
# 不再使用 SKU-A001 这种占位名
```

**重点池规则函数（v1.5，每周日 23:00 重排）**：
```python
async def rebuild_focus_pool():
    """
    选 ~9 个 SKU 进重点池：
    - GMV TOP 5（近 30 天 gmv_paid 排序）
    - 衰退 TOP 2（连续 3 天 gmv_paid 下行 + 30 天同比下滑）
    - 新品 TOP 2（created_on_platform_at ≤ 30 天，按当日流量）
    + 老板手动锁定的 SKU（最多 5 个，额外加入）
    """
    main = await query_top_n_by_gmv(n=5, days=30)
    declining = await query_declining_n(n=2)
    new_ones = await query_new_n(n=2, max_age_days=30)
    locked = await query_user_locked_skus(max=5)
    pool = list({s.id for s in main + declining + new_ones + locked})
    await db.execute("UPDATE mvp_sku SET in_focus_pool=FALSE")
    await db.executemany(
      "UPDATE mvp_sku SET in_focus_pool=TRUE, focus_reason=$2 WHERE id=$1",
      [(s.id, reason_for(s, main, declining, new_ones, locked)) for s in pool]
    )
```

**`mvp_sku` 表需补 2 个字段**：
```sql
ALTER TABLE mvp_sku ADD COLUMN in_focus_pool BOOLEAN DEFAULT FALSE;
ALTER TABLE mvp_sku ADD COLUMN focus_reason VARCHAR(64);  -- 'top_gmv' / 'declining' / 'new' / 'locked'
ALTER TABLE mvp_sku ADD COLUMN locked_by_user BOOLEAN DEFAULT FALSE;  -- 老板手动锁定
CREATE INDEX idx_mvp_sku_focus ON mvp_sku(in_focus_pool) WHERE in_focus_pool;
```

### 2.3 mvp_daily_metric：每日指标快照

```sql
CREATE TABLE IF NOT EXISTS mvp_daily_metric (
    id              BIGSERIAL PRIMARY KEY,
    sku_id          VARCHAR(64) NOT NULL REFERENCES mvp_sku(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    metric_name     VARCHAR(64) NOT NULL,
    value           NUMERIC(20, 6),
    source_runbook  VARCHAR(128),
    source_run_id   VARCHAR(64),
    raw             JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(sku_id, date, metric_name)
);

CREATE INDEX idx_mvp_metric_sku_date ON mvp_daily_metric(sku_id, date DESC);
CREATE INDEX idx_mvp_metric_runbook ON mvp_daily_metric(source_runbook, date DESC);
```

**核心 metric_name 枚举**（v1.4 终版，3 平台合并）：

> **重要约定**：主线指标用 `gmv_paid`（用户支付金额），不用 `gmv` 或 `revenue`。`gmv` 字段保留兼容，但生产以 `gmv_paid` 为准。

**[共有 / 罗盘]**

| metric_name | 单位 | 来源 | 说明 |
|---|---|---|---|
| `gmv_paid` | 元 | 罗盘首页/交易 | **用户支付金额（主线）** |
| `order_count` | 笔 | 罗盘 | 支付订单数 |
| `buyer_count` | 人 | 罗盘 | 成交人数 |
| `uv` | 人 | 罗盘 | 用户访问数 |
| `click_count` | 次 | 罗盘 | 点击数 |
| `uv_value` | 元 | 罗盘 | UV 价值（gmv_paid / uv） |
| `aov` / `avg_order_value` | 元 | 罗盘 | 客单价 |
| `unit_price` | 元 | 罗盘 | 件单价 |
| `ctr` / `cvr` | 0-1 | 罗盘 | 点击率 / 转化率 |
| `bounce_rate` | 0-1 | 罗盘 | 跳失率 |
| `add_to_cart_rate` | 0-1 | 罗盘 | 加购率 |
| `refund_amount` / `refund_rate` | 元 / 0-1 | 罗盘退款分析 | 退款金额 / 退款率 |
| `net_revenue` | 元 | 罗盘营收分析 | 实收金额（剔除运费/补贴/佣金） |
| `experience_score` | 分（5 制）| 罗盘体验 / 抖店后台 eco | 商家体验分总分 |
| `experience_product` / `_logistics` / `_service` / `_fulfill` | 分 | 同上 | 4 子维体验分 |
| `service_session_count` / `service_response_time` / `service_dissatisfaction_rate` | 个 / 秒 / % | 罗盘客服分析 | 客服会话量/响应时长/不满意率 |
| `review_bad_rate` / `review_count` | % / 个 | 罗盘用户原声 + 抖店后台评价管理 | 商品差评率 / 评价数 |
| `quality_refund_rate` / `complaint_rate` | % | 罗盘用户原声 | 品质退货率 / 投诉率 |
| `logistics_pickup_rate` / `_trunk_rate` / `_lastmile_rate` | % | 罗盘 + 抖店后台物流诊断 | 揽收/干线/末端时效率 |
| `search_uv` / `search_referral_uv` | 人 | 罗盘搜索流量 | 搜索 UV / 引流 UV |
| `weight_score` / `rank` | - | 罗盘商品诊断 | 商品权重分 / 类目排名 |

**[v1.3 from 抖店后台]**

| metric_name | 单位 | 来源 | 说明 |
|---|---|---|---|
| `todo_pending_ship` / `_aftersale` / `_review` / `_audit` | 个 | mshop-homepage-index | **6 待办数实时**（待发货/待售后/待评论/待审核） |
| `todo_abnormal_order` / `_appealing` | 个 | 同上 | 异常订单 / 申诉中 |
| `logistics_pickup_avg_hours` | 时 | logistics-project-diagnosis-index | **揽收平均时长**（罗盘没有） |
| `logistics_overdue_orders` | 单 | 同上 | **超时单数**（按发货地） |
| `review_real_pic_ratio` / `_video_ratio` / `_quality_ratio` | % | maftersale-comment | 实拍/视频/优质评价占比（罗盘没有） |
| `review_invite_count` | 个 | maftersale-comment-邀请评价 | 邀请评价数 |
| `sku_total_stock` / `_available_stock` / `_locked_stock` | 件 | g-stock-manage-list | 总/未占用/占用库存 |
| `sku_status` | 枚举 | g-list | on_sale/off_sale/paused |
| `sku_growth_class` | 枚举 | growth-common-growth-shelf | excellent/good/declining/optimizing |
| `member_consumer_total` | 人次 | mvip-consumer | 用户总人次 |
| `member_new_amount` / `_old_amount` | 元 | mvip-consumer | 新客 / 老客金额 |
| `marketing_active_count` | 个 | 营销活动 | 在跑营销活动数 |
| `marketing_voucher_used` | 个 | 优惠券 | 优惠券核销数 |

**[v1.4 from 云图]**

| metric_name | 单位 | 来源 | 说明 |
|---|---|---|---|
| `asset_5a_total` | 人 | assets-crowd-distribution | 5A 总资产 |
| `asset_o_count` / `_a1_aware` / `_a2_appeal` / `_a3_ask` / `_a4_act` / `_a5_advocate` | 人 | 同上 | **6 张 5A 大卡** |
| `flow_acquire` / `_reservoir` / `_seed` / `_live_convert` / `_seed_convert` / `_repurchase` | 人 | assets-crowd-flow | **6 场景流转**（拉新/蓄水/种草/直播转化/种草转化/复购） |
| `mind_brand_assoc` / `_industry_share` / `_industry_rank` | 数 / % / 名次 | image-mind-monitor | 品牌联想量 / 行业联想份额 / 排名 |
| `mind_reputation` / `_preference` | % | 同上 | 美誉度 / 偏爱度 |
| `mind_dwell` / `_connection` / `_increase` | 评分 | home-overview | 5A 心电图 3 指标（停留/联想/增长） |
| `gta_5a_buyer_ratio` / `_o_buyer_ratio` / `_a3_in_5a_ratio` | % | assets-gta-overview | GMV TO 5A 归因（5A 成交占比 / O 机会成交 / A3 占 5A 比例） |
| `search_brand_exposure` / `_brand_searcher` / `_sov` / `_brand_buyer` | 次/人/%/人 | search-overview | 品牌曝光/搜索人数/搜索 SOV/搜索成交人数 |
| `touchpoint_traffic_share_*` | % | evaluation-* | 触点资源分布（通投/UGC/品牌广告/达人营销） |
| `product_industry_rank` | 名次 | product-productOverview | 商品行业排名 |
| `product_new_sales` / `_main_sales` / `_regular_sales` | 元 | product-productOverview-productStructure | 货品结构（新品/主推品/常规品销售额） |
| `product_brandsale_account` / `_talent_account` | 元 | product-productOverview-sellMatrix | 带货矩阵（企业号/达人号销售额） |
| `product_general_mall` / `_information_flow` | 元 | product-productOverview-trafficSources | 流量来源（泛商城/信息流销售额） |
| `member_amount` / `_active_amount` | 元 | home-overview | 会员金额 / 月活会员金额 |

### 2.4 mvp_change_event：动作日志（v1.4 双轨改造）

> **v1.4 核心改造**：动作日志改为**双轨**——用户登记（轨 A）+ 平台被动抓取（轨 B），通过 `source` 字段区分。

```sql
CREATE TABLE IF NOT EXISTS mvp_change_event (
    id                      BIGSERIAL PRIMARY KEY,
    sku_id                  VARCHAR(64) REFERENCES mvp_sku(id) ON DELETE CASCADE,  -- v1.4: 允许 NULL（品牌策略类不绑 SKU）
    asset_type              VARCHAR(32) NOT NULL,
    action_subtype          VARCHAR(64),                     -- v1.4: 子类型（如"上架新 SKU" / "改库存" / "评价回复"）
    change_description      VARCHAR(500) NOT NULL,
    screenshot_path         TEXT,
    optimization_intent     VARCHAR(64),
    expected_kpis           JSONB DEFAULT '[]',
    executed_at             TIMESTAMPTZ NOT NULL,
    end_at                  TIMESTAMPTZ,                     -- v1.4: 动作结束时间（可空，长期生效填空）
    actor                   VARCHAR(32) DEFAULT 'owner',
    source                  VARCHAR(32) DEFAULT 'user_manual', -- v1.4: 双轨来源
    source_run_id           VARCHAR(64),                     -- v1.4: 如来自抓取，关联 mvp_runbook_run.id
    target_sku_ids          JSONB DEFAULT '[]',              -- v1.4: 多 SKU 影响（如全店调价同时影响多 SKU）
    target_platform         VARCHAR(32) DEFAULT 'douyin',    -- v1.4: 影响平台（douyin / qianchuan / multiple）
    source_decision_log_id  BIGINT,                          -- 软引用 mvp_decision_log
    verification_status     VARCHAR(32) DEFAULT 'pending',
    notes                   TEXT,
    raw_log                 JSONB,                           -- v1.4: 来自轨 B 时存原始日志
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mvp_event_sku_time ON mvp_change_event(sku_id, executed_at DESC);
CREATE INDEX idx_mvp_event_verification ON mvp_change_event(verification_status, executed_at);
CREATE INDEX idx_mvp_event_source_time ON mvp_change_event(source, executed_at DESC);
CREATE INDEX idx_mvp_event_asset_type ON mvp_change_event(asset_type, executed_at DESC);

-- asset_type 枚举（v1.4 12 类）：
--   product / asset / price / ad / content / audience / talent / service / campaign / shop_ops / user_reach / brand_strategy
--
-- source 枚举（v1.4 4 类）：
--   user_manual       用户主动登记（轨 A）
--   shop_admin_log    抖店后台抓取（轨 B：库存变更/评价回复/活动报名/内容发布等）
--   compass_log       罗盘抓取（极少）
--   yuntu_log         云图抓取（5A 人群包变更/触点结构调整/AIMars 建议采纳）
--
-- optimization_intent 枚举：click / cvr / impression / bounce / aov / refund / experience / 5a_flow / other
-- verification_status 枚举：pending / running / completed / skipped
```

### 2.5 mvp_verification：前后对比结果

```sql
CREATE TABLE IF NOT EXISTS mvp_verification (
    id                  BIGSERIAL PRIMARY KEY,
    change_event_id     BIGINT NOT NULL UNIQUE REFERENCES mvp_change_event(id) ON DELETE CASCADE,
    pre_window_start    TIMESTAMPTZ NOT NULL,
    pre_window_end      TIMESTAMPTZ NOT NULL,
    post_window_start   TIMESTAMPTZ NOT NULL,
    post_window_end     TIMESTAMPTZ NOT NULL,
    kpi_deltas          JSONB NOT NULL,
    verdict             VARCHAR(32),
    summary             TEXT,
    confidence          NUMERIC(4, 3),
    verified_at         TIMESTAMPTZ DEFAULT NOW()
);

-- verdict 枚举：positive / negative / neutral / inconclusive
```

### 2.6 mvp_decision_log：AI 决策日志

```sql
CREATE TABLE IF NOT EXISTS mvp_decision_log (
    id                      BIGSERIAL PRIMARY KEY,
    source_module           VARCHAR(64) NOT NULL,
    source_run_id           VARCHAR(64),
    sku_id                  VARCHAR(64) REFERENCES mvp_sku(id) ON DELETE SET NULL,
    type                    VARCHAR(32),
    title                   VARCHAR(200) NOT NULL,
    summary                 TEXT,
    full_content            TEXT,
    status                  VARCHAR(32) DEFAULT 'pending',
    adopted_at              TIMESTAMPTZ,
    rejected_reason         TEXT,
    postponed_until         DATE,
    linked_change_event_id  BIGINT REFERENCES mvp_change_event(id) ON DELETE SET NULL,
    verified_at             TIMESTAMPTZ,
    verification_result     JSONB,
    meta                    JSONB DEFAULT '{}',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mvp_decision_status ON mvp_decision_log(status, created_at DESC);
CREATE INDEX idx_mvp_decision_sku ON mvp_decision_log(sku_id, created_at DESC);

-- source_module: roundtable / chat / scout_anomaly / manual_diagnosis / ad_review / other
-- type: diagnosis / suggestion / anomaly / experiment
-- status: pending / adopted / rejected / postponed / executing / verified
```

### 2.7 mvp_anomaly：异动事件

```sql
CREATE TABLE IF NOT EXISTS mvp_anomaly (
    id                      BIGSERIAL PRIMARY KEY,
    sku_id                  VARCHAR(64) NOT NULL REFERENCES mvp_sku(id) ON DELETE CASCADE,
    detected_at             TIMESTAMPTZ DEFAULT NOW(),
    severity                VARCHAR(32),                      -- urgent / warning / positive
    metric_name             VARCHAR(64),
    rule_id                 VARCHAR(64),                      -- 哪条规则触发的（详见 §6.4）
    description             TEXT,
    delta_pct               NUMERIC(8, 4),
    handled                 BOOLEAN DEFAULT FALSE,
    handled_at              TIMESTAMPTZ,
    related_decision_log_id BIGINT REFERENCES mvp_decision_log(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mvp_anomaly_unhandled ON mvp_anomaly(handled, severity, detected_at DESC);
```

### 2.8 mvp_runbook_run：巡店执行记录

```sql
CREATE TABLE IF NOT EXISTS mvp_runbook_run (
    id              VARCHAR(64) PRIMARY KEY,                  -- UUID
    runbook_name    VARCHAR(128) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    status          VARCHAR(32),                              -- running / success / failed / partial
    error           TEXT,
    log_path        TEXT,
    metadata        JSONB DEFAULT '{}'                        -- 各 step 状态
);

CREATE INDEX idx_mvp_run_name_time ON mvp_runbook_run(runbook_name, started_at DESC);
```

### 2.9 mvp_session：登录态（v1.4 三平台）

```sql
CREATE TABLE IF NOT EXISTS mvp_session (
    platform        VARCHAR(32) PRIMARY KEY,                  -- 'douyin_compass' / 'douyin_shop_admin' / 'yuntu'
    storage_path    TEXT NOT NULL,
    last_login_at   TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    health          VARCHAR(32) DEFAULT 'unknown',            -- ok / expired / error
    notes           TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- v1.4 备注：
-- 1. douyin_compass + douyin_shop_admin 共用 cookie，但分开存档便于独立续期
-- 2. yuntu 是独立登录系统（巨量云图账号体系）
INSERT INTO mvp_session (platform, storage_path) VALUES
  ('douyin_compass', './sessions/douyin_compass.json'),
  ('douyin_shop_admin', './sessions/douyin_shop_admin.json'),
  ('yuntu', './sessions/yuntu.json')
ON CONFLICT (platform) DO NOTHING;
```

### 2.10 mvp_industry_benchmark：行业基线（v1.4 新增）

> **价值**：罗盘"行业均值/优于同行 X%" + 云图"对比品牌均值/行业排名" 都需要这张表存放基线值，每日快照。

```sql
CREATE TABLE IF NOT EXISTS mvp_industry_benchmark (
    date            DATE NOT NULL,
    category_id     VARCHAR(64) NOT NULL,                    -- 行业类目 ID
    metric_name     VARCHAR(64) NOT NULL,
    industry_avg    NUMERIC(20, 6),                          -- 行业均值
    industry_top    NUMERIC(20, 6),                          -- 优秀均值
    shop_value      NUMERIC(20, 6),                          -- 本店实际值
    percentile      NUMERIC(8, 4),                           -- 优于同行 X%（0-1）
    industry_rank   INTEGER,                                 -- 行业排名（云图独有）
    source          VARCHAR(32),                             -- 'compass' / 'yuntu'
    raw             JSONB,
    PRIMARY KEY (date, category_id, metric_name)
);

CREATE INDEX idx_benchmark_metric_time ON mvp_industry_benchmark(metric_name, date DESC);
```

### 2.11 mvp_stock_change_log：库存变更记录镜像（v1.4 新增）

> **来源**：抖店后台 g-stock-manage-list - 库存变更记录页。**MVP 双轨动作日志的"轨 B"主要数据源**之一。

```sql
CREATE TABLE IF NOT EXISTS mvp_stock_change_log (
    id              BIGSERIAL PRIMARY KEY,
    sku_id          VARCHAR(64) NOT NULL REFERENCES mvp_sku(id) ON DELETE CASCADE,
    change_at       TIMESTAMPTZ NOT NULL,
    change_type     VARCHAR(32),                             -- 'manual_set' / 'auto_lock' / 'sale_release' / 'restock' / 'cancel_release'
    delta           INTEGER,                                  -- 变更量（正/负）
    before_stock    INTEGER,
    after_stock     INTEGER,
    operator        VARCHAR(64),                             -- 操作人（来自抖店后台日志）
    source          VARCHAR(32) DEFAULT 'shop_admin_log',
    source_run_id   VARCHAR(64),
    raw_log         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stock_change_sku ON mvp_stock_change_log(sku_id, change_at DESC);
CREATE INDEX idx_stock_change_type ON mvp_stock_change_log(change_type, change_at DESC);
```

### 2.12 mvp_5a_asset_daily：5A 资产日快照（v1.4 新增）

> **来源**：云图 assets-crowd-distribution。**MVP 品牌资产视角的核心表**，是 omni-vibe 5A 心电图看板的唯一数据源。

```sql
CREATE TABLE IF NOT EXISTS mvp_5a_asset_daily (
    date                DATE NOT NULL,
    brand_id            VARCHAR(64) NOT NULL,                -- 品牌（如 'WADAKAN_HETIANKUAN'）
    sku_id              VARCHAR(64),                          -- NULL = 品牌级；非空 = 商品级 SPU 5A
    -- 6 张 5A 大卡
    o_count             BIGINT,                              -- O 机会人群
    a1_aware            BIGINT,                              -- A1 了解（Aware）
    a2_appeal           BIGINT,                              -- A2 吸引（Appeal）
    a3_ask              BIGINT,                              -- A3 问询（Ask）
    a4_act              BIGINT,                              -- A4 行动（Act）
    a5_advocate         BIGINT,                              -- A5 拥护（Advocate）
    total_5a            BIGINT,                              -- 5A 总资产 = a1+a2+a3+a4+a5
    -- 行业对比
    o_industry_avg      BIGINT,
    a1_industry_avg     BIGINT,
    a2_industry_avg     BIGINT,
    a3_industry_avg     BIGINT,
    a4_industry_avg     BIGINT,
    a5_industry_avg     BIGINT,
    total_industry_avg  BIGINT,
    -- 超过同行业 X%
    a1_outperform_pct   NUMERIC(6, 4),
    a2_outperform_pct   NUMERIC(6, 4),
    a3_outperform_pct   NUMERIC(6, 4),
    a4_outperform_pct   NUMERIC(6, 4),
    a5_outperform_pct   NUMERIC(6, 4),
    total_outperform_pct NUMERIC(6, 4),
    -- AI 总结（云图自带）
    ai_summary          TEXT,
    raw                 JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, brand_id, sku_id)
);

CREATE INDEX idx_5a_asset_brand_date ON mvp_5a_asset_daily(brand_id, date DESC);
CREATE INDEX idx_5a_asset_sku_date ON mvp_5a_asset_daily(sku_id, date DESC) WHERE sku_id IS NOT NULL;
```

### 2.13 mvp_5a_flow_daily：5A 流转日快照（v1.4 新增）

> **来源**：云图 assets-crowd-flow。**6 大场景流转 + 行业对比**，是 omni-vibe "6 场景化策略卡"的数据源。

```sql
CREATE TABLE IF NOT EXISTS mvp_5a_flow_daily (
    date                DATE NOT NULL,
    brand_id            VARCHAR(64) NOT NULL,
    sku_id              VARCHAR(64),                          -- NULL = 品牌级；非空 = 商品级
    scene               VARCHAR(32) NOT NULL,                 -- 'acquire' / 'reservoir' / 'seed' / 'live_convert' / 'seed_convert' / 'repurchase'
    flow_count          BIGINT,                              -- 该场景流转人数
    industry_avg        BIGINT,
    outperform_pct      NUMERIC(6, 4),                       -- 超过同行业 X%
    -- 沙基图明细（O→A1, A1→A2, ... 之间的人数）
    flow_detail         JSONB,
    raw                 JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, brand_id, sku_id, scene)
);

CREATE INDEX idx_5a_flow_brand_date ON mvp_5a_flow_daily(brand_id, scene, date DESC);

-- scene 枚举（对应云图 6 大场景）：
--   acquire        拉新 O→5A
--   reservoir      蓄水 O→A1/A2
--   seed           种草 O/A1/A2→A3
--   live_convert   直播转化 O→A4/A5
--   seed_convert   种草转化 A3→A4/A5
--   repurchase     复购 A4→A5
```

### 2.14 mvp_brand_mind_daily：品牌心智日快照（v1.4 新增）

> **来源**：云图 image-mind-monitor。

```sql
CREATE TABLE IF NOT EXISTS mvp_brand_mind_daily (
    date                DATE NOT NULL,
    brand_id            VARCHAR(64) NOT NULL,
    sku_id              VARCHAR(64),                          -- NULL = 品牌级；非空 = 商品级
    -- 3 大核心指标
    brand_assoc_count   BIGINT,                              -- 联想量
    industry_share      NUMERIC(8, 6),                       -- 行业联想份额（0-1）
    industry_rank       INTEGER,                             -- 联想份额行业排名
    reputation          NUMERIC(8, 6),                       -- 美誉度
    preference          NUMERIC(8, 6),                       -- 偏爱度
    -- 5A 心电图（仅品牌级有）
    dwell               INTEGER,                             -- 停留
    connection          INTEGER,                             -- 联想
    increase            INTEGER,                             -- 增长
    raw                 JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, brand_id, sku_id)
);

CREATE INDEX idx_mind_brand_date ON mvp_brand_mind_daily(brand_id, date DESC);
```

### 2.15 创建脚本

放置于 `migrations/path-a-mvp/001-create-mvp-tables.sql`，由 dev-start.ps1 启动时自动执行。

---

## 三、scout-agent 服务

### 3.1 目录结构

```
services/scout-agent/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置（端口/数据库/通知）
│   ├── database.py              # asyncpg 连接池
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── runbooks.py          # GET/POST /runbooks
│   │   ├── runs.py              # GET /runs, POST /runs/{id}/retry
│   │   ├── sessions.py          # GET/POST /sessions/douyin/relogin
│   │   ├── anomalies.py         # GET /anomalies
│   │   └── health.py
│   ├── services/
│   │   ├── runbook_loader.py    # 加载 YAML
│   │   ├── runbook_executor.py  # 执行 Playwright 步骤
│   │   ├── csv_parser.py        # CSV → daily_metric
│   │   ├── anomaly_engine.py    # 异动检测
│   │   ├── verification.py      # 7 天前后对比
│   │   ├── notification/        # NotificationChannel 抽象（v1.5）
│   │   │   ├── base.py          # NotificationChannel 接口
│   │   │   ├── inapp.py         # 默认：前端站内通知（写 mvp_notification 表）
│   │   │   ├── browser_push.py  # 浏览器原生通知
│   │   │   ├── wecom.py         # 企微 webhook（端口预留，WECOM_WEBHOOK_URL 为空时不启用）
│   │   │   ├── email.py         # 邮件（预留接口，未实现）
│   │   │   └── dispatcher.py    # 按可用通道广播
│   │   └── llm_vision.py        # Gemini 视觉读图
│   ├── schemas/
│   │   ├── ai.py
│   │   └── runbook.py           # YAML 模型
│   └── scheduler.py             # APScheduler 定时
├── runbooks/
│   └── douyin/
│       ├── single_product.yaml          # 单品概览
│       ├── traffic_source.yaml          # 流量来源
│       ├── reviews.yaml                 # 评价管理
│       └── product_weight.yaml          # 商品权重分（视觉）
├── sessions/                            # storage_state.json 存放
│   └── .gitkeep
├── downloads/                           # 临时 CSV
│   └── .gitkeep
├── snapshots/                           # 截图归档
│   └── .gitkeep
├── pyproject.toml
└── Dockerfile
```

### 3.2 核心代码骨架

#### 3.2.1 main.py

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.database import init_db, close_db
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import runbooks, runs, sessions, anomalies, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()
    await close_db()


app = FastAPI(title="Omni Scout Agent", version="1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(runbooks.router, prefix="/api/v1/scout")
app.include_router(runs.router, prefix="/api/v1/scout")
app.include_router(sessions.router, prefix="/api/v1/scout")
app.include_router(anomalies.router, prefix="/api/v1/scout")
```

#### 3.2.2 runbook_executor.py（关键骨架）

```python
"""
Runbook 执行器：
  - 加载 YAML
  - 启动 Playwright（持久 storage_state）
  - 按 step 顺序执行
  - 每 step 失败重试 3 次（指数退避）
  - 全程日志 + 截图归档
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import yaml

from app.services.notify import send_failure_alert
from app.services.csv_parser import parse_and_write
from app.services.llm_vision import vision_extract


class RunbookExecutor:
    def __init__(self, runbook_path: Path):
        self.runbook = yaml.safe_load(runbook_path.read_text(encoding="utf-8"))
        self.run_id = generate_uuid()
        self.results = {}

    async def run(self):
        await self._record_start()

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch_persistent_context(
                    user_data_dir=f"./sessions/{self.runbook['platform']}",
                    headless=False,  # 必须有头，避开抖店反爬
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = browser.pages[0] if browser.pages else await browser.new_page()

                if not await self._check_session(page):
                    await send_failure_alert("session_expired", self.runbook["name"])
                    await self._record_end(status="failed", error="session_expired")
                    return

                for step in self.runbook["steps"]:
                    await self._exec_step(page, step)

                await browser.close()

            await self._record_end(status="success")

        except Exception as e:
            await send_failure_alert("execution_error", self.runbook["name"], str(e))
            await self._record_end(status="failed", error=str(e))
            raise

    async def _exec_step(self, page, step):
        action = step["action"]
        for attempt in range(3):
            try:
                if action == "goto":
                    await page.goto(step["url"], wait_until="networkidle")
                elif action == "click_then_select":
                    await page.click(step["selector"])
                    await page.click(f'[data-value="{step["value"]}"]')
                elif action == "click_and_download":
                    async with page.expect_download() as dl_info:
                        await page.click(step["selector"])
                    download = await dl_info.value
                    save_path = step["save_to"].format(date=today_str())
                    await download.save_as(save_path)
                    self.results[step["id"]] = save_path
                elif action == "parse_csv":
                    csv_path = self.results.get(step.get("file_from"), step["file"])
                    await parse_and_write(csv_path, step["schema"], step["write_to"], self.run_id)
                elif action == "screenshot":
                    save_path = step["save_to"].format(date=today_str())
                    el = await page.query_selector(step["selector"])
                    await el.screenshot(path=save_path)
                    self.results[step["id"]] = save_path
                elif action == "llm_vision":
                    img_path = self.results.get(step.get("image_from"), step["image"])
                    extracted = await vision_extract(img_path, step["prompt"])
                    await write_observation(self.run_id, step["id"], extracted)
                else:
                    raise ValueError(f"Unknown action: {action}")
                return
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
```

#### 3.2.3 anomaly_engine.py

```python
"""
异动检测：每天数据入库后跑一遍。
基于 PRD §4.1.4 的 6 条规则，写入 mvp_anomaly + 触发 mvp_decision_log。
"""

from datetime import date, timedelta

ANOMALY_RULES = [
    {
        "id": "gmv_drop_25",
        "metric": "gmv",
        "condition": lambda today, avg7: today < avg7 * 0.75,
        "severity": "urgent",
        "template": "GMV 跌幅 {delta_pct:.0f}%（vs 7 日均值）",
    },
    {
        "id": "gmv_surge_50",
        "metric": "gmv",
        "condition": lambda today, avg7: today > avg7 * 1.5,
        "severity": "positive",
        "template": "GMV 涨幅 {delta_pct:.0f}%",
    },
    {
        "id": "ctr_3day_decline",
        "metric": "ctr",
        "condition": lambda today, *_: _is_consecutive_decline(today, 3),
        "severity": "urgent",
        "template": "CTR 连续 3 天下滑",
    },
    # ... 其他 3 条
]

async def detect_anomalies_for_sku(sku_id: str, run_id: str):
    today = date.today() - timedelta(days=1)
    metrics = await fetch_metrics(sku_id, today, days_back=7)
    fired = []
    for rule in ANOMALY_RULES:
        if rule["condition"](metrics["today"][rule["metric"]], metrics["avg7"][rule["metric"]]):
            anomaly_id = await write_anomaly(sku_id, rule, metrics)
            fired.append(anomaly_id)
            # 自动建一条 decision_log（pending）让用户处理
            await write_decision_log(
                source_module="scout_anomaly",
                source_run_id=run_id,
                sku_id=sku_id,
                type="anomaly",
                title=rule["template"].format(**metrics),
                summary=f"SKU {sku_id} 触发规则 {rule['id']}",
                related_anomaly_id=anomaly_id,
            )
    return fired
```

#### 3.2.4 verification.py（7 天后跑前后对比）

```python
"""
每天 02:00 跑：找所有 verification_status=pending 且 executed_at 距今 ≥ 7 天的 change_event，
跑前后窗口对比 → 写 mvp_verification → 联动 decision_log 状态变更为 verified。
"""

from datetime import datetime, timedelta

async def run_pending_verifications():
    pending = await fetch_pending_change_events(min_age_days=7)
    for event in pending:
        await verify_one(event)

async def verify_one(event):
    pre_start = event["executed_at"] - timedelta(days=7)
    pre_end = event["executed_at"]
    post_start = event["executed_at"]
    post_end = event["executed_at"] + timedelta(days=7)

    pre = await aggregate_metrics(event["sku_id"], pre_start, pre_end)
    post = await aggregate_metrics(event["sku_id"], post_start, post_end)

    deltas = {}
    for kpi in ["ctr", "cvr", "gmv", "uv"]:
        pre_v = pre.get(kpi, 0)
        post_v = post.get(kpi, 0)
        deltas[kpi] = {
            "pre": pre_v,
            "post": post_v,
            "delta_abs": post_v - pre_v,
            "delta_pct": ((post_v - pre_v) / pre_v * 100) if pre_v else 0,
        }

    improved = sum(1 for d in deltas.values() if d["delta_pct"] >= 10)
    declined = sum(1 for d in deltas.values() if d["delta_pct"] <= -10)
    if improved >= 3:
        verdict = "positive"
    elif declined >= 3:
        verdict = "negative"
    else:
        verdict = "neutral"

    summary = await llm_summarize_verification(deltas, event)
    await write_verification(event["id"], pre_start, pre_end, post_start, post_end, deltas, verdict, summary)
    await update_change_event_status(event["id"], "completed")
    await link_decision_log_verification(event["source_decision_log_id"], deltas, verdict, summary)
```

### 3.3 三平台 8 份 Runbook（v1.4 终版）

> **结构调整**：原 §3.3 描述的"抖店罗盘 4 份 runbook"已扩展为 **3 平台 8 份 runbook**。下面保留原 4 份 YAML 作为**模板范例**，但 v1.4 实际 runbook 结构按 §13.4.1 的 8 份组织：A 全店日报 / B SKU 详情 / C 客服与原声 / D 搜索与流量与营销 / E 人群与机会 / F 物流与履约 / G 品牌心智 / H 品牌资产+触点效能。
>
> **目录结构**（v1.4）：
> ```
> services/scout-agent/runbooks/
>   ├── compass/             # 罗盘子任务（被 8 份 runbook 引用）
>   │   ├── home.yaml
>   │   ├── business-part.yaml
>   │   ├── ... 12 个页面
>   ├── shop-admin/          # 抖店后台子任务
>   │   ├── homepage-todo.yaml
>   │   ├── g-list.yaml
>   │   ├── ... 8 个页面
>   ├── yuntu/               # 云图子任务
>   │   ├── home-overview.yaml
>   │   ├── 5a-asset.yaml
>   │   ├── 5a-flow.yaml
>   │   ├── ... 9 个页面
>   └── runbook-suite/       # 8 份 runbook（编排子任务）
>       ├── A-daily-report.yaml
>       ├── B-sku-detail.yaml
>       ├── C-service-voice.yaml
>       ├── D-search-traffic-marketing.yaml
>       ├── E-audience-opportunity.yaml
>       ├── F-logistics-fulfillment.yaml
>       ├── G-brand-mind.yaml
>       └── H-brand-asset-touchpoint.yaml
> ```

下面保留**原 4 份罗盘 runbook YAML** 作为模板。v1.4 新增的抖店后台和云图 runbook 沿用同一结构（differ in `platform` / `session.storage_state` / `steps.url`）。



#### 3.3.1 单品概览

```yaml
# services/scout-agent/runbooks/douyin/single_product.yaml
name: 抖店日报-单品概览
schedule: "30 8 * * *"
platform: douyin
shop_id_env: DOUYIN_SHOP_ID

session:
  storage_state: ./sessions/douyin
  recheck_url: https://compass.jinritemai.com/shop/home
  on_expired: notify_dispatcher  # v1.5: NotificationChannel 抽象，按 .env 自动选可用通道

steps:
  - id: navigate
    action: goto
    url: https://compass.jinritemai.com/shop/product/single-overview

  - id: filter_yesterday
    action: click_then_select
    selector: "#date-picker"
    value: yesterday

  - id: filter_skus
    action: multi_select
    selector: ".product-search-input"
    values_env: MVP_DOUYIN_PRODUCT_IDS

  - id: export_csv
    action: click_and_download
    selector: 'button:has-text("导出"), button:has-text("下载")'
    save_to: ./downloads/douyin_single_{date}.csv
    timeout: 60000

  - id: parse_csv
    action: parse_csv
    file_from: export_csv
    schema: douyin_single_product_metrics
    write_to: mvp_daily_metric

  - id: detect_anomalies
    action: invoke_anomaly_engine
    sku_filter_env: MVP_SKU_IDS
```

#### 3.3.2 流量来源、评价、权重分（结构同上，selector 不同）

略。详细 YAML 见 `services/scout-agent/runbooks/douyin/`。

### 3.4 调度（APScheduler）

```python
# scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

def start_scheduler():
    # 每天 08:30 触发 4 份 runbook
    for rb in ["single_product", "traffic_source", "reviews", "product_weight"]:
        scheduler.add_job(
            execute_runbook,
            CronTrigger.from_crontab("30 8 * * *"),
            kwargs={"runbook_id": f"douyin/{rb}"},
            id=f"daily-{rb}",
            replace_existing=True,
        )
    # 每天 02:00 跑 7 天后验证
    scheduler.add_job(
        run_pending_verifications,
        CronTrigger.from_crontab("0 2 * * *"),
        id="daily-verification",
        replace_existing=True,
    )
    scheduler.start()
```

---

## 四、API 设计

### 4.1 scout-agent

```
GET  /api/v1/scout/runbooks                    列出所有 runbook
POST /api/v1/scout/runbooks/{id}/run            手动触发一次
GET  /api/v1/scout/runs                         最近 N 次执行列表
GET  /api/v1/scout/runs/{id}                    单次执行详情（含 step 日志）
POST /api/v1/scout/runs/{id}/retry              失败重试

GET  /api/v1/scout/sessions/douyin              查询登录态
POST /api/v1/scout/sessions/douyin/relogin      启动扫码续期（返回 WS URL）

GET  /api/v1/scout/anomalies                    异动事件列表（unhandled 优先）
PATCH /api/v1/scout/anomalies/{id}              标记 handled
```

### 4.2 BFF（前端 Next.js）

```
# 数据查询（直接走 PG）
GET  /api/omni/sku                              SKU 列表
GET  /api/omni/sku/{id}                         单 SKU 详情
GET  /api/omni/sku/{id}/metrics                 14 天指标
GET  /api/omni/sku/{id}/changes                 动作时间轴
GET  /api/omni/sku/{id}/decisions               关联决策

POST /api/omni/changes                          登记新动作
GET  /api/omni/changes/{id}/verification        前后对比卡

# 决策日志
POST /api/omni/decisions                        写入新决策（chat/roundtable 用）
PATCH /api/omni/decisions/{id}                  状态变更（采纳/拒绝/暂缓）

# 巡店代理
GET  /api/omni/scout/runs                       → scout-agent
GET  /api/omni/scout/anomalies                  → scout-agent
POST /api/omni/scout/sessions/relogin           → scout-agent

# 工作台聚合
GET  /api/omni/workspace/today                  今日异动 + 待办 + 巡店状态
GET  /api/omni/workspace/weekly                 本周决策状态
```

### 4.3 数据合约示例

**`POST /api/omni/changes`**：

```json
{
  "sku_id": "SKU-A001",
  "asset_type": "main_image",
  "change_description": "新主图突出零添加场景",
  "screenshot_path": "/uploads/changes/2026-04-30-abc.jpg",
  "optimization_intent": "click",
  "expected_kpis": ["ctr", "cvr"],
  "executed_at": "2026-04-30T10:30:00Z",
  "source_decision_log_id": 42
}
```

**`GET /api/omni/workspace/today`** 返回：

```json
{
  "scout_status": {
    "single_product": "success",
    "traffic_source": "success",
    "reviews": "running",
    "product_weight": "failed"
  },
  "anomalies": [
    { "id": 1, "sku_id": "SKU-A001", "severity": "urgent", "title": "GMV 跌 28%", "rule_id": "gmv_drop_25" }
  ],
  "pending_decisions": [
    { "id": 5, "title": "AI 建议下架素材 G", "source": "scout_anomaly", "sku_id": "SKU-A001" }
  ],
  "completed_verifications": [
    { "change_event_id": 12, "verdict": "positive", "summary": "改主图后 CVR +50%" }
  ]
}
```

---

## 五、前端实施

### 5.1 新增路由（已建占位，本期填充内容）

| 路由 | 占位状态 | 本期内容 |
|---|---|---|
| `/workspace` | ✅ 占位 | 接 `GET /api/omni/workspace/today` |
| `/products` | ✅ 占位 | 接 `GET /api/omni/sku` 列表 |
| `/sku/[id]` | ✅ 3 Tab 骨架 | 填充每个 Tab 的真实内容 |
| `/scout` | ✅ 占位 | 接 `GET /api/omni/scout/runs` 等 |
| `/decisions` | ✅ 已可用（本地） | 增强：双写后端 + 跨设备同步 |

### 5.2 新增组件

```
frontend/src/components/
├── change-event-form.tsx           # 动作登记表单（弹窗或 sheet）
├── change-event-timeline.tsx       # 动作时间轴
├── verification-card.tsx           # 前后对比卡
├── anomaly-card.tsx                # 工作台异动卡片
├── sku-overview-tab.tsx            # SKU 概览 Tab 内容
├── sku-actions-tab.tsx             # SKU 动作 Tab 内容
├── sku-diagnosis-tab.tsx           # SKU AI 诊断 Tab 内容
├── trend-chart.tsx                 # 14 天趋势图（含动作竖线叠加）
├── scout-runbook-list.tsx          # 巡店 runbook 列表
├── scout-run-detail.tsx            # 单次 run 详情
└── relogin-modal.tsx               # 抖店扫码续期弹窗
```

### 5.3 新增 store

```
frontend/src/stores/
├── decisionStore.ts          # ✅ 已建（桥接阶段）
├── skuStore.ts               # 当前选中 SKU 上下文 + 列表缓存
├── changeEventStore.ts       # 动作日志本地缓存
└── scoutStore.ts             # 巡店状态实时数据
```

### 5.4 SKU 详情页 Tab 实现重点

#### 概览 Tab

- 趋势图：用 `recharts` 绘制 4 条线（GMV / UV / CTR / CVR）
- 动作变更竖线：从 `mvp_change_event` 取本 SKU 14 天内事件，在图上画 `<ReferenceLine>`，鼠标悬停 tooltip 显示描述
- 关键指标卡：4 个 metric × 4 个时间窗口（昨日 / 7 日均值 / 14 日均值 / 环比）

#### 动作 Tab

- 时间轴用纵向布局，每个事件一张卡
- 卡片内容：图标（asset_type）+ 时间 + 描述 + 截图缩略图 + 验证徽章
- 点击展开：完整描述 + 大图 + 前后对比卡（如已验证）

#### AI 诊断 Tab

- 已在桥接阶段读 `decisionStore`（本地）
- 本期：双源读取 — 后端 `mvp_decision_log` + localStorage（fallback）
- 「启动深度诊断」按钮：
  - 拉本 SKU 14 天数据 + 动作日志 + 知识库 RAG → 圆桌 4 视角讨论
  - 结果落 `mvp_decision_log` + 显示在列表

---

## 六、关键算法

### 6.1 异动检测规则（PRD §4.1.4，v1.4 终版 13 条）

**罗盘相关 6 条**：

| 规则 ID | 触发条件 | 严重程度 | 模板 |
|---|---|---|---|
| `gmv_drop_25` | 当日 gmv_paid < 7 日均值 × 0.75 | urgent | "用户支付金额跌幅 {delta}% vs 7 日均值" |
| `gmv_surge_50` | 当日 gmv_paid > 7 日均值 × 1.5 | positive | "用户支付金额涨幅 {delta}%" |
| `ctr_3day_decline` | 连续 3 天 CTR 下滑 | urgent | "CTR 连续 3 天下滑" |
| `kpi_3day_improve` | 连续 3 天某指标改善 ≥5%/天 | positive | "{metric} 连续 3 天改善" |
| `zero_traffic` | 当日 UV = 0 或 CTR = 0 | urgent | "异常无流量，可能下架/限流" |
| `negative_reviews` | 当日新增差评（≤2 星）≥3 条 | warning | "新增差评 {n} 条" |

**抖店后台相关 3 条（v1.3）**：

| 规则 ID | 触发条件 | 严重程度 | 模板 |
|---|---|---|---|
| `logistics_overdue_alert` | 当日 logistics_overdue_orders > 3 OR logistics_pickup_avg_hours > 行业均值 × 1.5 | warning | "今日超时单 {n} 单 / 揽收 {h} 小时" |
| `experience_score_drop` | experience_score < 4.0 OR 任一子维下降 ≥ 5 分 | urgent | "体验分降级 {detail}" |
| `todo_overflow` | 待发货 > 5 OR 待售后 > 3 OR 异常订单 > 0 OR 申诉中 > 0 | warning | "店铺待办堆积 {detail}" |

**云图相关 4 条（v1.4）**：

| 规则 ID | 触发条件 | 严重程度 | 模板 |
|---|---|---|---|
| `5a_asset_3day_decline` | 6 卡（O/A1-A5）任一连续 3 天行业百分位下行 | urgent | "{a_stage} 资产规模连续 3 天行业排名下行" |
| `flow_scene_under_industry_30pct` | 6 场景任一场景流转量低于行业均值 30% | warning | "{scene} 场景超同行 X% 持续 < 30%" |
| `mind_3indicator_3day_decline` | 联想量 / 美誉度 / 偏爱度 任一连续 3 天下行 | warning | "{indicator} 心智指标连续 3 天下行" |
| `touchpoint_imbalance_80pct` | 单一触点占比 > 80%（投放结构失衡）| warning | "触点结构失衡：{touchpoint} 占 {pct}%" |

### 6.2 验证 verdict 判定

```
improved = sum(1 for kpi in [ctr, cvr, gmv, uv] if delta_pct >= 10)
declined = sum(1 for kpi in [ctr, cvr, gmv, uv] if delta_pct <= -10)

if improved >= 3:        verdict = "positive"
elif declined >= 3:      verdict = "negative"
elif improved == declined == 0:  verdict = "neutral"
else:                    verdict = "neutral"  # 涨跌互现
```

**置信度 confidence**：基于 pre/post 窗口各自的样本量稳定性（标准差），简化版本用固定值 0.8 即可。

### 6.3 前后对比窗口选择

- 默认：动作执行时点 ± 7 天
- **重要**：前后窗口不能重叠其他动作（即 7 天内多次动作时，verdict 标记为 `inconclusive`）
- 增强（路径 B）：动态窗口、控制对照组

---

## 七、外部集成

### 7.1 抖店反爬应对

| 措施 | 实现 |
|---|---|
| 真实浏览器（非 headless） | `headless=False` |
| 持久 user-data-dir | `launch_persistent_context(user_data_dir=...)` |
| 真实 user-agent | 默认即可（Chrome） |
| 随机延迟 | 每个 step 前 `await asyncio.sleep(random.uniform(1, 3))` |
| 鼠标轨迹 | Playwright 默认轨迹是直线，必要时用 `page.mouse.move()` 模拟 |
| 不开启 webdriver flag | `args=["--disable-blink-features=AutomationControlled"]` |

### 7.2 NotificationChannel 抽象（v1.5 改）

> **MVP 默认不依赖企微**——通过 NotificationChannel 抽象层，按 `.env` 配置自动启用可用通道；企微 webhook 留端口，写到 `.env` 即可生效，无需改代码。

```python
# notification/base.py
from abc import ABC, abstractmethod

class NotificationChannel(ABC):
    name: str
    enabled: bool

    @abstractmethod
    async def send(self, level: str, title: str, body: str, meta: dict = None): ...
```

```python
# notification/inapp.py（默认启用，无需配置）
class InAppChannel(NotificationChannel):
    name = "inapp"
    enabled = True  # 始终启用

    async def send(self, level, title, body, meta=None):
        # 写入 mvp_notification 表，前端通过 SSE / 轮询拉取
        await db.execute("""
          INSERT INTO mvp_notification(level, title, body, meta, created_at)
          VALUES ($1, $2, $3, $4, NOW())
        """, level, title, body, meta or {})
```

```python
# notification/wecom.py（端口预留，WECOM_WEBHOOK_URL 为空时禁用）
class WecomChannel(NotificationChannel):
    name = "wecom"

    def __init__(self):
        self.webhook = settings.wecom_webhook_url
        self.enabled = bool(self.webhook)  # 配置了才启用

    async def send(self, level, title, body, meta=None):
        if not self.enabled:
            return  # 端口未配置，静默
        msg = f"【{title}】\n{body}\n时间: {now()}"
        async with httpx.AsyncClient() as c:
            await c.post(self.webhook, json={"msgtype": "text", "text": {"content": msg}})
```

```python
# notification/dispatcher.py
class NotificationDispatcher:
    def __init__(self):
        self.channels = [InAppChannel(), BrowserPushChannel(), WecomChannel(), EmailChannel()]

    async def broadcast(self, level: str, title: str, body: str, meta: dict = None):
        """向所有 enabled 的通道广播。"""
        for ch in self.channels:
            if ch.enabled:
                try:
                    await ch.send(level, title, body, meta)
                except Exception as e:
                    log.warning(f"Notification {ch.name} failed: {e}")  # 不影响其他通道

# 业务代码：
# await dispatcher.broadcast(
#     level="urgent", title="Omni 巡店告警",
#     body=f"任务: {runbook_name} 失败：{error[:200]}",
#     meta={"runbook": runbook_name}
# )
```

**新增 mvp_notification 表（v1.5）**：
```sql
CREATE TABLE mvp_notification (
  id BIGSERIAL PRIMARY KEY,
  level VARCHAR(16) NOT NULL,           -- 'info' / 'warning' / 'urgent'
  title VARCHAR(200) NOT NULL,
  body TEXT,
  meta JSONB,
  read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notif_unread ON mvp_notification(read, created_at DESC) WHERE NOT read;
```

### 7.3 LLM 视觉读图

复用 ai-provider-hub 的 Gemini provider：

```python
async def vision_extract(image_path: str, prompt: str) -> dict:
    base64_img = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/png", "data": base64_img}},
            ],
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    resp = await httpx.post(
        "http://ai-provider-hub:8001/api/v1/ai/chat/structured",
        json={"provider": "gemini", "model": "gemini-3-flash-preview", "body": body},
    )
    return resp.json()["data"]
```

---

## 八、任务拆解（**32 天 ticket 列表，v1.4 终版**）

### Phase 1: scout-agent 框架（Day 1-3）

| ID | 标题 | 工时 | 依赖 |
|---|---|---|---|
| T01 | 创建 services/scout-agent 服务骨架（FastAPI + asyncpg） | 4h | - |
| T02 | 设计 mvp_* **15 张表**（v1.5）+ migration SQL：含 mvp_5a_asset_daily / _flow_daily / _stock_change_log / _industry_benchmark / _brand_mind_daily / **mvp_notification（v1.5 新增）** + mvp_sku 加 in_focus_pool/focus_reason/locked_by_user 字段 + 写入 dev-start.ps1 | 5h | - |
| T03 | runbook YAML 模型定义（pydantic）+ 三平台子任务编排器 | 3h | T01 |
| T04 | runbook_executor 核心：goto / click / download / parse_csv / parse_html_table / extract_5a_card | 8h | T01, T03 |
| T05 | **三平台 storage_state 持久化**（罗盘+抖店后台共用 cookie / 云图独立）+ 三套登录态健康检查 | 5h | T04 |
| T06 | docker-compose.yml 加 scout-agent 服务 + 暴露 8009 | 2h | T01 |

### Phase 2: 数据底座（Day 4-6）

| ID | 标题 | 工时 |
|---|---|---|
| T07 | csv_parser.py：CSV → mvp_daily_metric（v1.4 metric_name 全枚举支持） | 5h |
| T08 | html_parser.py：HTML 表格抽取通用工具（用于云图沙基图 / 触点 TOP10 等）| 4h |
| T09 | **anomaly_engine.py 13 条规则实现**（v1.4 含 5A 资产 / 6 场景流转 / 品牌心智 / 触点失衡 / 行业排名）| 5h |
| T10 | runs / sessions API endpoints | 3h |
| T11 | benchmark_loader.py：行业均值 / 优秀均值 / 行业排名 / 对比品牌均值 写入 mvp_industry_benchmark | 3h |
| T11b | **sku_bootstrapper.py（v1.5 新增）**：从抖店后台 g-list 全量同步 SKU 主数据到 mvp_sku；id 由 douyin_product_id 派生；启动时执行一次 + 每天 08:00 增量更新 | 4h |
| T11c | **focus_pool_builder.py（v1.5 新增）**：每周日 23:00 重排"重点池"（GMV TOP 5 + 衰退 TOP 2 + 新品 TOP 2 + 老板锁定 ≤5）+ 前端可见的 focus_reason 标签 | 3h |

### Phase 3: 罗盘 runbook（Day 7-12）

> 12 个页面：home / business-part / sell-analysis / refund-analysis / ecology-experience-score / commodity-product-list / product-detail / service-customer-analysis / service-user-sound / search-drainage-terms / biz-center-business-center-crowd-user-buy / logistics-diagnosis-index

| ID | 标题 | 工时 |
|---|---|---|
| T12 | 罗盘 home + business-part runbook | 5h |
| T13 | sell-analysis + refund-analysis runbook | 5h |
| T14 | ecology-experience-score + 4 子维体验分 | 4h |
| T15 | commodity-product-list（全店 SKU 看版） | 4h |
| T16 | **product-detail 7 Tab**（重点池 ~9 SKU 各跑一份；非重点池按需触发）| 8h |
| T17 | service-customer-analysis + service-user-sound（差评摘要 LLM） | 6h |
| T18 | search-drainage-terms + biz-center-用户偏好 | 6h |
| T19 | logistics-diagnosis-index + 罗盘联调 | 4h |

### Phase 4: 抖店后台 runbook + 双轨动作日志（Day 13-19）

> 8 页面：mshop-homepage-index / g-list / g-stock-manage-list（含库存变更记录）/ growth-common-growth-shelf / maftersale-comment 4 Tab / logistics-project-diagnosis-index 3 Tab / mvip-consumer / 营销活动

| ID | 标题 | 工时 |
|---|---|---|
| T20 | mshop-homepage-index 6 待办数（实时） | 3h |
| T21 | g-list SKU 主数据同步（mvp_sku 字段刷新）| 5h |
| T22 | **g-stock-manage-list 库存变更记录抓取 → mvp_stock_change_log（双轨轨 B 兜底）**| 6h |
| T23 | growth-common-growth-shelf 商品诊断分类 | 3h |
| T24 | maftersale-comment 4 Tab（实拍/视频/优质/邀请）| 5h |
| T25 | logistics-project-diagnosis-index 3 Tab | 5h |
| T26 | mvip-consumer 用户中心 + 会员体系 | 4h |
| T27 | 营销活动 + 优惠券 + 单品直降 + 大促报名 | 5h |
| T28 | **双轨动作日志合并器**（用户登记 + 抖店后台日志去重 / 关联） | 6h |

### Phase 5: 云图 runbook（Day 20-27）

> 9 页面：home-overview / assets-crowd-distribution / assets-crowd-flow / assets-gta-overview / assets-gta-deal / image-mind-monitor / product-productOverview-* / search-overview / evaluation-* (触点效能)

| ID | 标题 | 工时 |
|---|---|---|
| T29 | 云图独立登录态 + cookie 续期 | 4h |
| T30 | home-overview 3 大卡 + 5A 心电图 | 3h |
| T31 | **assets-crowd-distribution 5A 关系资产 6 卡 → mvp_5a_asset_daily**（品牌级） | 6h |
| T32 | **assets-crowd-flow 6 场景流转 + 沙基图 → mvp_5a_flow_daily** | 8h |
| T33 | assets-gta-overview + assets-gta-deal（GMV TO 5A 归因）| 6h |
| T34 | **image-mind-monitor 品牌心智 3 指标 → mvp_brand_mind_daily**（品牌+商品级） | 6h |
| T35 | product-productOverview 4 Tab（货品结构/带货矩阵/流量来源） | 6h |
| T36 | search-overview（品牌搜索 SOV） | 3h |
| T37 | evaluation 触点效能（投放资源分布） | 4h |
| T38 | **SPU 5A**（重点池 ~9 SKU 各跑一份商品级 5A；非重点池按需触发）| 6h |

### Phase 6: 8 份 runbook 整合 + 调度（Day 28-30）

| ID | 标题 | 工时 |
|---|---|---|
| T39 | runbook A 全店日报（罗盘+抖店后台合并） | 4h |
| T40 | runbook B SKU 详情（罗盘+抖店后台+云图三源合并） | 5h |
| T41 | runbook C/D/E/F 整合 | 6h |
| T42 | runbook G 品牌心智 + H 品牌资产+触点效能 | 4h |
| T43 | APScheduler 全部定时配置 + 失败重试 | 3h |
| T44 | **NotificationChannel 抽象 + 4 通道**（inapp 默认 / browser_push / wecom 端口预留 / email 端口预留）+ mvp_notification 表 + dispatcher | 4h |
| T45 | scout-agent 三平台全链路联调 | 4h |

### Phase 7: 前端核心页 + 5A 心电图看板（Day 31-32 前段）

| ID | 标题 | 工时 |
|---|---|---|
| T46 | BFF API：workspace/today（含 5A 心电图 + 6 待办 + 异动 + 6 场景策略卡数据） | 5h |
| T47 | **工作台首页**（5A 心电图卡 + 6 待办数 + 异动卡 + 6 场景策略卡 + 决策待办 + 巡店状态） | 8h |
| T48 | SKU 详情页概览 Tab（含 SPU 5A 心电图 + 商品级心智 + 7 Tab 罗盘字段） | 8h |
| T49 | SKU 详情页动作 Tab（时间轴 + 双轨标记 user_manual / shop_admin_log / yuntu_log） | 5h |
| T50 | SKU 详情页 AI 诊断 Tab | 4h |
| T51 | 动作登记表单（**12 大类** + 双轨提示 + 极简 ≤60 秒） | 6h |
| T52 | 截图上传后端（POST /api/omni/uploads） | 3h |
| T53 | 巡店监控页 `/scout` 真实数据接入 | 3h |

### Phase 8: 动作验证 + 联调 + buffer（Day 32 后段）

| ID | 标题 | 工时 |
|---|---|---|
| T54 | verification.py 7 天后验证 cron | 4h |
| T55 | 前后对比卡组件（含 5A 流转前后对比） | 5h |
| T56 | LLM 一句话总结集成（含云图 AI 总结沿用） | 2h |
| T57 | 端到端联调：三平台登录 → 跑 1 天 → 验收数据 | 6h |
| T58 | 修 bug + 反爬测试 | - |
| T59 | 周末复盘页（PRD 故事 7） | 5h |
| T31 | 文档完善 + 验收清单逐项核对 | 3h |

---

## 九、风险与依赖

### 9.1 高风险项

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 抖店罗盘 selector 失效 | 中 | 高 | 每 runbook 内置健康检查；连续 3 天失败自动告警；保留 LLM 视觉 fallback |
| 三平台反爬识别 | 中 | 高 | 真实浏览器 + 随机延迟 + persistent context；不批量、不并发；夜间静默 |
| Cookie 续期流程不顺畅（v1.4 三平台）| 高 | 中 | 完整设计扫码续期 UI；NotificationChannel 通知 + 一键重跑（罗盘+抖店后台共用 / 云图独立）|
| Gemini API 配额或网络 | 中 | 低 | 视觉分析降级为"截图存档不解析"，不阻塞主流程 |

### 9.2 依赖（v1.5 极简化）

| 依赖 | 提供方 | 说明 | 阻塞？ |
|---|---|---|---|
| 抖店账号 | 老板 | 主店账号，最好二级账号（避免主账号被风控连累） | ✅ 阻塞 |
| 巨量云图账号 | 老板 | 已开通"品牌主"身份（WADAKAN/和田宽 / 食品饮料） | ✅ 阻塞 |
| Gemini API key | 已配置 | 复用现有 | - |
| ~~MVP 5 SKU 真实抖店商品 ID~~（v1.5 删）| ~~老板~~ | **不再需要**——sku_bootstrapper 自动从 g-list 全量同步 | ❌ 不阻塞 |
| 企微 webhook URL（v1.5 改为可选）| 老板（任意时刻补齐）| 写入 `.env WECOM_WEBHOOK_URL` 即生效；MVP 默认走站内通知 | ❌ 不阻塞 |

---

## 十、配置文件

### 10.1 services/scout-agent/.env

```env
# 数据库
DB_HOST=postgres
DB_PORT=5432
DB_NAME=omni
DB_USER=omni
DB_PASSWORD=...

# 抖店（v1.5: 不再需要手动配 SKU 列表，sku_bootstrapper 自动从 g-list 同步）
DOUYIN_SHOP_ID=153xxxxx
# MVP_DOUYIN_PRODUCT_IDS=  # 已废弃 - 系统从 g-list 全量同步
# MVP_SKU_IDS=             # 已废弃 - id 由 douyin_product_id 派生

# 巨量云图（v1.4 新增）
YUNTU_BRAND_ID=WADAKAN_HETIANKUAN
YUNTU_INDUSTRY=food_beverage

# 通知（v1.5: 全部可选，任一不配则该通道静默）
WECOM_WEBHOOK_URL=          # 留空 = 不推企微（用前端站内通知 + 浏览器原生通知代替）
SMTP_HOST=                  # 留空 = 不发邮件
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=

# 通知通道开关（默认全部 enabled，由 .env 实际配置自动判断）
NOTIFICATION_INAPP_ENABLED=true       # 站内通知，默认开（无依赖）
NOTIFICATION_BROWSER_PUSH=true        # 浏览器原生通知，默认开
NOTIFICATION_WECOM_ENABLED=auto       # auto = WECOM_WEBHOOK_URL 非空时自动启用
NOTIFICATION_EMAIL_ENABLED=auto

# AI hub
AI_HUB_URL=http://ai-provider-hub:8001

# 调度
ENABLE_SCHEDULER=true
SCHEDULE_CRON=30 8 * * *
```

### 10.2 docker-compose.yml 新增片段

```yaml
  scout-agent:
    build: ./services/scout-agent
    container_name: omni-scout-agent
    ports:
      - "8009:8009"
    environment:
      - DB_HOST=postgres
      - DB_NAME=omni
    volumes:
      - ./services/scout-agent/sessions:/app/sessions
      - ./services/scout-agent/downloads:/app/downloads
      - ./services/scout-agent/snapshots:/app/snapshots
    depends_on:
      - postgres
      - ai-provider-hub
    restart: unless-stopped
```

---

## 十一、文档关联

| 关联文档 | 作用 |
|---|---|
| `01-PRD-抖店MVP产品需求文档.md` | 业务需求 + 用户故事 |
| `03-验收-抖店MVP验收文档.md` | 测试 case + 验收标准 |
| `04-使用指南-抖店MVP使用指南.md` | 老板日常使用手册 |
| `../路径B-中台底座/02-施工-中台底座工程实施文档.md` | 路径 B 实施细节，包含从 mvp_* 迁移到 omni_* 的 SQL |

---

## 文档变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-04-30 | 初稿 |
