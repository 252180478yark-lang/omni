-- Path A MVP: 15 tables (v1.5)
-- Applied by: python scripts/apply_migrations.py

-- ── mvp_sku ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_sku (
    id                       VARCHAR(64) PRIMARY KEY,
    name                     VARCHAR(200) NOT NULL,
    category                 VARCHAR(100),
    douyin_product_id        VARCHAR(64) NOT NULL UNIQUE,
    douyin_url               TEXT,
    douyin_shop_id           VARCHAR(64),
    source                   VARCHAR(32)  DEFAULT 'shop_admin',
    platform_status          VARCHAR(32),
    total_stock              INTEGER,
    available_stock          INTEGER,
    locked_stock             INTEGER,
    growth_class             VARCHAR(32),
    created_on_platform_at   TIMESTAMPTZ,
    status                   VARCHAR(32)  DEFAULT 'active',
    push_tier                VARCHAR(32),
    in_focus_pool            BOOLEAN      DEFAULT FALSE,
    focus_reason             VARCHAR(64),
    locked_by_user           BOOLEAN      DEFAULT FALSE,
    metadata                 JSONB        DEFAULT '{}',
    created_at               TIMESTAMPTZ  DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mvp_sku_status         ON mvp_sku(status);
CREATE INDEX IF NOT EXISTS idx_mvp_sku_growth_class   ON mvp_sku(growth_class);
CREATE INDEX IF NOT EXISTS idx_mvp_sku_platform_status ON mvp_sku(platform_status);
CREATE INDEX IF NOT EXISTS idx_mvp_sku_focus          ON mvp_sku(in_focus_pool) WHERE in_focus_pool;

-- ── mvp_daily_metric ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_daily_metric (
    id              BIGSERIAL    PRIMARY KEY,
    sku_id          VARCHAR(64)  NOT NULL REFERENCES mvp_sku(id) ON DELETE CASCADE,
    date            DATE         NOT NULL,
    metric_name     VARCHAR(64)  NOT NULL,
    value           NUMERIC(20, 6),
    source_runbook  VARCHAR(128),
    source_run_id   VARCHAR(64),
    raw             JSONB,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (sku_id, date, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_mvp_metric_sku_date  ON mvp_daily_metric(sku_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_mvp_metric_runbook   ON mvp_daily_metric(source_runbook, date DESC);

-- ── mvp_change_event ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_change_event (
    id                      BIGSERIAL    PRIMARY KEY,
    sku_id                  VARCHAR(64)  REFERENCES mvp_sku(id) ON DELETE CASCADE,
    asset_type              VARCHAR(32)  NOT NULL,
    action_subtype          VARCHAR(64),
    change_description      VARCHAR(500) NOT NULL,
    screenshot_path         TEXT,
    optimization_intent     VARCHAR(64),
    expected_kpis           JSONB        DEFAULT '[]',
    executed_at             TIMESTAMPTZ  NOT NULL,
    end_at                  TIMESTAMPTZ,
    actor                   VARCHAR(32)  DEFAULT 'owner',
    source                  VARCHAR(32)  DEFAULT 'user_manual',
    source_run_id           VARCHAR(64),
    target_sku_ids          JSONB        DEFAULT '[]',
    target_platform         VARCHAR(32)  DEFAULT 'douyin',
    source_decision_log_id  BIGINT,
    verification_status     VARCHAR(32)  DEFAULT 'pending',
    notes                   TEXT,
    raw_log                 JSONB,
    created_at              TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mvp_event_sku_time     ON mvp_change_event(sku_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_mvp_event_verification  ON mvp_change_event(verification_status, executed_at);
CREATE INDEX IF NOT EXISTS idx_mvp_event_source_time  ON mvp_change_event(source, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_mvp_event_asset_type   ON mvp_change_event(asset_type, executed_at DESC);

-- ── mvp_verification ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_verification (
    id                  BIGSERIAL    PRIMARY KEY,
    change_event_id     BIGINT       NOT NULL UNIQUE REFERENCES mvp_change_event(id) ON DELETE CASCADE,
    pre_window_start    TIMESTAMPTZ  NOT NULL,
    pre_window_end      TIMESTAMPTZ  NOT NULL,
    post_window_start   TIMESTAMPTZ  NOT NULL,
    post_window_end     TIMESTAMPTZ  NOT NULL,
    kpi_deltas          JSONB        NOT NULL,
    verdict             VARCHAR(32),
    summary             TEXT,
    confidence          NUMERIC(4, 3),
    verified_at         TIMESTAMPTZ  DEFAULT NOW()
);

-- ── mvp_decision_log ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_decision_log (
    id                      BIGSERIAL    PRIMARY KEY,
    source_module           VARCHAR(64)  NOT NULL,
    source_run_id           VARCHAR(64),
    sku_id                  VARCHAR(64)  REFERENCES mvp_sku(id) ON DELETE SET NULL,
    type                    VARCHAR(32),
    title                   VARCHAR(200) NOT NULL,
    summary                 TEXT,
    full_content            TEXT,
    status                  VARCHAR(32)  DEFAULT 'pending',
    adopted_at              TIMESTAMPTZ,
    rejected_reason         TEXT,
    postponed_until         DATE,
    linked_change_event_id  BIGINT       REFERENCES mvp_change_event(id) ON DELETE SET NULL,
    verified_at             TIMESTAMPTZ,
    verification_result     JSONB,
    meta                    JSONB        DEFAULT '{}',
    created_at              TIMESTAMPTZ  DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mvp_decision_status ON mvp_decision_log(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mvp_decision_sku    ON mvp_decision_log(sku_id, created_at DESC);

-- ── mvp_anomaly ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_anomaly (
    id                      BIGSERIAL    PRIMARY KEY,
    sku_id                  VARCHAR(64)  NOT NULL REFERENCES mvp_sku(id) ON DELETE CASCADE,
    detected_at             TIMESTAMPTZ  DEFAULT NOW(),
    severity                VARCHAR(32),
    metric_name             VARCHAR(64),
    rule_id                 VARCHAR(64),
    description             TEXT,
    delta_pct               NUMERIC(8, 4),
    handled                 BOOLEAN      DEFAULT FALSE,
    handled_at              TIMESTAMPTZ,
    related_decision_log_id BIGINT       REFERENCES mvp_decision_log(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mvp_anomaly_unhandled ON mvp_anomaly(handled, severity, detected_at DESC);

-- ── mvp_runbook_run ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_runbook_run (
    id              VARCHAR(64)  PRIMARY KEY,
    runbook_name    VARCHAR(128) NOT NULL,
    started_at      TIMESTAMPTZ  NOT NULL,
    ended_at        TIMESTAMPTZ,
    status          VARCHAR(32),
    error           TEXT,
    log_path        TEXT,
    metadata        JSONB        DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mvp_run_name_time ON mvp_runbook_run(runbook_name, started_at DESC);

-- ── mvp_session ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_session (
    platform        VARCHAR(32)  PRIMARY KEY,
    storage_path    TEXT         NOT NULL,
    last_login_at   TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    health          VARCHAR(32)  DEFAULT 'unknown',
    notes           TEXT,
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO mvp_session (platform, storage_path) VALUES
  ('douyin_compass',    './sessions/douyin_compass.json'),
  ('douyin_shop_admin', './sessions/douyin_shop_admin.json'),
  ('yuntu',             './sessions/yuntu.json')
ON CONFLICT (platform) DO NOTHING;

-- ── mvp_industry_benchmark ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_industry_benchmark (
    date            DATE         NOT NULL,
    category_id     VARCHAR(64)  NOT NULL,
    metric_name     VARCHAR(64)  NOT NULL,
    industry_avg    NUMERIC(20, 6),
    industry_top    NUMERIC(20, 6),
    shop_value      NUMERIC(20, 6),
    percentile      NUMERIC(8, 4),
    industry_rank   INTEGER,
    source          VARCHAR(32),
    raw             JSONB,
    PRIMARY KEY (date, category_id, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_metric_time ON mvp_industry_benchmark(metric_name, date DESC);

-- ── mvp_stock_change_log ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_stock_change_log (
    id              BIGSERIAL    PRIMARY KEY,
    sku_id          VARCHAR(64)  NOT NULL REFERENCES mvp_sku(id) ON DELETE CASCADE,
    change_at       TIMESTAMPTZ  NOT NULL,
    change_type     VARCHAR(32),
    delta           INTEGER,
    before_stock    INTEGER,
    after_stock     INTEGER,
    operator        VARCHAR(64),
    source          VARCHAR(32)  DEFAULT 'shop_admin_log',
    source_run_id   VARCHAR(64),
    raw_log         JSONB,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_change_sku  ON mvp_stock_change_log(sku_id, change_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_change_type ON mvp_stock_change_log(change_type, change_at DESC);

-- ── mvp_5a_asset_daily ────────────────────────────────────────────────────────
-- sku_id = '' means brand-level; non-empty means SKU-level SPU 5A
CREATE TABLE IF NOT EXISTS mvp_5a_asset_daily (
    date                DATE         NOT NULL,
    brand_id            VARCHAR(64)  NOT NULL,
    sku_id              VARCHAR(64)  NOT NULL DEFAULT '',
    o_count             BIGINT,
    a1_aware            BIGINT,
    a2_appeal           BIGINT,
    a3_ask              BIGINT,
    a4_act              BIGINT,
    a5_advocate         BIGINT,
    total_5a            BIGINT,
    o_industry_avg      BIGINT,
    a1_industry_avg     BIGINT,
    a2_industry_avg     BIGINT,
    a3_industry_avg     BIGINT,
    a4_industry_avg     BIGINT,
    a5_industry_avg     BIGINT,
    total_industry_avg  BIGINT,
    a1_outperform_pct   NUMERIC(6, 4),
    a2_outperform_pct   NUMERIC(6, 4),
    a3_outperform_pct   NUMERIC(6, 4),
    a4_outperform_pct   NUMERIC(6, 4),
    a5_outperform_pct   NUMERIC(6, 4),
    total_outperform_pct NUMERIC(6, 4),
    ai_summary          TEXT,
    raw                 JSONB,
    created_at          TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (date, brand_id, sku_id)
);

CREATE INDEX IF NOT EXISTS idx_5a_asset_brand_date ON mvp_5a_asset_daily(brand_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_5a_asset_sku_date   ON mvp_5a_asset_daily(sku_id, date DESC) WHERE sku_id <> '';

-- ── mvp_5a_flow_daily ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_5a_flow_daily (
    date            DATE         NOT NULL,
    brand_id        VARCHAR(64)  NOT NULL,
    sku_id          VARCHAR(64)  NOT NULL DEFAULT '',
    scene           VARCHAR(32)  NOT NULL,
    flow_count      BIGINT,
    industry_avg    BIGINT,
    outperform_pct  NUMERIC(6, 4),
    flow_detail     JSONB,
    raw             JSONB,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (date, brand_id, sku_id, scene)
);

CREATE INDEX IF NOT EXISTS idx_5a_flow_brand_date ON mvp_5a_flow_daily(brand_id, scene, date DESC);

-- ── mvp_brand_mind_daily ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_brand_mind_daily (
    date                DATE         NOT NULL,
    brand_id            VARCHAR(64)  NOT NULL,
    sku_id              VARCHAR(64)  NOT NULL DEFAULT '',
    brand_assoc_count   BIGINT,
    industry_share      NUMERIC(8, 6),
    industry_rank       INTEGER,
    reputation          NUMERIC(8, 6),
    preference          NUMERIC(8, 6),
    dwell               INTEGER,
    connection          INTEGER,
    increase            INTEGER,
    raw                 JSONB,
    created_at          TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (date, brand_id, sku_id)
);

CREATE INDEX IF NOT EXISTS idx_mind_brand_date ON mvp_brand_mind_daily(brand_id, date DESC);

-- ── mvp_notification ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_notification (
    id          BIGSERIAL    PRIMARY KEY,
    level       VARCHAR(16)  NOT NULL,
    title       VARCHAR(200) NOT NULL,
    body        TEXT,
    meta        JSONB,
    read        BOOLEAN      DEFAULT FALSE,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_unread ON mvp_notification(read, created_at DESC) WHERE NOT read;
