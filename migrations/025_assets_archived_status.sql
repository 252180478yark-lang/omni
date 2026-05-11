-- 2026-05-12 W4-B 14.4 phase D：pipeline.assets 加 archived 状态
--
-- 老板从血缘图归档 asset 时报 CheckViolationError：
--   "new row for relation 'assets' violates check constraint 'assets_status_check'"
--
-- 根因：migrations/021 建表时 assets.status check 只允许 'draft/adopted/
-- published/discarded'，没 'archived'（其他 6 张表都已支持 archived）。
-- 老板归档功能 archive_node UPDATE status='archived' 全表通用，但 assets
-- 的 check 拒收，需要 ALTER 加上。
--
-- 保留 published / discarded（这俩是 W4-A 加分 5 tool dy_publish_creative
-- 投后用的状态，未来还要用）。

ALTER TABLE pipeline.assets
    DROP CONSTRAINT IF EXISTS assets_status_check;

ALTER TABLE pipeline.assets
    ADD CONSTRAINT assets_status_check
    CHECK (status = ANY (ARRAY['draft', 'adopted', 'published', 'discarded', 'archived']));
