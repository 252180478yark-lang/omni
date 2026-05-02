-- Content Pipeline v2 Phase 2
-- ad_review.campaigns 关联 brief / digital_human 用于回灌指标

ALTER TABLE ad_review.campaigns
    ADD COLUMN IF NOT EXISTS brief_id UUID NULL,
    ADD COLUMN IF NOT EXISTS digital_human_id UUID NULL;

CREATE INDEX IF NOT EXISTS idx_campaigns_brief ON ad_review.campaigns (brief_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_digital_human ON ad_review.campaigns (digital_human_id);
