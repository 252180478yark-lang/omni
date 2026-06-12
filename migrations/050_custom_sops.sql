-- Migration 050: mcp.custom_sops（老板自建 SOP 存储）
--
-- 链路：桌面说需求 → chat claude 拟 SOP → 老板确认 → sop_save_custom 入库
--      → 桌面菜单「我的 SOP」展示复用（sop_list_custom）
-- 约定：同名 active 唯一（partial unique index）；重存 = version+1 全量覆盖；
--      下架走 status='archived'（不物理删，留痕）。

CREATE TABLE IF NOT EXISTS mcp.custom_sops (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '🧩 我的 SOP',
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    sop_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_sops_name_active
    ON mcp.custom_sops (name) WHERE status = 'active';

COMMENT ON TABLE mcp.custom_sops IS '老板自建 SOP（桌面拟稿→确认→入库→菜单复用）';

-- updated_at 自动刷新触发器（照抄 047 的防御模式：函数存在才挂）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_mcp_custom_sops_touch ON mcp.custom_sops;
        CREATE TRIGGER trg_mcp_custom_sops_touch
            BEFORE UPDATE ON mcp.custom_sops
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;
