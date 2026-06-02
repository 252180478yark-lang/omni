"""W3a T9：CSV 批量导入 accounting.cost_items（绕 Gate）。

为啥绕 Gate：老板手动跑这个脚本本身就是"批"动作；
record_cost 一条条批 Gate 累。

用法：
    docker exec -it omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python /app/scripts/import_costs.py /app/scripts/cost_template.csv"
    # 或：dry-run（只 print 不写）
    docker exec ... python /app/scripts/import_costs.py path.csv --dry-run

CSV 列：sku_id, category, item_name, unit_cost, currency, unit,
       quantity_per_unit, vendor, valid_from, valid_to, notes
（sku_id / vendor / valid_to / notes 可空）
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.database import init_pool, close_pool, get_pool


_VALID_CATS = {"product", "logistics", "partner_quote"}


def _parse_row(row: dict, line_no: int) -> dict | None:
    cat = (row.get("category") or "").strip()
    if cat not in _VALID_CATS:
        print(f"[line {line_no}] skip: bad category {cat!r}", file=sys.stderr)
        return None

    item_name = (row.get("item_name") or "").strip()
    if not item_name:
        print(f"[line {line_no}] skip: empty item_name", file=sys.stderr)
        return None

    try:
        unit_cost = Decimal((row.get("unit_cost") or "0").strip())
        qty_per_unit = Decimal((row.get("quantity_per_unit") or "1").strip() or "1")
    except Exception as exc:
        print(f"[line {line_no}] skip: bad number ({exc})", file=sys.stderr)
        return None

    vf_str = (row.get("valid_from") or "").strip()
    vf = date.fromisoformat(vf_str) if vf_str else date.today()
    vt_str = (row.get("valid_to") or "").strip()
    vt = date.fromisoformat(vt_str) if vt_str else None

    return {
        "id": uuid.uuid4(),
        "sku_id": (row.get("sku_id") or "").strip() or None,
        "category": cat,
        "item_name": item_name,
        "unit_cost": unit_cost,
        "currency": (row.get("currency") or "CNY").strip() or "CNY",
        "unit": (row.get("unit") or "件").strip() or "件",
        "quantity_per_unit": qty_per_unit,
        "vendor": (row.get("vendor") or "").strip() or None,
        "valid_from": vf,
        "valid_to": vt,
        "notes": (row.get("notes") or "").strip() or None,
    }


async def _main(csv_path: Path, dry_run: bool) -> int:
    if not csv_path.exists():
        print(f"csv not found: {csv_path}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # 1 是 header
            parsed = _parse_row(row, i)
            if parsed:
                rows.append(parsed)

    print(f"parsed {len(rows)} rows from {csv_path}")
    if dry_run:
        for r in rows:
            print(f"  [dry] {r['category']:14} {r['item_name']:20} ¥{r['unit_cost']}")
        return 0

    await init_pool()
    pool = get_pool()
    inserted = 0
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for r in rows:
                    await conn.execute(
                        """
                        INSERT INTO accounting.cost_items
                          (id, sku_id, category, item_name, unit_cost, currency,
                           unit, quantity_per_unit, vendor, valid_from, valid_to, notes)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        r["id"], r["sku_id"], r["category"], r["item_name"],
                        r["unit_cost"], r["currency"], r["unit"],
                        r["quantity_per_unit"], r["vendor"], r["valid_from"],
                        r["valid_to"], r["notes"],
                    )
                    inserted += 1
    finally:
        await close_pool()

    print(f"inserted {inserted} rows")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="import_costs")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(_main(args.csv, args.dry_run)))
