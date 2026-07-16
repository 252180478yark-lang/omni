from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from app.database import close_pool, get_pool, init_pool
from app.services import ai_hub_client, pipeline_lineage
from app.services.media_reference_manifest import build_reference_manifest


@pytest_asyncio.fixture(scope="module", autouse=True)
async def database_pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def db_connection():
    async with get_pool().acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            yield connection
        finally:
            await transaction.rollback()


class _ConnectionPool:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def fetch(self, query: str, *args: Any) -> Any:
        return await self.connection.fetch(query, *args)


async def _make_script_with_two_arms(connection: Any) -> dict[str, Any]:
    token = uuid4().hex[:16]
    sku_id = f"SKU-REF-{token}"
    await connection.execute(
        "INSERT INTO public.mvp_sku(id,name,douyin_product_id) VALUES($1,$2,$3)",
        sku_id,
        f"reference test {token}",
        f"DY-REF-{token}",
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
        ") VALUES($1,$2,$3,'# script','video_planting','planting','adopted') RETURNING id",
        audience_record_id,
        matrix_id,
        sku_id,
    )
    experiment_id = await connection.fetchval(
        "INSERT INTO pipeline.experiments("
        "sku_id,audience_record_id,audience_run_id,matrix_run_id,intent,north_star_metric,track"
        ") VALUES($1,$2,$3,$4,'planting','a3_ratio','ai_video') RETURNING id",
        sku_id,
        audience_record_id,
        audience_run_id,
        matrix_id,
    )
    round_id = await connection.fetchval(
        "INSERT INTO pipeline.experiment_rounds(experiment_id,sku_id,round_no,swept_variable) "
        "VALUES($1,$2,1,'opening_hook_3s') RETURNING id",
        experiment_id,
        sku_id,
    )
    arm_ids = []
    for label in ("A", "B"):
        arm_ids.append(
            await connection.fetchval(
                "INSERT INTO pipeline.experiment_arms("
                "round_id,experiment_id,sku_id,round_no,swept_variable,variable_value,"
                "arm_label,script_id,production_mode"
                ") VALUES($1,$2,$3,1,'opening_hook_3s',$4,$5,$6,'ai_video') RETURNING id",
                round_id,
                experiment_id,
                sku_id,
                f"hook-{label}",
                label,
                script_id,
            )
        )
    return {
        "sku_id": sku_id,
        "script_id": script_id,
        "experiment_id": experiment_id,
        "arm_a": arm_ids[0],
        "arm_b": arm_ids[1],
    }


async def _insert_sheet(
    connection: Any,
    graph: dict[str, Any],
    *,
    asset_id: UUID,
    role: str | None,
    status: str,
    file_url: str,
    arm_id: Any,
    created_at: str,
) -> None:
    await connection.execute(
        "INSERT INTO pipeline.assets("
        "id,script_id,sku_id,asset_type,status,file_url,character_role,"
        "experiment_id,experiment_arm_id,created_at"
        ") VALUES($1,$2,$3,'character_sheet',$4,$5,$6,$7,$8,$9)",
        asset_id,
        graph["script_id"],
        graph["sku_id"],
        status,
        file_url,
        role,
        graph["experiment_id"] if arm_id is not None else None,
        arm_id,
        datetime.fromisoformat(created_at.replace("Z", "+00:00")),
    )


async def _seed_mixed_sheets(
    connection: Any,
    graph: dict[str, Any],
    tmp_path: Path,
) -> dict[str, UUID]:
    paths = {
        name: tmp_path / f"{name}.png"
        for name in (
            "hero_old",
            "hero_latest",
            "hero_discarded",
            "tie_low",
            "tie_high",
            "published",
            "archived",
            "blank",
            "tab_only",
            "newline_only",
            "wrong_arm",
            "legacy",
        )
    }
    for name, path in paths.items():
        path.write_bytes(name.encode("utf-8"))

    ids = {name: UUID(int=index) for index, name in enumerate(paths, start=1)}
    rows = [
        ("hero_old", "hero", "draft", graph["arm_a"], "2026-01-01T00:00:00Z"),
        ("hero_latest", "hero", "adopted", graph["arm_a"], "2026-01-02T00:00:00Z"),
        ("hero_discarded", "hero", "discarded", graph["arm_a"], "2026-01-03T00:00:00Z"),
        ("tie_low", "tie", "draft", graph["arm_a"], "2026-01-04T00:00:00Z"),
        ("tie_high", "tie", "draft", graph["arm_a"], "2026-01-04T00:00:00Z"),
        ("published", "published", "published", graph["arm_a"], "2026-01-02T00:00:00Z"),
        ("archived", "archived", "archived", graph["arm_a"], "2026-01-05T00:00:00Z"),
        ("blank", "   ", "draft", graph["arm_a"], "2026-01-05T00:00:00Z"),
        ("tab_only", "\t", "draft", graph["arm_a"], "2026-01-05T00:00:00Z"),
        ("newline_only", "\n", "draft", graph["arm_a"], "2026-01-05T00:00:00Z"),
        ("wrong_arm", "wrong-arm", "draft", graph["arm_b"], "2026-01-05T00:00:00Z"),
        ("legacy", "legacy", "draft", None, "2026-01-05T00:00:00Z"),
    ]
    for name, role, status, arm_id, created_at in rows:
        await _insert_sheet(
            connection,
            graph,
            asset_id=ids[name],
            role=role,
            status=status,
            file_url=str(paths[name]),
            arm_id=arm_id,
            created_at=created_at,
        )
    return ids


@pytest.mark.asyncio
async def test_character_sheet_helper_returns_latest_usable_matching_arm(
    monkeypatch: pytest.MonkeyPatch,
    db_connection: Any,
    tmp_path: Path,
) -> None:
    graph = await _make_script_with_two_arms(db_connection)
    ids = await _seed_mixed_sheets(db_connection, graph, tmp_path)
    monkeypatch.setattr(
        pipeline_lineage,
        "get_pool",
        lambda: _ConnectionPool(db_connection),
    )

    rows = await pipeline_lineage.list_character_sheets_for_script(
        str(graph["script_id"]),
        experiment_arm_id=str(graph["arm_a"]),
    )
    legacy_rows = await pipeline_lineage.list_character_sheets_for_script(
        str(graph["script_id"]),
        experiment_arm_id=None,
    )

    assert {row["character_role"]: row["id"] for row in rows} == {
        "hero": str(ids["hero_latest"]),
        "published": str(ids["published"]),
        "tie": str(ids["tie_high"]),
    }
    assert [(row["character_role"], row["id"]) for row in legacy_rows] == [
        ("legacy", str(ids["legacy"]))
    ]


@pytest.mark.asyncio
async def test_only_latest_usable_sheets_reach_manifest_and_provider_body(
    monkeypatch: pytest.MonkeyPatch,
    db_connection: Any,
    tmp_path: Path,
) -> None:
    graph = await _make_script_with_two_arms(db_connection)
    ids = await _seed_mixed_sheets(db_connection, graph, tmp_path)
    monkeypatch.setattr(
        pipeline_lineage,
        "get_pool",
        lambda: _ConnectionPool(db_connection),
    )
    rows = await pipeline_lineage.list_character_sheets_for_script(
        str(graph["script_id"]),
        experiment_arm_id=str(graph["arm_a"]),
    )
    expected_ids = [
        str(ids["hero_latest"]),
        str(ids["published"]),
        str(ids["tie_high"]),
    ]

    manifest = build_reference_manifest(
        sku_id=graph["sku_id"],
        arm_id=str(graph["arm_a"]),
        face_assets=rows,
        product_assets=[],
        provider="seedance",
        model="seedance-2-0",
    )
    prepared, sent = ai_hub_client.prepare_video_reference_images(rows, [])
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, Any]:
            return {"task_id": "task-1"}

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(ai_hub_client.httpx, "AsyncClient", FakeAsyncClient)
    await ai_hub_client.AIHubClient(base_url="http://hub.test").generate_video_v2(
        prompt="prompt",
        prepared_reference_images=prepared,
    )

    assert [item["id"] for item in manifest["items"]] == expected_ids
    assert [item["id"] for item in sent["items"]] == expected_ids
    assert len(captured["json"]["reference_images"]) == len(expected_ids)
