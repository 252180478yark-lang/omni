"""P0 planting-video production-order tools.

This is the intentionally narrow production atom for one 12–15 second
Seedance planting video.  It shares platform lineage primitives but does not
activate the P1 ecommerce-visual or deferred AI-insert branches.
"""

from __future__ import annotations

from typing import Any

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services.video_production_baseline import run_video_production_preflight
from app.services.video_production_orders import (
    build_and_save_content_spec,
    create_or_reuse_production_order,
    get_production_order,
    list_production_inputs,
    list_production_orders,
    save_content_spec,
)
from app.services.video_production_workflow import (
    assess_candidate_execution_vector_match,
    assess_execution_content_match,
    assess_frozen_execution_vector_match,
    cancel_production_order,
    compose_final_video,
    generate_planting_bridge_candidates,
    generate_script_candidates,
    prepare_prompt_source,
    recover_generation_attempt,
    release_package,
    request_generation_approval,
    review_script_candidates,
    run_final_qa,
    run_raw_qa,
    save_script_candidates,
    select_script,
    start_generation_attempt,
)


@tool_with_audit(mcp, require_approval=False)
async def p0_preflight_video_production() -> dict[str, Any]:
    """Read the reproducible migration/config baseline required before P0 order creation."""

    return await run_video_production_preflight()


@tool_with_audit(mcp, require_approval=False)
async def p0_list_video_production_inputs(sku_id: str) -> dict[str, Any]:
    """List adopted audience, portrait, pack and product-reference inputs for one P0 SKU."""

    return await list_production_inputs(sku_id=sku_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_list_video_production_orders(sku_id: str, limit: int = 20) -> dict[str, Any]:
    """Restore existing P0 orders for this SKU without fabricating their state."""

    return await list_production_orders(sku_id=sku_id, limit=limit)


@tool_with_audit(mcp, require_approval=False)
async def p0_create_video_production_order(
    sku_id: str,
    audience_record_id: str,
    product_reference_asset_ids: list[str],
    baseline_manifest: dict[str, Any],
    audience_pack_id: str,
    audience_portrait_id: str | None = None,
) -> dict[str, Any]:
    """Create/reuse one P0 order from adopted audience, portrait, pack and product facts."""

    return await create_or_reuse_production_order(
        sku_id=sku_id,
        audience_record_id=audience_record_id,
        audience_portrait_id=audience_portrait_id,
        audience_pack_id=audience_pack_id,
        product_reference_asset_ids=product_reference_asset_ids,
        baseline_manifest=baseline_manifest,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_build_video_content_spec(
    production_order_id: str,
    product_action: str,
    pain_solution_bridge: dict[str, Any],
    upstream_fact_hash: str,
    spoken_copy_goal: str,
    target_audience_signal: str | None = None,
    duration_seconds: float = 12,
    visual_constraints: list[str] | None = None,
    audio_constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Build and freeze the P0 ContentSpec from owner choices plus frozen truth."""

    return await build_and_save_content_spec(
        production_order_id=production_order_id,
        product_action=product_action,
        pain_solution_bridge=pain_solution_bridge,
        upstream_fact_hash=upstream_fact_hash,
        spoken_copy_goal=spoken_copy_goal,
        target_audience_signal=target_audience_signal,
        duration_seconds=duration_seconds,
        visual_constraints=visual_constraints,
        audio_constraints=audio_constraints,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_save_video_content_spec(
    production_order_id: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist the one immutable P0 ContentSpec."""

    return await save_content_spec(production_order_id=production_order_id, spec=spec)


@tool_with_audit(mcp, require_approval=False)
async def p0_get_video_production_order(production_order_id: str) -> dict[str, Any]:
    """Read the full P0 lineage, gates, QA reports and the next safe action."""

    return await get_production_order(production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_generate_planting_bridge_candidates(
    production_order_id: str,
) -> dict[str, Any]:
    """Generate two canonical, frozen-context bridge candidates for P0 v4 review."""

    return await generate_planting_bridge_candidates(
        production_order_id=production_order_id,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_generate_video_script_candidates(
    production_order_id: str,
    extra_context: str | None = None,
) -> dict[str, Any]:
    """Generate and freeze the two P0 script candidates before independent review."""

    return await generate_script_candidates(
        production_order_id=production_order_id,
        extra_context=extra_context,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_save_video_script_candidates(
    production_order_id: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Freeze two externally edited P0 candidates through the same truth gate."""

    return await save_script_candidates(
        production_order_id=production_order_id,
        candidates=candidates,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_review_video_script_candidates(production_order_id: str) -> dict[str, Any]:
    """Run deterministic fact checks and an independent critic on both candidates."""

    return await review_script_candidates(production_order_id=production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_select_video_script(
    production_order_id: str,
    script_id: str,
) -> dict[str, Any]:
    """Record the owner's selected, independently passed candidate script."""

    return await select_script(production_order_id=production_order_id, script_id=script_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_prepare_video_prompt(production_order_id: str) -> dict[str, Any]:
    """Compile and freeze the executable P0 Seedance prompt and ref manifest."""

    return await prepare_prompt_source(production_order_id=production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_assess_video_content_match(production_order_id: str) -> dict[str, Any]:
    """Show optional transparent lexical execution evidence for owner review."""

    return await assess_execution_content_match(production_order_id=production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_assess_video_candidate_vector_match(production_order_id: str) -> dict[str, Any]:
    """Run real three-track vector pre-match for review-passed P0 candidates."""

    return await assess_candidate_execution_vector_match(production_order_id=production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_assess_video_execution_vector_match(production_order_id: str) -> dict[str, Any]:
    """Run real vector pre-match on the selected immutable PromptSource."""

    return await assess_frozen_execution_vector_match(production_order_id=production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_request_video_generation_approval(production_order_id: str) -> dict[str, Any]:
    """Show the exact immutable paid payload and advance to the approval gate."""

    return await request_generation_approval(production_order_id=production_order_id)


def _generation_summary(args: dict[str, Any]) -> str:
    return (
        "P0 Seedance paid generation: "
        f"order={args.get('production_order_id')}, approval={str(args.get('approval_hash') or '')[:12]}…"
    )


@tool_with_audit(mcp, require_approval=True, summary_fn=_generation_summary)
async def p0_start_video_generation(
    production_order_id: str,
    approval_hash: str,
) -> dict[str, Any]:
    """Create exactly one human-approved, pinned Seedance generation attempt."""

    return await start_generation_attempt(
        production_order_id=production_order_id,
        approval_hash=approval_hash,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_recover_video_generation(
    production_order_id: str,
    attempt_id: str,
    max_wait_seconds: int = 0,
) -> dict[str, Any]:
    """Poll/recover one existing remote render without creating another paid attempt."""

    return await recover_generation_attempt(
        production_order_id=production_order_id,
        attempt_id=attempt_id,
        max_wait_seconds=max_wait_seconds,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_run_raw_video_qa(
    production_order_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Run technical plus independent semantic QA on the persisted raw video."""

    return await run_raw_qa(production_order_id=production_order_id, attempt_id=attempt_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_compose_video_final(
    production_order_id: str,
    attempt_id: str,
    voiceover_audio_ref: str | None = None,
    bgm_audio_ref: str | None = None,
    bgm_authorization_note: str | None = None,
    allow_no_bgm: bool = False,
    no_bgm_scope_note: str | None = None,
) -> dict[str, Any]:
    """Compose native/owner audio, authorized BGM (or explicit no-BGM scope), and subtitles."""

    return await compose_final_video(
        production_order_id=production_order_id,
        attempt_id=attempt_id,
        voiceover_audio_ref=voiceover_audio_ref,
        bgm_audio_ref=bgm_audio_ref,
        bgm_authorization_note=bgm_authorization_note,
        allow_no_bgm=allow_no_bgm,
        no_bgm_scope_note=no_bgm_scope_note,
    )


@tool_with_audit(mcp, require_approval=False)
async def p0_run_final_video_qa(production_order_id: str) -> dict[str, Any]:
    """Verify final video/audio streams, subtitles and immutable manifest links."""

    return await run_final_qa(production_order_id=production_order_id)


def _release_summary(args: dict[str, Any]) -> str:
    return f"P0 release package: order={args.get('production_order_id')}"


@tool_with_audit(mcp, require_approval=True, summary_fn=_release_summary)
async def p0_release_video_package(production_order_id: str) -> dict[str, Any]:
    """Create the immutable release package after final QA and owner approval."""

    return await release_package(production_order_id=production_order_id)


@tool_with_audit(mcp, require_approval=False)
async def p0_cancel_video_production(production_order_id: str) -> dict[str, Any]:
    """Cancel a non-released P0 order without deleting its audit history."""

    return await cancel_production_order(production_order_id=production_order_id)


__all__ = [
    "p0_assess_video_candidate_vector_match",
    "p0_assess_video_content_match",
    "p0_assess_video_execution_vector_match",
    "p0_build_video_content_spec",
    "p0_create_video_production_order",
    "p0_cancel_video_production",
    "p0_compose_video_final",
    "p0_generate_planting_bridge_candidates",
    "p0_generate_video_script_candidates",
    "p0_get_video_production_order",
    "p0_list_video_production_inputs",
    "p0_list_video_production_orders",
    "p0_preflight_video_production",
    "p0_prepare_video_prompt",
    "p0_recover_video_generation",
    "p0_release_video_package",
    "p0_request_video_generation_approval",
    "p0_review_video_script_candidates",
    "p0_run_final_video_qa",
    "p0_run_raw_video_qa",
    "p0_save_video_content_spec",
    "p0_save_video_script_candidates",
    "p0_select_video_script",
    "p0_start_video_generation",
]
