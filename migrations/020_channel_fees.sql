-- migrations/020_channel_fees.sql
-- W4-B 切片 9：渠道扣点表（抖音/天猫/京东等的平台抽点）
--
-- compute_margin 现有 channel_fee_rate 参数默认 0.05（5%），但每个渠道实际
-- 不一样且会变。这表存当前生效的扣点率，compute_margin 不显式传时 fallback
-- 查这里。
--
-- 字段：
--   channel        douyin / tmall / jd / wechat / pdd 等
--   fee_type       percentage（按 GMV %）或 flat（每单固定费）
--   fee_rate       percentage 时是小数（0.02 = 2%）；flat 时是元/单
--   valid_from/to  生效期；价改走新行 + 关旧行（保留历史）
--   is_active      软删
--
-- 录入：手工 SQL INSERT 或调 mcp tool（W4-B 后续切片加）；查询 list_channel_fees。

CREATE TABLE IF NOT EXISTS accounting.channel_fees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel TEXT NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'percentage'
        CHECK (fee_type IN ('percentage', 'flat')),
    fee_rate NUMERIC(8, 6) NOT NULL,
    description TEXT,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT channel_fees_rate_nonneg CHECK (fee_rate >= 0),
    CONSTRAINT channel_fees_valid_range CHECK (
        valid_to IS NULL OR valid_to >= valid_from
    )
);

CREATE INDEX IF NOT EXISTS idx_channel_fees_channel
    ON accounting.channel_fees (channel) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_channel_fees_active
    ON accounting.channel_fees (is_active) WHERE is_active = TRUE;

-- 复用 content_studio.touch_updated_at 触发器
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_channel_fees_touch ON accounting.channel_fees;
        CREATE TRIGGER trg_channel_fees_touch
            BEFORE UPDATE ON accounting.channel_fees
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;

COMMENT ON TABLE accounting.channel_fees IS
    '渠道扣点表（抖音/天猫/京东 平台抽点）；compute_margin 不传 channel_fee_rate 时 fallback 查';

-- 老板今天拍的：抖音 2% 抽点
INSERT INTO accounting.channel_fees (channel, fee_type, fee_rate, description, notes)
VALUES ('douyin', 'percentage', 0.020000,
        '抖店技术服务费', '2026-05-07 老板录入')
ON CONFLICT DO NOTHING;
