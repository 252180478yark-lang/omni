"""Database contract tests for migration 068 (AI planting parity)."""
from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from app.database import close_pool, get_pool, init_pool


EXPECTED_VIEW_COLUMNS = [
    ("experiment_id", "uuid"),
    ("sku_id", "character varying"),
    ("intent", "text"),
    ("round_no", "integer"),
    ("arm_id", "uuid"),
    ("arm_label", "text"),
    ("swept_variable", "text"),
    ("variable_value", "text"),
    ("hypothesis", "text"),
    ("script_id", "uuid"),
    ("north_star_metric", "text"),
    ("north_star_direction", "text"),
    ("is_winner", "boolean"),
    ("is_baseline_locked", "boolean"),
    ("forced", "boolean"),
    ("n_videos", "bigint"),
    ("north_star_avg", "numeric"),
    ("north_star_sum", "numeric"),
    ("sample_status", "text"),
    ("production_mode", "text"),
    ("impressions_sum", "numeric"),
    ("predicted_match_score", "numeric"),
    ("a3_numerator_sum", "numeric"),
    ("a3_denominator_sum", "numeric"),
    ("a3_ratio_pooled", "numeric"),
    ("spend_sum", "numeric"),
    ("cpm_pooled", "numeric"),
    ("play_3s_sum", "numeric"),
    ("play_3s_rate_pooled", "numeric"),
    ("completion_numerator_sum", "numeric"),
    ("completion_denominator_sum", "numeric"),
    ("completion_denominator_type", "text"),
    ("completion_rate_pooled", "numeric"),
    ("metric_coverage_complete", "boolean"),
]


@pytest_asyncio.fixture(scope="module", autouse=True)
async def database_pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def db_connection():
    """Run each data-contract test in a transaction that is always rolled back."""
    async with get_pool().acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            yield connection
        finally:
            await transaction.rollback()


async def _make_arm(connection, *, intent: str, north_star_metric: str, label: str = "A"):
    token = uuid4().hex[:16]
    sku_id = f"SKU-TEST-068-{token}"
    await connection.execute(
        "INSERT INTO public.mvp_sku(id,name,douyin_product_id) VALUES($1,$2,$3)",
        sku_id,
        f"migration 068 test {token}",
        f"DY-068-{token}",
    )
    matrix_id = await connection.fetchval(
        "INSERT INTO pipeline.matrix_runs(sku_id,matrix_md,status) "
        "VALUES($1,'# matrix','adopted') RETURNING id",
        sku_id,
    )
    audience_run_id = await connection.fetchval(
        "INSERT INTO pipeline.audience_runs(matrix_run_id,sku_id,audience_md,status,record_count) "
        "VALUES($1,$2,'# audience','adopted',1) RETURNING id",
        matrix_id,
        sku_id,
    )
    audience_record_id = await connection.fetchval(
        "INSERT INTO pipeline.audience_records("
        "audience_run_id,matrix_run_id,sku_id,ordinal,name,raw_md_segment,status,selected_for_pack"
        ") VALUES($1,$2,$3,1,'test audience','# record','adopted',true) RETURNING id",
        audience_run_id,
        matrix_id,
        sku_id,
    )
    script_id = await connection.fetchval(
        "INSERT INTO pipeline.scripts("
        "audience_record_id,matrix_run_id,sku_id,script_md,kind,intent,status"
        ") VALUES($1,$2,$3,'# script',$4,$5,'adopted') RETURNING id",
        audience_record_id,
        matrix_id,
        sku_id,
        "video_planting" if intent == "planting" else "video_soft_ad",
        intent,
    )
    experiment_id = await connection.fetchval(
        "INSERT INTO pipeline.experiments("
        "sku_id,audience_record_id,audience_run_id,matrix_run_id,intent,north_star_metric,track"
        ") VALUES($1,$2,$3,$4,$5,$6,'ai_video') RETURNING id",
        sku_id,
        audience_record_id,
        audience_run_id,
        matrix_id,
        intent,
        north_star_metric,
    )
    round_id = await connection.fetchval(
        "INSERT INTO pipeline.experiment_rounds(experiment_id,sku_id,round_no,swept_variable) "
        "VALUES($1,$2,1,'pain_scene_bridge') RETURNING id",
        experiment_id,
        sku_id,
    )
    arm_id = await connection.fetchval(
        "INSERT INTO pipeline.experiment_arms("
        "round_id,experiment_id,sku_id,round_no,swept_variable,variable_value,arm_label,script_id,production_mode"
        ") VALUES($1,$2,$3,1,'pain_scene_bridge','test bridge',$4,$5,'ai_video') RETURNING id",
        round_id,
        experiment_id,
        sku_id,
        label,
        script_id,
    )
    return {
        "sku_id": sku_id,
        "matrix_id": matrix_id,
        "audience_record_id": audience_record_id,
        "script_id": script_id,
        "experiment_id": experiment_id,
        "round_id": round_id,
        "arm_id": arm_id,
    }


async def _insert_asset(
    connection,
    graph,
    metrics,
    *,
    asset_status: str = "adopted",
    generation_set_status: str | None = None,
    post_gate_pass: bool = True,
    selected: bool = True,
):
    asset_id = uuid4()
    generation_set_id = None
    if generation_set_status is not None:
        generation_set_id = await connection.fetchval(
            "INSERT INTO pipeline.video_generation_sets("
            "sku_id,script_id,experiment_id,experiment_arm_id,selected_assets,"
            "post_video_group_gate,profile_version,status"
            ") VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,'planting-v1',$7) RETURNING id",
            graph["sku_id"],
            graph["script_id"],
            graph["experiment_id"],
            graph["arm_id"],
            json.dumps([str(asset_id)] if selected else []),
            json.dumps({"pass": post_gate_pass}),
            generation_set_status,
        )
    await connection.execute(
        "INSERT INTO pipeline.assets("
        "id,script_id,audience_record_id,matrix_run_id,sku_id,asset_type,status,ad_metrics,"
        "experiment_id,experiment_arm_id,generation_set_id,file_url"
        ") VALUES($1,$2,$3,$4,$5,'video',$6,$7::jsonb,$8,$9,$10,$11)",
        asset_id,
        graph["script_id"],
        graph["audience_record_id"],
        graph["matrix_id"],
        graph["sku_id"],
        asset_status,
        json.dumps(metrics),
        graph["experiment_id"],
        graph["arm_id"],
        generation_set_id,
        f"test://068/{asset_id}",
    )
    return asset_id, generation_set_id


async def _arm_result(connection, arm_id):
    return await connection.fetchrow(
        "SELECT * FROM pipeline.v_experiment_round_results WHERE arm_id=$1", arm_id
    )


@pytest.mark.asyncio
async def test_planting_schema_has_contract_policy_and_generation_sets():
    pool = get_pool()
    script_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='pipeline' "
        "AND table_name='scripts' AND column_name='content_contract'"
    )
    policy_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='pipeline' "
        "AND table_name='experiments' AND column_name='evaluation_policy'"
    )
    set_table = await pool.fetchval(
        "SELECT to_regclass('pipeline.video_generation_sets')::text"
    )
    asset_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='pipeline' "
        "AND table_name='assets' AND column_name='generation_set_id'"
    )
    assert (script_col, policy_col, set_table, asset_col) == (
        1,
        1,
        "pipeline.video_generation_sets",
        1,
    )


@pytest.mark.asyncio
async def test_new_json_columns_and_generation_set_constraints_are_strict():
    pool = get_pool()
    columns = await pool.fetch(
        "SELECT table_name,column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema='pipeline' AND ("
        "(table_name='scripts' AND column_name='content_contract') OR "
        "(table_name='experiments' AND column_name='evaluation_policy') OR "
        "table_name='video_generation_sets') ORDER BY table_name,ordinal_position"
    )
    by_key = {(row["table_name"], row["column_name"]): row for row in columns}
    for key in (("scripts", "content_contract"), ("experiments", "evaluation_policy")):
        assert by_key[key]["data_type"] == "jsonb"
        assert by_key[key]["is_nullable"] == "NO"
        assert "'{}'::jsonb" in by_key[key]["column_default"]

    expected_set_columns = {
        "id": "uuid",
        "sku_id": "character varying",
        "script_id": "uuid",
        "experiment_id": "uuid",
        "experiment_arm_id": "uuid",
        "expected_segment_manifest": "jsonb",
        "selected_assets": "jsonb",
        "reference_manifest": "jsonb",
        "pre_video_group_gate": "jsonb",
        "post_video_group_gate": "jsonb",
        "profile_version": "text",
        "status": "text",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
    }
    assert {
        row["column_name"]: row["data_type"]
        for row in columns
        if row["table_name"] == "video_generation_sets"
    } == expected_set_columns

    constraints = await pool.fetch(
        "SELECT c.conname,c.confdeltype,pg_get_constraintdef(c.oid) AS definition "
        "FROM pg_constraint c WHERE c.conrelid IN ("
        "'pipeline.scripts'::regclass,'pipeline.experiments'::regclass,"
        "'pipeline.video_generation_sets'::regclass,'pipeline.assets'::regclass)"
    )
    definitions = {row["conname"]: row["definition"] for row in constraints}
    assert "jsonb_typeof(content_contract) = 'object'" in definitions["scripts_content_contract_object_check"]
    assert "jsonb_typeof(evaluation_policy) = 'object'" in definitions["experiments_evaluation_policy_object_check"]
    for field, expected_type in {
        "expected_segment_manifest": "array",
        "selected_assets": "array",
        "reference_manifest": "object",
        "pre_video_group_gate": "object",
        "post_video_group_gate": "object",
    }.items():
        assert field in definitions[f"video_generation_sets_{field}_check"]
        assert f"'{expected_type}'" in definitions[f"video_generation_sets_{field}_check"]
    assert "btrim(profile_version) <> ''" in definitions["video_generation_sets_profile_version_check"]
    assert all(status in definitions["video_generation_sets_status_check"] for status in (
        "draft", "ready", "adopted", "discarded"
    ))
    assert all(asset_type in definitions["assets_type_check"] for asset_type in (
        "image", "image_first", "image_last", "video", "character_sheet", "product_reference"
    ))
    assert "assets_duration_nonneg" in definitions
    assert "assets_status_check" in definitions

    asset_fk = next(row for row in constraints if row["conname"] == "assets_generation_set_id_fkey")
    assert asset_fk["confdeltype"] in ("r", b"r")
    assert "ON DELETE RESTRICT" in asset_fk["definition"]

    indexes = {
        row["indexname"]: row["indexdef"]
        for row in await pool.fetch(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='pipeline' "
            "AND tablename IN ('video_generation_sets','assets')"
        )
    }
    assert "idx_video_generation_sets_arm" in indexes
    assert "idx_assets_generation_set" in indexes
    product_index = indexes["idx_product_reference_file"]
    assert "UNIQUE INDEX" in product_index
    assert "asset_type = 'product_reference'" in product_index
    assert "file_url IS NOT NULL" in product_index


@pytest.mark.asyncio
async def test_experiment_results_view_has_exact_compatible_34_column_contract():
    rows = await get_pool().fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='pipeline' AND table_name='v_experiment_round_results' "
        "ORDER BY ordinal_position"
    )
    assert [(row["column_name"], row["data_type"]) for row in rows] == EXPECTED_VIEW_COLUMNS


@pytest.mark.asyncio
async def test_experiment_results_view_uses_shape_safe_eligibility_predicates():
    definition = await get_pool().fetchval(
        "SELECT pg_get_viewdef('pipeline.v_experiment_round_results'::regclass,true)"
    )
    compact = " ".join(definition.split())
    assert "#> '{_validation,suspect}'" in compact
    assert "= '{}'::jsonb" in compact
    assert "= 'false'::jsonb" in compact
    assert "post_video_group_gate @> '{\"pass\": true}'::jsonb" in compact
    assert "jsonb_typeof(gs.selected_assets) = 'array'" in compact
    assert "gs.selected_assets ? a.id::text" in compact
    assert "suspect}')::boolean" not in compact
    assert "suspect}'::text[])::boolean" not in compact


@pytest.mark.asyncio
async def test_generation_set_fk_cannot_turn_governed_asset_into_legacy(db_connection):
    graph = await _make_arm(db_connection, intent="planting", north_star_metric="a3_ratio")
    asset_id, generation_set_id = await _insert_asset(
        db_connection,
        graph,
        {"new_a3": 1, "a3_eligible_users": 10},
        generation_set_status="adopted",
    )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with db_connection.transaction():
            await db_connection.execute(
                "DELETE FROM pipeline.video_generation_sets WHERE id=$1", generation_set_id
            )
    assert await db_connection.fetchval(
        "SELECT generation_set_id FROM pipeline.assets WHERE id=$1", asset_id
    ) == generation_set_id


@pytest.mark.asyncio
async def test_product_reference_is_allowed_and_globally_unique(db_connection):
    graph = await _make_arm(db_connection, intent="planting", north_star_metric="a3_ratio")
    file_url = f"test://product-reference/{uuid4()}"
    first_id = await db_connection.fetchval(
        "INSERT INTO pipeline.assets(sku_id,asset_type,status,file_url) "
        "VALUES($1,'product_reference','adopted',$2) RETURNING id",
        graph["sku_id"],
        file_url,
    )
    assert first_id is not None
    second_sku = f"SKU-TEST-068-{uuid4().hex[:16]}"
    await db_connection.execute(
        "INSERT INTO public.mvp_sku(id,name,douyin_product_id) VALUES($1,'second product ref',$2)",
        second_sku,
        f"DY-068-{uuid4().hex[:16]}",
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        async with db_connection.transaction():
            await db_connection.execute(
                "INSERT INTO pipeline.assets(sku_id,asset_type,status,file_url) "
                "VALUES($1,'product_reference','adopted',$2)",
                second_sku,
                file_url,
            )


@pytest.mark.asyncio
async def test_planting_metrics_pool_raw_counts_and_missing_a3_denominator_fails_closed(db_connection):
    graph = await _make_arm(db_connection, intent="planting", north_star_metric="a3_ratio")
    await _insert_asset(db_connection, graph, {
        "a3_ratio": 0.9,
        "new_a3": 10,
        "a3_eligible_users": 100,
        "spend": 20,
        "impressions": 1000,
        "play_3s": 500,
        "play_complete": 250,
        "completion_denominator": 1000,
        "completion_denominator_type": "impressions",
        "currency": "CNY",
    })
    await _insert_asset(db_connection, graph, {
        "a3_ratio": 0.8,
        "new_a3": 30,
        "a3_eligible_users": 200,
        "spend": 40,
        "impressions": 2000,
        "play_3s": 900,
        "play_complete": 400,
        "completion_denominator": 2000,
        "completion_denominator_type": "impressions",
        "currency": "CNY",
    })
    row = await _arm_result(db_connection, graph["arm_id"])
    assert row["metric_coverage_complete"] is True
    assert row["a3_numerator_sum"] == Decimal("40")
    assert row["a3_denominator_sum"] == Decimal("300")
    assert row["a3_ratio_pooled"] == Decimal("0.133333")
    assert row["north_star_avg"] == Decimal("0.133333")
    assert row["north_star_sum"] == Decimal("1.7000")
    assert row["spend_sum"] == Decimal("60")
    assert row["cpm_pooled"] == Decimal("20.000000")
    assert row["play_3s_sum"] == Decimal("1400")
    assert row["play_3s_rate_pooled"] == Decimal("0.466667")
    assert row["completion_numerator_sum"] == Decimal("650")
    assert row["completion_denominator_sum"] == Decimal("3000")
    assert row["completion_denominator_type"] == "impressions"
    assert row["completion_rate_pooled"] == Decimal("0.216667")

    await _insert_asset(db_connection, graph, {
        "a3_ratio": 0.7,
        "new_a3": 5,
        "spend": 1,
        "impressions": 100,
        "play_3s": 50,
        "play_complete": 20,
        "completion_denominator": 100,
        "completion_denominator_type": "impressions",
        "currency": "CNY",
    })
    incomplete = await _arm_result(db_connection, graph["arm_id"])
    assert incomplete["metric_coverage_complete"] is False
    assert incomplete["a3_numerator_sum"] is None
    assert incomplete["a3_denominator_sum"] is None
    assert incomplete["a3_ratio_pooled"] is None
    assert incomplete["north_star_avg"] is None


@pytest.mark.asyncio
async def test_soft_ad_keeps_legacy_completion_average(db_connection):
    graph = await _make_arm(
        db_connection, intent="soft_ad", north_star_metric="completion_rate"
    )
    await _insert_asset(db_connection, graph, {"completion_rate": 0.2, "impressions": 100})
    await _insert_asset(db_connection, graph, {"completion_rate": 0.4, "impressions": 200})
    row = await _arm_result(db_connection, graph["arm_id"])
    assert row["n_videos"] == 2
    assert row["north_star_avg"] == Decimal("0.3000")
    assert row["north_star_sum"] == Decimal("0.6000")
    assert row["impressions_sum"] == Decimal("300")
    assert row["metric_coverage_complete"] is False


@pytest.mark.asyncio
async def test_only_clean_selected_adopted_generation_assets_are_pooled(db_connection):
    graph = await _make_arm(db_connection, intent="planting", north_star_metric="a3_ratio")
    base = {"a3_ratio": 0.1, "new_a3": 1, "a3_eligible_users": 10}
    # Missing suspect, empty-object suspect and boolean false are all explicitly clean.
    await _insert_asset(db_connection, graph, base)
    await _insert_asset(db_connection, graph, {**base, "_validation": {"suspect": {}}})
    await _insert_asset(db_connection, graph, {**base, "_validation": {"suspect": False}})
    # Every following asset would distort the result if the eligibility predicate admitted it.
    await _insert_asset(db_connection, graph, {**base, "_validation": {"suspect": True}})
    await _insert_asset(db_connection, graph, base, asset_status="discarded")
    await _insert_asset(
        db_connection, graph, base, generation_set_status="adopted", selected=False
    )
    await _insert_asset(
        db_connection, graph, base, generation_set_status="discarded", selected=True
    )
    await _insert_asset(
        db_connection,
        graph,
        base,
        generation_set_status="adopted",
        post_gate_pass=False,
        selected=True,
    )
    row = await _arm_result(db_connection, graph["arm_id"])
    assert row["metric_coverage_complete"] is True
    assert row["a3_numerator_sum"] == Decimal("3")
    assert row["a3_denominator_sum"] == Decimal("30")
    assert row["a3_ratio_pooled"] == Decimal("0.100000")
