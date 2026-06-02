"""把 pipeline.assets.file_url 是 http(s) cdn url 的资产转存本地磁盘（W4-B 14.4 phase D 候选 D）。

cdn url（火山方舟 seedance/seedream, OpenAI gpt-image）24h 过期 → 老板隔天回头打开 404。
此脚本扫 file_url LIKE 'http%' 的所有 asset，逐条试拉到本地磁盘并 UPDATE file_url。
拉失败的（已过期 / 404）保留原 cdn url 不动，notes 追加错误。

用法：
    docker exec -it omni-knowledge-engine python /app/scripts/backfill_local_assets.py
    # dry-run（不真改库）
    docker exec -it omni-knowledge-engine python /app/scripts/backfill_local_assets.py --dry-run
    # 限定某个 sku
    docker exec -it omni-knowledge-engine python /app/scripts/backfill_local_assets.py --sku-id SKU-xxx
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.database import close_pool, get_pool, init_pool
from app.services.asset_storage import persist_asset_to_disk


async def _run(*, dry_run: bool, sku_id: str | None, asset_type: str | None) -> int:
    await init_pool()
    pool = get_pool()
    try:
        where = ["file_url LIKE 'http%'"]
        params: list = []
        if sku_id:
            params.append(sku_id)
            where.append(f"sku_id = ${len(params)}")
        if asset_type:
            params.append(asset_type)
            where.append(f"asset_type = ${len(params)}")
        sql = f"""
            SELECT id::text AS id, sku_id, asset_type, file_url, status, created_at
            FROM pipeline.assets
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
        """
        rows = await pool.fetch(sql, *params)
        if not rows:
            print("没有需要回填的 cdn url 资产。")
            return 0

        ok_count = 0
        err_count = 0
        for r in rows:
            asset_id = r["id"]
            url = r["file_url"]
            print(f"[{asset_id[:8]}] {r['asset_type']:8s} sku={r['sku_id']:24s} created={r['created_at']:%m-%d %H:%M} url_head={url[:60]}...")
            try:
                local_url = await persist_asset_to_disk(
                    url, sku_id=r["sku_id"], asset_type=r["asset_type"],
                )
            except Exception as exc:
                err_count += 1
                err_msg = f"{type(exc).__name__}: {exc}"
                print(f"    ✗ FAILED: {err_msg}")
                if not dry_run:
                    await pool.execute(
                        """UPDATE pipeline.assets
                           SET notes = COALESCE(notes || ' | ', '') || $1,
                               updated_at = NOW()
                           WHERE id = $2::uuid""",
                        f"backfill_err={err_msg}",
                        asset_id,
                    )
                continue

            print(f"    ✓ → {local_url}")
            ok_count += 1
            if not dry_run:
                await pool.execute(
                    "UPDATE pipeline.assets SET file_url = $1, updated_at = NOW() WHERE id = $2::uuid",
                    local_url,
                    asset_id,
                )

        suffix = " (DRY RUN — 库未改动)" if dry_run else ""
        print(f"\n=== 完成：成功 {ok_count} / 失败 {err_count} / 总 {len(rows)}{suffix} ===")
        return 0 if err_count == 0 else 1
    finally:
        await close_pool()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只 print 不真改库")
    ap.add_argument("--sku-id", default=None, help="限定某 SKU")
    ap.add_argument(
        "--asset-type", default=None,
        choices=("image", "video", "character_sheet"),
        help="限定资产类型",
    )
    args = ap.parse_args()
    return asyncio.run(_run(
        dry_run=args.dry_run,
        sku_id=args.sku_id,
        asset_type=args.asset_type,
    ))


if __name__ == "__main__":
    sys.exit(main())
