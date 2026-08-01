"""
Parses downloaded CSVs from Compass/shop-admin and writes rows to mvp_daily_metric.

Schema mapping: each 'schema_name' maps to a list of (csv_column, metric_name) pairs.
Rows are inserted with ON CONFLICT DO UPDATE so re-runs are idempotent.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from app.database import get_pool
from app.services.metric_ownership import submit_metric

log = logging.getLogger(__name__)

# Column mappings per schema.
# Key = schema_name used in YAML runbook; value = list of (csv_col, metric_name).
# csv_col supports '*' wildcard prefix matching for multi-column tables.
SCHEMA_MAPS: dict[str, list[tuple[str, str]]] = {
    # ── Compass ──────────────────────────────────────────────────────────────
    "compass_single_product": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("用户支付金额", "gmv_paid"),
        ("支付订单数", "order_count"),
        ("成交人数", "buyer_count"),
        ("用户访问数", "uv"),
        ("点击数", "click_count"),
        ("UV价值", "uv_value"),
        ("客单价", "aov"),
        ("件单价", "unit_price"),
        ("点击率", "ctr"),
        ("转化率", "cvr"),
        ("跳失率", "bounce_rate"),
        ("加购率", "add_to_cart_rate"),
    ],
    # business-part 经营分时：按小时，选前24h的最大值归今天
    "compass_business_part": [
        ("日期", "_date"),
        ("用户支付金额", "gmv_paid"),
        ("用户访问数", "uv"),
        ("点击数", "click_count"),
        ("UV价值", "uv_value"),
    ],
    # sell-analysis 全店成交分析（按渠道汇总行）
    "compass_sell_analysis": [
        ("日期", "_date"),
        ("用户支付金额", "gmv_paid"),
        ("支付订单数", "order_count"),
        ("成交人数", "buyer_count"),
        ("件单价", "unit_price"),
        ("客单价", "aov"),
    ],
    # refund-analysis 退款分析
    "compass_refund": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("退款金额", "refund_amount"),
        ("退款率", "refund_rate"),
        ("实收金额", "net_revenue"),
        ("品质退款率", "quality_refund_rate"),
    ],
    # commodity-product-list 商品列表
    "compass_product_list": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("用户支付金额", "gmv_paid"),
        ("支付订单数", "order_count"),
        ("用户访问数", "uv"),
        ("UV价值", "uv_value"),
        ("转化率", "cvr"),
        ("商品权重分", "weight_score"),
        ("类目排名", "rank"),
    ],
    # product-detail 单品详情（运行时按focus SKU，商品ID从env注入）
    "compass_product_detail": [
        ("日期", "_date"),
        ("用户支付金额", "gmv_paid"),
        ("用户访问数", "uv"),
        ("点击率", "ctr"),
        ("转化率", "cvr"),
        ("跳失率", "bounce_rate"),
        ("加购率", "add_to_cart_rate"),
        ("退款率", "refund_rate"),
    ],
    # service-customer-analysis 客服分析
    "compass_service_customer": [
        ("日期", "_date"),
        ("人工会话量", "service_session_count"),
        ("平均响应时长", "service_response_time"),
        ("不满意率", "service_dissatisfaction_rate"),
    ],
    # service-user-sound 用户原声（差评）
    "compass_user_sound": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("商品差评率", "review_bad_rate"),
        ("评价数", "review_count"),
        ("品质退货率", "quality_refund_rate"),
        ("投诉率", "complaint_rate"),
    ],
    # search-drainage-terms 搜索引流词（按词级别，写到shop-level sku '_SHOP')
    "compass_search_terms": [
        ("日期", "_date"),
        ("搜索词", "_keyword"),
        ("搜索UV", "search_uv"),
        ("搜索引流UV", "search_referral_uv"),
    ],
    # logistics-diagnosis-index 物流时效（抖店后台和罗盘共用）
    "compass_logistics": [
        ("日期", "_date"),
        ("揽收时效达成率", "logistics_pickup_rate"),
        ("干线时效达成率", "logistics_trunk_rate"),
        ("末端时效达成率", "logistics_lastmile_rate"),
    ],
    # ── Shop Admin ────────────────────────────────────────────────────────────
    "shop_admin_stock": [
        ("商品ID", "_product_id"),
        ("变更时间", "_date"),
        ("变更类型", "_change_type"),
        ("变更量", "_delta"),
        ("变更前库存", "_before"),
        ("变更后库存", "_after"),
        ("操作人", "_operator"),
    ],
    # Deprecated aliases kept for backwards compat
    "douyin_single_product_metrics": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("用户支付金额", "gmv_paid"),
        ("支付订单数", "order_count"),
        ("成交人数", "buyer_count"),
        ("用户访问数", "uv"),
        ("点击数", "click_count"),
        ("UV价值", "uv_value"),
        ("客单价", "aov"),
        ("件单价", "unit_price"),
        ("点击率", "ctr"),
        ("转化率", "cvr"),
        ("跳失率", "bounce_rate"),
        ("加购率", "add_to_cart_rate"),
    ],
    "douyin_traffic_source": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("搜索UV", "search_uv"),
        ("搜索引流UV", "search_referral_uv"),
        ("商品权重分", "weight_score"),
        ("类目排名", "rank"),
    ],
    "douyin_refund_metrics": [
        ("商品ID", "_product_id"),
        ("日期", "_date"),
        ("退款金额", "refund_amount"),
        ("退款率", "refund_rate"),
        ("实收金额", "net_revenue"),
    ],
}


async def parse_and_write(
    csv_path: str,
    schema_name: str,
    write_to: str,
    run_id: str,
) -> int:
    """Parse csv_path according to schema_name and write rows. Returns row count."""
    # Special-case schemas that write to non-metric tables
    if schema_name == "shop_admin_stock":
        return await _parse_stock_change_log(csv_path, run_id)

    mapping = SCHEMA_MAPS.get(schema_name)
    if not mapping:
        log.warning("no mapping for schema '%s', skipping", schema_name)
        return 0

    path = Path(csv_path)
    if not path.exists():
        log.warning("csv not found: %s", csv_path)
        return 0

    # Try multiple encodings common on Douyin exports
    content = None
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            content = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        log.error("cannot decode %s", csv_path)
        return 0

    reader = csv.DictReader(content.splitlines())
    col_to_metric = {col: metric for col, metric in mapping}

    pool = await get_pool()
    written = 0
    async with pool.acquire() as conn:
        for row in reader:
            product_id = row.get("商品ID", "").strip()
            date_str = row.get("日期", "").strip()
            if not product_id or not date_str:
                continue

            # Look up sku_id by douyin_product_id
            sku_id = await conn.fetchval(
                "SELECT id FROM mvp_sku WHERE douyin_product_id=$1", product_id
            )
            if not sku_id:
                log.debug("unknown product_id %s, skipping", product_id)
                continue

            for csv_col, metric_name in col_to_metric.items():
                if metric_name.startswith("_"):
                    continue  # internal columns
                raw_val = row.get(csv_col, "").strip()
                if not raw_val or raw_val == "-":
                    continue
                try:
                    value = float(raw_val.replace(",", "").replace("%", ""))
                    if "%" in raw_val:
                        value = value / 100.0
                except ValueError:
                    continue

                result = await submit_metric(
                    conn, sku_id=sku_id, metric_date=date_str, metric_name=metric_name,
                    value=value, platform="douyin", source=f"csv:{schema_name}",
                    source_run_id=run_id,
                )
                written += int(result["canonical_updated"])

    log.info("csv_parser: wrote %d metric rows from %s", written, csv_path)
    return written


async def _parse_stock_change_log(csv_path: str, run_id: str) -> int:
    """Write 库存变更记录 rows to mvp_stock_change_log (双轨轨B)."""
    import os
    path = Path(csv_path)
    if not path.exists():
        return 0
    content = None
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            content = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        return 0

    reader = csv.DictReader(content.splitlines())
    pool = await get_pool()
    written = 0
    async with pool.acquire() as conn:
        for row in reader:
            product_id = row.get("商品ID", "").strip()
            date_str = row.get("变更时间", "").strip()
            if not product_id:
                continue
            sku_id = await conn.fetchval(
                "SELECT id FROM mvp_sku WHERE douyin_product_id=$1", product_id
            )
            if not sku_id:
                continue
            try:
                delta = int(row.get("变更量", "0").replace(",", "") or "0")
                before = int(row.get("变更前库存", "0").replace(",", "") or "0")
                after = int(row.get("变更后库存", "0").replace(",", "") or "0")
            except ValueError:
                delta = before = after = 0

            await conn.execute(
                """
                INSERT INTO mvp_stock_change_log
                    (sku_id, change_at, change_type, delta, before_stock, after_stock,
                     operator, source, source_run_id)
                VALUES ($1, $2::timestamptz, $3, $4, $5, $6, $7, 'shop_admin_log', $8)
                ON CONFLICT DO NOTHING
                """,
                sku_id, date_str or "now",
                row.get("变更类型", "").strip(),
                delta, before, after,
                row.get("操作人", "").strip(),
                run_id,
            )
            written += 1
    log.info("csv_parser: wrote %d stock_change_log rows from %s", written, csv_path)
    return written
