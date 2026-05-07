"""W4-B 切片 8：把内部酱油价格表导入 accounting.product_price_list。

来源：F:/和田宽电商/价格表（内部）/酱油价格表.xlsx 的 sheet 1 + sheet 2
（sheet 3 锦百合不导）。

xlsx 解析在 host 端跑（用 pandas），导出 CSV；本脚本只读 CSV 入库（容器内
跑，无 pandas 依赖）。

跑法（两步）：
    # 1. host 端解析 xlsx → CSV（路径见 docs/superpowers/...，或一次性 inline 跑）
    # 2. 容器内导入：
    docker cp E:/tmp/product_prices.csv omni-knowledge-engine:/tmp/product_prices.csv
    docker exec -it omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app \
        python /app/scripts/import_product_prices.py /tmp/product_prices.csv --replace"

CSV 列：vendor, product_name, grade, spec, pack_size, unit_price, case_price, barcode
visibility 自动设 'public'（员工出厂价；老板真实价独立录到 cost_items）。
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.database import close_pool, get_pool, init_pool


def _to_int_or_none(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _to_dec(s: str) -> Decimal | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_row(row: dict) -> dict | None:
    name = (row.get("product_name") or "").strip()
    if not name:
        return None
    unit_price = _to_dec(row.get("unit_price"))
    if unit_price is None or unit_price <= 0:
        return None
    vendor = (row.get("vendor") or "").strip()
    if not vendor:
        return None
    return {
        "product_name": name,
        "grade": (row.get("grade") or "").strip() or None,
        "spec": (row.get("spec") or "").strip() or None,
        "pack_size": _to_int_or_none(row.get("pack_size")),
        "unit_price": unit_price,
        "case_price": _to_dec(row.get("case_price")),
        "barcode": (row.get("barcode") or "").strip() or None,
        "vendor": vendor,
    }


async def _main(csv_path: Path, dry_run: bool, replace: bool) -> int:
    if not csv_path.exists():
        print(f"csv not found: {csv_path}", file=sys.stderr)
        return 2

    parsed: list[dict] = []
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            r = _parse_row(row)
            if r is None:
                print(f"[line {i}] skip", file=sys.stderr)
                continue
            parsed.append(r)

    print(f"total parsed: {len(parsed)} rows from {csv_path}")
    vendors = sorted({r["vendor"] for r in parsed})
    for v in vendors:
        n = sum(1 for r in parsed if r["vendor"] == v)
        print(f"  {v}: {n} rows")

    if dry_run:
        for r in parsed[:8]:
            print(f"  [dry] {r['vendor']:20} {r['product_name']:24} "
                  f"{r['grade'] or '-':10} {r['spec'] or '-':14} "
                  f"¥{r['unit_price']}/瓶 pack={r['pack_size']} bc={r['barcode']}")
        if len(parsed) > 8:
            print(f"  ... +{len(parsed) - 8} more")
        return 0

    await init_pool()
    pool = get_pool()
    inserted = 0
    deleted = 0
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if replace:
                    res = await conn.execute(
                        "DELETE FROM accounting.product_price_list "
                        "WHERE vendor = ANY($1::text[])",
                        vendors,
                    )
                    deleted = int(res.split()[-1]) if res.startswith("DELETE") else 0
                    print(f"replace mode: deleted {deleted} old rows for vendors {vendors}")
                today = date.today()
                for r in parsed:
                    await conn.execute(
                        """
                        INSERT INTO accounting.product_price_list
                          (product_name, grade, spec, pack_size, unit_price,
                           case_price, barcode, vendor, visibility, valid_from)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'public', $9)
                        """,
                        r["product_name"], r["grade"], r["spec"], r["pack_size"],
                        r["unit_price"], r["case_price"], r["barcode"],
                        r["vendor"], today,
                    )
                    inserted += 1
    finally:
        await close_pool()

    print(f"inserted {inserted} rows; replaced {deleted} old rows")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="import_product_prices")
    ap.add_argument("csv", type=Path, help="product_prices.csv 路径（容器内）")
    ap.add_argument("--dry-run", action="store_true", help="只解析不写库")
    ap.add_argument(
        "--replace", action="store_true",
        help="导入前先删同 vendor 的旧行（防重跑累积）",
    )
    args = ap.parse_args()
    sys.exit(asyncio.run(_main(args.csv, args.dry_run, args.replace)))
