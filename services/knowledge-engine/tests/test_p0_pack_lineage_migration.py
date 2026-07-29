from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "migrations" / "097_p0_v4_adopted_pack_lineage.sql"


def test_p0_v4_pack_lineage_migration_is_additive_and_restrictive() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "alter table pipeline.production_orders" in sql
    assert "add column if not exists audience_pack_id uuid" in sql
    assert "references pipeline.audience_packs(id) on delete restrict" in sql
    assert "create index if not exists idx_production_orders_audience_pack_id" in sql
    assert "where audience_pack_id is not null" in sql
    assert "not null" not in sql.split("add column if not exists audience_pack_id uuid", 1)[1].split(";", 1)[0]
