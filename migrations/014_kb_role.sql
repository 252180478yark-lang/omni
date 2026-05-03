-- Migration 014: 知识库角色化（kb_role）
--
-- 目标：把 5 类知识库（官方文档/方法论/录音/素材模板/公司文档）的"使用方式"
--      在数据层显式区分。检索路由、prompt 分区、入库管道都依据 kb_role 分流。
--
-- 角色枚举：
--   authoritative  官方文档（千川/云图/抖加/京东/天猫等说明书）—— 严格引用
--   methodology    方法论（管理学/心理学/易经/营销理论）—— 借框架不引事实
--   personal_log   个人录音（面试/员工/客户/谈判转写）—— 摘要式入库
--   template       素材模板（爆款拆解/话术结构）—— 按结构标签检索
--   private_doc    公司文档（公司历史/奖项/产品介绍）—— 标准 RAG
--   general        通用/默认 —— 兜底
--
-- 不在枚举里：private_data（成本/价格走结构化表，不进 KB；阶段二实现）

ALTER TABLE knowledge.knowledge_bases
    ADD COLUMN IF NOT EXISTS kb_role TEXT NOT NULL DEFAULT 'general';

COMMENT ON COLUMN knowledge.knowledge_bases.kb_role IS
    '知识库角色：authoritative/methodology/personal_log/template/private_doc/general';

-- CHECK 约束（用 DO 块是为了重复执行幂等）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'knowledge'
          AND table_name = 'knowledge_bases'
          AND constraint_name = 'knowledge_bases_kb_role_check'
    ) THEN
        ALTER TABLE knowledge.knowledge_bases
            ADD CONSTRAINT knowledge_bases_kb_role_check
            CHECK (kb_role IN ('authoritative','methodology','personal_log','template','private_doc','general'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_kb_role
    ON knowledge.knowledge_bases (kb_role);
