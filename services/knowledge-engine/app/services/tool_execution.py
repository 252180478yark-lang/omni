"""One registered-tool executor for canonical and compatibility HTTP routes."""

from __future__ import annotations

import asyncio
import inspect
import sys
from dataclasses import dataclass
from typing import Any, Mapping, get_type_hints

from pydantic import ValidationError, create_model


OPERATION_REGISTRY: dict[str, str] = {
    "sku.selling-points.generate": "generate_selling_points_matrix",
    "sku.audience-match.generate": "generate_audience_match",
    "sku.keyword-pack.generate": "generate_keyword_pack",
    "sku.audience-pack.generate": "generate_audience_pack",
    "sku.creative-pack.generate": "generate_creative_pack",
    "sku.character-sheets.generate": "generate_character_sheets",
    "sku.storyboard.generate": "generate_storyboard_images",
    "sku.video.generate": "generate_video_segments",
    "sku.video-anchor.generate": "generate_video_anchor",
    "sku.audience-portrait.generate": "generate_audience_portrait",
    "sku.director-brief.generate": "generate_director_brief",
    "sku.matrix-runs.list": "pipeline_list_matrix_runs",
    "sku.matrix-run.get": "pipeline_get_matrix_run",
    "sku.audience-runs.list": "pipeline_list_audience_runs",
    "sku.audience-run.get": "pipeline_get_audience_run",
    "sku.audience-records.list": "pipeline_list_audience_records",
    "sku.audience-record.get": "pipeline_get_audience_record",
    "sku.pipeline.adopt": "pipeline_adopt",
    "sku.lineage.get": "pipeline_get_sku_lineage",
    "sku.node.archive": "pipeline_archive_node",
    "sku.scenes.backfill": "pipeline_backfill_scenes",
    "sku.assets.list": "pipeline_list_assets",
    "sku.creative-packs.list": "pipeline_list_creative_packs",
    "sku.audience-pack.get": "pipeline_get_audience_pack",
    "sku.creative-pack.get": "pipeline_get_creative_pack",
    "sku.audience-portraits.list": "pipeline_list_audience_portraits",
    "sku.audience-portrait.get": "pipeline_get_audience_portrait",
    "sku.ad-metrics.record": "record_ad_metrics",
    "sku.ad-metrics.record-batch": "record_ad_metrics_batch",
    "sku.asset-performance.list": "pipeline_list_asset_performance",
    "sku.asset-lineage.get": "pipeline_get_asset_lineage",
    "video.storyboard.reverse": "reverse_storyboard_video",
    "sku.content-audience.embed": "embed_content_and_audience",
    "sku.audience-match.predict": "predict_audience_match",
    "experiment.create": "experiment_create",
    "experiment.list": "experiment_list",
    "experiment.get": "experiment_get",
    "experiment.status": "experiment_status",
    "experiment.prescreen": "experiment_prescreen_round",
    "experiment.round.register": "experiment_register_round",
    "experiment.winner.lock": "experiment_lock_winner",
    "experiment.distill": "experiment_distill",
    "experiment.changelog": "experiment_changelog",
    "experiment.seed.next": "experiment_next_version_seed",
    "experiment.script.adopt": "experiment_adopt_script",
    "experiment.arm.attach": "experiment_attach_arm",
    "p0.preflight": "p0_preflight_video_production",
    "p0.inputs.list": "p0_list_video_production_inputs",
    "p0.orders.list": "p0_list_video_production_orders",
    "p0.order.get": "p0_get_video_production_order",
    "p0.order.create": "p0_create_video_production_order",
    "p0.bridge-review.generate": "p0_generate_planting_bridge_candidates",
    "p0.content-spec.build": "p0_build_video_content_spec",
    "p0.scripts.generate": "p0_generate_video_script_candidates",
    "p0.scripts.review": "p0_review_video_script_candidates",
    "p0.script.select": "p0_select_video_script",
    "p0.prompt.prepare": "p0_prepare_video_prompt",
    "p0.candidate-vector.assess": "p0_assess_video_candidate_vector_match",
    "p0.execution-vector.assess": "p0_assess_video_execution_vector_match",
    "p0.content-match.assess": "p0_assess_video_content_match",
    "p0.approval.request": "p0_request_video_generation_approval",
    "p0.generation.start": "p0_start_video_generation",
    "p0.generation.recover": "p0_recover_video_generation",
    "p0.raw-qa.run": "p0_run_raw_video_qa",
    "p0.final.compose": "p0_compose_video_final",
    "p0.final-qa.run": "p0_run_final_video_qa",
    "p0.package.release": "p0_release_video_package",
    "p0.production.cancel": "p0_cancel_video_production",
}


@dataclass(frozen=True)
class ToolExecutionFailure(Exception):
    status_code: int
    code: str
    detail: str
    hint: str = ""

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"ok": False, "error": self.code, "detail": self.detail}
        if self.hint:
            body["hint"] = self.hint
        return body


def operation_tool(operation_id: str) -> str:
    try:
        return OPERATION_REGISTRY[operation_id]
    except KeyError as exc:
        raise ToolExecutionFailure(404, "unknown_operation", operation_id) from exc


def _registered_tool(tool_name: str) -> Mapping[str, Any]:
    # Importing the canonical MCP server populates TOOL_REGISTRY exactly once.
    from app.mcp import server as _server  # noqa: F401
    from app.mcp.audit import TOOL_REGISTRY

    registration = TOOL_REGISTRY.get(tool_name)
    if not registration:
        raise ToolExecutionFailure(404, "unknown_tool", tool_name)
    fn = registration["fn"]
    module = sys.modules.get(getattr(fn, "__module__", ""))
    current = getattr(module, tool_name, None) if module else None
    if current is not None and current is not fn:
        return {**registration, "fn": current, "validation_fn": fn}
    return registration


def _validated_args(fn: Any, args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolExecutionFailure(422, "body_must_be_json_object", type(args).__name__)
    signature = inspect.signature(fn)
    if any(parameter.kind is parameter.VAR_KEYWORD for parameter in signature.parameters.values()) and not any(
        parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        for parameter in signature.parameters.values()
    ):
        return dict(args)
    try:
        type_hints = get_type_hints(fn)
    except Exception:
        type_hints = {}
    fields: dict[str, tuple[Any, Any]] = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        annotation = type_hints.get(name, parameter.annotation if parameter.annotation is not inspect.Parameter.empty else Any)
        default = parameter.default if parameter.default is not inspect.Parameter.empty else ...
        fields[name] = (annotation, default)
    try:
        model = create_model(f"ToolInput_{getattr(fn, '__name__', 'anonymous')}", **fields)
        validated = model.model_validate(args)
        # exclude_unset keeps wrapper defaults authoritative and avoids turning omitted
        # nullable parameters into explicit None when the function has another default.
        values = validated.model_dump()
        signature.bind(**values)
        return values
    except (ValidationError, TypeError) as exc:
        raise ToolExecutionFailure(
            422,
            "bad_args",
            str(exc),
            "Use the MCP catalog input_schema for the registered tool.",
        ) from exc


async def execute_registered_tool(
    *,
    tool_name: str,
    args: Any,
    route_family: str,
    timeout_seconds: float | None = None,
) -> Any:
    """Validate and invoke the audited wrapper; Gate/trace/audit stay inside it."""

    registration = _registered_tool(tool_name)
    fn = registration["fn"]
    values = _validated_args(registration.get("validation_fn", fn), args)
    configured_timeout = registration.get("timeout_seconds")
    timeout = timeout_seconds or configured_timeout or 300
    try:
        result = await asyncio.wait_for(fn(**values), timeout=max(0.001, float(timeout)))
        from app.services.compatibility import append_route_telemetry
        await append_route_telemetry(route_family=route_family, capability_id=tool_name, state="completed")
        return result
    except asyncio.TimeoutError as exc:
        from app.services.compatibility import append_route_telemetry
        await append_route_telemetry(route_family=route_family, capability_id=tool_name, state="timeout")
        raise ToolExecutionFailure(504, "tool_timeout", f"{tool_name} via {route_family}") from exc
