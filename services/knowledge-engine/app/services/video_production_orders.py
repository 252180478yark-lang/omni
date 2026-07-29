"""Persistence service for the P0 planting-video production atom.

The service writes only to the existing ``pipeline`` domain.  It deliberately
does not read or mutate ecommerce-visual or AI-insert tables: those are future
adapters, not alternate sources of truth for P0.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.database import get_pool
from app.services.pain_solution_bridge import load_planting_bridge_context
from app.services.video_production_contract import (
    P0_CONTRACT_VERSION,
    content_hash,
    p0_idempotency_key,
    validate_candidate_pair,
    validate_content_spec,
    validate_prompt_preview,
    validate_transition,
    validate_truth_snapshot,
)
from app.services.video_production_workflow import get_full_production_order


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _selling_point_texts(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, Mapping) and str(item.get("text") or "").strip():
            result.append(str(item["text"]).strip())
    return result


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _require_ready_baseline(manifest: object) -> dict[str, Any] | None:
    if not isinstance(manifest, Mapping):
        return {"ok": False, "error": "baseline_not_reproducible", "missing": ["baseline_manifest"]}
    if manifest.get("status") != "ready":
        return {
            "ok": False,
            "error": "baseline_not_reproducible",
            "blockers": manifest.get("blockers") or ["baseline_status_not_ready"],
        }
    return None


def _freeze_bridge_context(upstream: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project the canonical bridge-loader result into immutable P0 truth."""

    facts = upstream.get("facts")
    upstream_fact_hash = str(upstream.get("upstream_fact_hash") or "").strip()
    if not isinstance(facts, Mapping) or not upstream_fact_hash:
        return None
    raw_evidence_catalog = facts.get("eligible_evidence_catalog")
    if not isinstance(raw_evidence_catalog, Mapping):
        return None
    # Mirror the canonical bridge generator exactly: pack evidence lives in a
    # sibling catalog in the loader result, but the validator expects it under
    # the ``pack`` source when a pack is part of the frozen lineage.
    evidence_catalog = dict(raw_evidence_catalog)
    pack_catalog = facts.get("pack_calibration_catalog")
    if isinstance(pack_catalog, Mapping) and pack_catalog:
        evidence_catalog["pack"] = dict(pack_catalog)
    return {
        # Retain the source result verbatim enough for a future audit to prove
        # which record/portrait/product evidence the bridge was grounded in.
        "facts": dict(facts),
        "eligible_evidence_catalog": evidence_catalog,
        "require_pack_evidence": bool(facts.get("pack_calibration")),
        "upstream_fact_hash": upstream_fact_hash,
    }


async def create_or_reuse_production_order(
    *,
    sku_id: str,
    audience_record_id: str,
    product_reference_asset_ids: Sequence[str],
    baseline_manifest: Mapping[str, Any],
    audience_portrait_id: str | None = None,
    audience_pack_id: str | None = None,
) -> dict[str, Any]:
    """Freeze P0 truth once, or return the exact prior order idempotently."""

    baseline_error = _require_ready_baseline(baseline_manifest)
    if baseline_error:
        return baseline_error
    portrait_id = str(audience_portrait_id or "").strip()
    if not portrait_id:
        return {
            "ok": False,
            "error": "audience_portrait_required",
            "missing": ["audience_portrait_id"],
        }
    pack_id = str(audience_pack_id or "").strip()
    if not pack_id:
        return {
            "ok": False,
            "error": "audience_pack_required",
            "missing": ["audience_pack_id"],
        }
    refs = [str(item).strip() for item in product_reference_asset_ids]
    if not refs or not all(refs) or len(refs) != len(set(refs)):
        return {"ok": False, "error": "product_ref_invalid_or_mismatch"}

    # This is the canonical source shape already used by the bridge generator.
    # Freeze it before any script exists so later content validation never has
    # to re-read mutable upstream tables or reconstruct an approximate catalog.
    upstream = await load_planting_bridge_context(
        sku_id,
        audience_record_id,
        portrait_id,
        pack_id,
    )
    if not upstream.get("ok"):
        return upstream
    bridge_context = _freeze_bridge_context(upstream)
    if bridge_context is None:
        return {
            "ok": False,
            "error": "upstream_lineage_incomplete",
            "reason": "canonical_bridge_context_invalid",
        }
    frozen_lineage = bridge_context["facts"].get("lineage")
    if not isinstance(frozen_lineage, Mapping):
        return {
            "ok": False,
            "error": "upstream_lineage_incomplete",
            "reason": "canonical_bridge_lineage_missing",
        }
    frozen_audience_record_id = str(frozen_lineage.get("audience_record_id") or "").strip()
    frozen_portrait_id = str(frozen_lineage.get("portrait_id") or "").strip()
    frozen_pack_id = str(frozen_lineage.get("audience_pack_id") or "").strip()
    if not frozen_audience_record_id or not frozen_portrait_id or not frozen_pack_id:
        return {
            "ok": False,
            "error": "upstream_lineage_incomplete",
            "reason": "canonical_bridge_lineage_missing",
        }
    if frozen_pack_id != pack_id:
        return {
            "ok": False,
            "error": "audience_pack_lineage_mismatch",
            "expected_audience_pack_id": pack_id,
            "frozen_audience_pack_id": frozen_pack_id,
        }

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            sku = await conn.fetchrow(
                """
                SELECT id, name, category, specifications, owner_selling_points,
                       owner_notes, status
                FROM mvp_sku WHERE id=$1 FOR SHARE
                """,
                sku_id,
            )
            if not sku:
                return {"ok": False, "error": "sku_not_found", "field": "sku_id"}
            audience = await conn.fetchrow(
                """
                SELECT id::text AS id, sku_id, name, raw_md_segment, layer_tags,
                       match_reasons, status
                FROM pipeline.audience_records WHERE id=$1::uuid FOR SHARE
                """,
                audience_record_id,
            )
            if not audience:
                return {"ok": False, "error": "audience_record_not_found"}
            if audience["sku_id"] != sku_id or audience["status"] != "adopted":
                return {"ok": False, "error": "audience_record_not_adopted_or_mismatch"}
            portrait_row = await conn.fetchrow(
                """
                SELECT id::text AS id, sku_id, audience_record_id::text,
                       portrait_md, status
                FROM pipeline.audience_portraits WHERE id=$1::uuid FOR SHARE
                """,
                portrait_id,
            )
            if not portrait_row:
                return {"ok": False, "error": "audience_portrait_not_found"}
            if (
                portrait_row["sku_id"] != sku_id
                or portrait_row["audience_record_id"] != audience["id"]
                or portrait_row["status"] != "adopted"
            ):
                return {"ok": False, "error": "audience_portrait_not_adopted_or_mismatch"}
            portrait = dict(portrait_row)

            pack_row = await conn.fetchrow(
                """
                SELECT id::text AS id, sku_id, audience_record_id::text, status
                FROM pipeline.audience_packs WHERE id=$1::uuid FOR SHARE
                """,
                frozen_pack_id,
            )
            if not pack_row:
                return {"ok": False, "error": "audience_pack_not_found"}
            if (
                pack_row["sku_id"] != sku_id
                or pack_row["audience_record_id"] != audience["id"]
                or pack_row["status"] != "adopted"
            ):
                return {"ok": False, "error": "audience_pack_not_adopted_or_mismatch"}

            rows = await conn.fetch(
                """
                SELECT id::text AS id, sku_id, file_url, status
                FROM pipeline.assets
                WHERE id=ANY($1::uuid[])
                  AND asset_type='product_reference'
                  AND status='adopted'
                FOR SHARE
                """,
                refs,
            )
            references_by_id = {row["id"]: dict(row) for row in rows}
            references = [references_by_id.get(asset_id) for asset_id in refs]
            if any(item is None or item["sku_id"] != sku_id for item in references):
                return {"ok": False, "error": "product_ref_invalid_or_mismatch"}

            sku_data = dict(sku)
            whitelist = _selling_point_texts(sku_data.get("owner_selling_points"))
            if not whitelist:
                whitelist = [
                    str(sku_data.get("name") or "").strip(),
                    str(sku_data.get("specifications") or "").strip(),
                ]
            whitelist = [item for item in whitelist if item]
            snapshot = {
                "contract_version": P0_CONTRACT_VERSION,
                "sku": {
                    "id": sku_data["id"],
                    "name": sku_data.get("name"),
                    "category": sku_data.get("category"),
                    "specifications": sku_data.get("specifications"),
                    "owner_notes": sku_data.get("owner_notes"),
                },
                "audience_record": dict(audience),
                "audience_portrait": portrait,
                "product_reference_manifest": {"assets": references},
                "facts": {"whitelist": whitelist},
                "planting_bridge_context": bridge_context,
            }
            truth = validate_truth_snapshot(
                snapshot,
                contract_version=P0_CONTRACT_VERSION,
            )
            if not truth["ok"]:
                return truth

            baseline_hash = content_hash(baseline_manifest)
            key = p0_idempotency_key(
                sku_id=sku_id,
                audience_record_id=frozen_audience_record_id,
                audience_portrait_id=frozen_portrait_id,
                audience_pack_id=frozen_pack_id,
                product_reference_asset_ids=refs,
            )
            key = content_hash({"input_key": key, "baseline_hash": baseline_hash})
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", key
            )
            existing = await conn.fetchrow(
                """
                SELECT id::text AS id, status, contract_version, created_at
                FROM pipeline.production_orders WHERE idempotency_key=$1 FOR UPDATE
                """,
                key,
            )
            if existing:
                return {"ok": True, "reused": True, "order": dict(existing)}

            order = await conn.fetchrow(
                """
                INSERT INTO pipeline.production_orders(
                    sku_id,audience_record_id,audience_portrait_id,audience_pack_id,intent,
                    contract_version,idempotency_key,baseline_manifest,status
                ) VALUES($1,$2::uuid,$3::uuid,$4::uuid,'planting',$5,$6,$7::jsonb,'baseline_ready')
                RETURNING id::text AS id, status, created_at
                """,
                sku_id,
                frozen_audience_record_id,
                frozen_portrait_id,
                frozen_pack_id,
                P0_CONTRACT_VERSION,
                key,
                _json(dict(baseline_manifest)),
            )
            await conn.execute(
                """
                INSERT INTO pipeline.order_truth_snapshots(
                    production_order_id,snapshot,snapshot_hash
                ) VALUES($1::uuid,$2::jsonb,$3)
                """,
                order["id"],
                _json(truth["snapshot"]),
                truth["snapshot_hash"],
            )
            await conn.execute(
                "UPDATE pipeline.production_orders SET status='truth_ready' WHERE id=$1::uuid",
                order["id"],
            )
            return {
                "ok": True,
                "reused": False,
                "order": {**dict(order), "status": "truth_ready"},
                "truth_snapshot_hash": truth["snapshot_hash"],
            }


async def save_content_spec(*, production_order_id: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Persist the sole P0 ContentSpec for a frozen truth snapshot."""

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                """
                SELECT id::text AS id,status,contract_version
                FROM pipeline.production_orders
                WHERE id=$1::uuid FOR UPDATE
                """,
                production_order_id,
            )
            if not order:
                return {"ok": False, "error": "production_order_not_found"}
            if order["contract_version"] != P0_CONTRACT_VERSION:
                return {
                    "ok": False,
                    "error": "production_order_contract_read_only",
                    "contract_version": order["contract_version"],
                }
            if order["status"] not in {"truth_ready", "spec_ready"}:
                return {"ok": False, "error": "production_order_wrong_state", "status": order["status"]}
            truth = await conn.fetchrow(
                """
                SELECT id::text AS id,snapshot,snapshot_hash FROM pipeline.order_truth_snapshots
                WHERE production_order_id=$1::uuid FOR SHARE
                """,
                production_order_id,
            )
            if not truth:
                return {"ok": False, "error": "truth_snapshot_not_found"}
            validated = validate_content_spec(
                spec,
                truth_snapshot_hash=truth["snapshot_hash"],
                truth_snapshot=_mapping(truth["snapshot"]),
                contract_version=order["contract_version"],
            )
            if not validated["ok"]:
                return validated
            existing = await conn.fetchrow(
                """
                SELECT id::text AS id,spec_hash FROM pipeline.production_content_specs
                WHERE production_order_id=$1::uuid AND version=1 FOR UPDATE
                """,
                production_order_id,
            )
            if existing:
                if existing["spec_hash"] == validated["spec_hash"]:
                    return {"ok": True, "reused": True, "content_spec_id": existing["id"]}
                return {"ok": False, "error": "content_spec_immutable"}
            row = await conn.fetchrow(
                """
                INSERT INTO pipeline.production_content_specs(
                    production_order_id,truth_snapshot_id,spec,spec_hash
                ) VALUES($1::uuid,$2::uuid,$3::jsonb,$4)
                RETURNING id::text AS id
                """,
                production_order_id,
                truth["id"],
                _json(validated["spec"]),
                validated["spec_hash"],
            )
            await conn.execute(
                "UPDATE pipeline.production_orders SET status='spec_ready' WHERE id=$1::uuid",
                production_order_id,
            )
            return {
                "ok": True,
                "reused": False,
                "content_spec_id": row["id"],
                "spec_hash": validated["spec_hash"],
            }


async def get_production_order(production_order_id: str) -> dict[str, Any]:
    """Return the complete P0 order lineage, including gates and release state."""

    return await get_full_production_order(production_order_id)


async def build_and_save_content_spec(
    *,
    production_order_id: str,
    product_action: str,
    pain_solution_bridge: Mapping[str, Any],
    upstream_fact_hash: str,
    spoken_copy_goal: str,
    target_audience_signal: str | None = None,
    duration_seconds: float = 12,
    visual_constraints: Sequence[str] | None = None,
    audio_constraints: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the narrow P0 ContentSpec from frozen truth plus owner intent.

    The owner selects one evidence-grounded pain-to-solution bridge and may
    set the script's product action/copy goal.  The rest is derived from the
    immutable truth snapshot so a UI cannot accidentally invent a second
    source of facts.
    """

    action = str(product_action or "").strip()
    bridge = dict(pain_solution_bridge) if isinstance(pain_solution_bridge, Mapping) else None
    upstream_hash = str(upstream_fact_hash or "").strip()
    spoken_goal = str(spoken_copy_goal or "").strip()
    if not action or bridge is None or not upstream_hash or not spoken_goal:
        return {
            "ok": False,
            "error": "content_spec_owner_inputs_missing",
            "missing": [
                name
                for name, value in (
                    ("product_action", action),
                    ("pain_solution_bridge", bridge),
                    ("upstream_fact_hash", upstream_hash),
                    ("spoken_copy_goal", spoken_goal),
                )
                if not value
            ],
        }
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT order_row.status,order_row.contract_version,truth.snapshot
            FROM pipeline.production_orders order_row
            JOIN pipeline.order_truth_snapshots truth
              ON truth.production_order_id=order_row.id
            WHERE order_row.id=$1::uuid
            """,
            production_order_id,
        )
    if not row:
        return {"ok": False, "error": "production_order_not_found"}
    if row["contract_version"] != P0_CONTRACT_VERSION:
        return {
            "ok": False,
            "error": "production_order_contract_read_only",
            "contract_version": row["contract_version"],
        }
    if row["status"] not in {"truth_ready", "spec_ready"}:
        return {"ok": False, "error": "production_order_wrong_state", "status": row["status"]}
    truth = _mapping(row["snapshot"])
    audience = _mapping(truth.get("audience_record"))
    facts = _mapping(truth.get("facts"))
    whitelist = _string_list(facts.get("whitelist"))
    if not whitelist:
        return {"ok": False, "error": "truth_snapshot_incomplete", "missing": ["facts.whitelist"]}
    visual = _string_list(visual_constraints) or [
        "9:16 竖屏、单人、单场景",
        "真实家庭厨房，产品包装与冻结参考图一致",
        "产品、手部和菜肴的动作关系连续可理解",
    ]
    audio = _string_list(audio_constraints) or [
        "口播清晰且与画面同步",
        "保留自然厨房环境音",
        "BGM 仅可接入已授权素材；无授权素材时需显式确认无 BGM 范围",
    ]
    spec = {
        "intent": "planting",
        "target_audience_signal": str(
            target_audience_signal
            or bridge.get("audience_segment")
            or audience.get("name")
            or "目标人群"
        ).strip(),
        "planting_function": (
            f"{bridge.get('pain_point') or '当下困扰'} → {bridge.get('product_action') or action}"
            f" → {bridge.get('visible_result') or '可见结果'}"
        ),
        "duration_seconds": duration_seconds,
        "cast_count": 1,
        "scene_count": 1,
        "product_actions": [action],
        "spoken_copy_goal": spoken_goal,
        "pain_solution_bridge": bridge,
        "upstream_fact_hash": upstream_hash,
        "factual_whitelist": whitelist,
        "forbidden_claims": [
            "未在冻结事实中的配方、认证、价格、销量、赠品、促销和绝对化功效",
            "无法由产品参考图或事实白名单验证的包装文字",
        ],
        "visual_constraints": visual,
        "audio_constraints": audio,
        "experiment_variable": "opening_hook_3s",
    }
    saved = await save_content_spec(production_order_id=production_order_id, spec=spec)
    if saved.get("ok"):
        saved["spec"] = spec
    return saved


async def list_production_inputs(*, sku_id: str) -> dict[str, Any]:
    """List only adopted P0 inputs that can legally enter a new order."""

    pool = get_pool()
    async with pool.acquire() as conn:
        audience_rows = await conn.fetch(
            """
            SELECT id::text AS id,name,raw_md_segment,layer_tags,match_reasons,created_at
            FROM pipeline.audience_records
            WHERE sku_id=$1 AND status='adopted'
            ORDER BY created_at DESC
            """,
            sku_id,
        )
        reference_rows = await conn.fetch(
            """
            SELECT id::text AS id,file_url,notes,created_at
            FROM pipeline.assets
            WHERE sku_id=$1 AND asset_type='product_reference' AND status='adopted'
            ORDER BY created_at DESC
            """,
            sku_id,
        )
        portrait_rows = await conn.fetch(
            """
            SELECT portrait.id::text AS id,portrait.audience_record_id::text,
                   record.name AS audience_name,portrait.status,portrait.created_at
            FROM pipeline.audience_portraits portrait
            JOIN pipeline.audience_records record ON record.id=portrait.audience_record_id
            WHERE portrait.sku_id=$1 AND portrait.status='adopted'
            ORDER BY portrait.created_at DESC
            """,
            sku_id,
        )
        pack_rows = await conn.fetch(
            """
            SELECT pack.id::text AS id,pack.audience_record_id::text,
                   record.name AS audience_name,pack.pack_md,pack.dmp_tags,
                   pack.version,pack.created_at
            FROM pipeline.audience_packs pack
            JOIN pipeline.audience_records record ON record.id=pack.audience_record_id
            WHERE pack.sku_id=$1
              AND pack.status='adopted'
              AND record.status='adopted'
            ORDER BY pack.created_at DESC
            """,
            sku_id,
        )
    return {
        "ok": True,
        "sku_id": sku_id,
        "audience_records": [dict(row) for row in audience_rows],
        "product_references": [dict(row) for row in reference_rows],
        "audience_portraits": [dict(row) for row in portrait_rows],
        "audience_packs": [dict(row) for row in pack_rows],
        "admission": {
            "requires_adopted_audience": True,
            "requires_adopted_audience_portrait": True,
            "requires_adopted_audience_pack": True,
            "requires_adopted_product_reference": True,
        },
    }


async def list_production_orders(*, sku_id: str, limit: int = 20) -> dict[str, Any]:
    """Restore the owner's P0 production orders for one SKU without guessing."""

    safe_limit = max(1, min(int(limit), 100))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_row.id::text AS id,order_row.audience_record_id::text,
                   order_row.audience_portrait_id::text,
                   to_jsonb(order_row)->>'audience_pack_id' AS audience_pack_id,
                   order_row.status,order_row.contract_version,order_row.created_at,order_row.updated_at
            FROM pipeline.production_orders AS order_row
            WHERE order_row.sku_id=$1
            ORDER BY order_row.updated_at DESC
            LIMIT $2
            """,
            sku_id,
            safe_limit,
        )
    return {"ok": True, "sku_id": sku_id, "orders": [dict(row) for row in rows]}


__all__ = [
    "build_and_save_content_spec",
    "create_or_reuse_production_order",
    "get_production_order",
    "list_production_inputs",
    "list_production_orders",
    "save_content_spec",
]
