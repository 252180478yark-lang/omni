"""内容版本迭代闭环 块0+块A（migration 064）真 DB 测试：

- attach_arm：采纳即挂臂（单条追加，自动派生臂标 A/B + 臂码 R{round}{label} + 脚本 draft→adopted）
- record_ad_metrics_batch：巨量素材报表 CSV 按臂码匹配回灌（dry_run 预览 / 真写 / 未匹配上报）
- experiment_status：露出 impressions 曝光量 + arm_code + 臂间曝光差≥3 倍 winner 存疑告警（块0b）
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.services import experiment_lab as lab
from app.services import pipeline_lineage as pl

SKU = "SKU-TEST-VILOOP"
SKU_ADOPT = "SKU-TEST-ADOPT"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    pool = get_pool()
    # assets.experiment_id/script_id 是 ON DELETE SET NULL，按 sku_id 直接清；experiment 级联 rounds/arms
    for s in (SKU, SKU_ADOPT):
        await pool.execute("DELETE FROM pipeline.assets WHERE sku_id = $1", s)
        await pool.execute("DELETE FROM pipeline.experiments WHERE sku_id = $1", s)
        await pool.execute("DELETE FROM pipeline.scripts WHERE sku_id = $1", s)
    await close_pool()


@pytest_asyncio.fixture
async def exp_with_two_scripts():
    """建一个种草实验 + 2 条 draft 脚本，返回 (experiment_id, [script_id, script_id])。"""
    r = await lab.create_experiment(
        sku_id=SKU, intent="planting", audience_record_id=str(uuid.uuid4()))
    assert r["ok"], r
    assert r["experiment"]["north_star_metric"] == "completion_rate"
    exp_id = r["experiment"]["id"]
    pool = get_pool()
    sids = []
    for _ in range(2):
        sid = await pool.fetchval(
            "INSERT INTO pipeline.scripts (sku_id, script_md, status, kind) "
            "VALUES ($1,$2,'draft','director_brief') RETURNING id::text", SKU, "测试brief")
        sids.append(sid)
    return exp_id, sids


@pytest.mark.asyncio
async def test_attach_arm_appends_and_adopts(exp_with_two_scripts):
    exp_id, sids = exp_with_two_scripts
    pool = get_pool()

    # 第 1 条：新开 round1 扫 opening_hook_3s → 臂 A / 码 R1A，脚本被采纳
    a1 = await lab.attach_arm(experiment_id=exp_id, script_id=sids[0],
                              variable_value="悬念式钩子", swept_variable="opening_hook_3s")
    assert a1["ok"], a1
    assert a1["arm"]["arm_label"] == "A" and a1["arm"]["arm_code"] == "R1A"
    assert a1["arm"]["round_no"] == 1 and a1["arm"]["swept_variable"] == "opening_hook_3s"
    assert a1["script_adopted"] is True
    assert await pool.fetchval(
        "SELECT status FROM pipeline.scripts WHERE id=$1::uuid", sids[0]) == "adopted"

    # 第 2 条：不给轮号 → 自动追加到 open 的 round1 → 臂 B / 码 R1B
    a2 = await lab.attach_arm(experiment_id=exp_id, script_id=sids[1], variable_value="痛点式钩子")
    assert a2["ok"], a2
    assert a2["arm"]["arm_label"] == "B" and a2["arm"]["arm_code"] == "R1B"
    assert a2["arm"]["round_no"] == 1


@pytest.mark.asyncio
async def test_attach_arm_guards(exp_with_two_scripts):
    exp_id, sids = exp_with_two_scripts
    # 没有 open 轮又不给 swept_variable → 拦
    bad = await lab.attach_arm(experiment_id=exp_id, script_id=sids[0], variable_value="x")
    assert not bad["ok"] and bad["error"] == "missing_swept_variable"
    # 建轮后同取值不重复挂
    await lab.attach_arm(experiment_id=exp_id, script_id=sids[0],
                         variable_value="悬念", swept_variable="opening_hook_3s")
    dup = await lab.attach_arm(experiment_id=exp_id, script_id=sids[1], variable_value="悬念")
    assert not dup["ok"] and dup["error"] == "variable_value_exists"
    # 脚本 sku 不符 → 拦
    pool = get_pool()
    other = await pool.fetchval(
        "INSERT INTO pipeline.scripts (sku_id, script_md, status) VALUES ('SKU-OTHER-X','m','draft') "
        "RETURNING id::text")
    try:
        mm = await lab.attach_arm(experiment_id=exp_id, script_id=other, variable_value="痛点")
        assert not mm["ok"] and mm["error"] == "script_sku_mismatch"
    finally:
        await pool.execute("DELETE FROM pipeline.scripts WHERE id=$1::uuid", other)


@pytest.mark.asyncio
async def test_batch_match_and_status_exposure(exp_with_two_scripts):
    exp_id, sids = exp_with_two_scripts
    await lab.attach_arm(experiment_id=exp_id, script_id=sids[0],
                         variable_value="悬念式钩子", swept_variable="opening_hook_3s")
    await lab.attach_arm(experiment_id=exp_id, script_id=sids[1], variable_value="痛点式钩子")

    csv = ("素材名称,视频ID,完播率,曝光量,转化率\n"
           "和田宽_R1A_悬念,V001,0.32,8000,0.02\n"
           "和田宽_R1B_痛点,V002,0.28,30000,0.018\n"
           "没臂码的无关视频,V099,0.5,100,0.01\n")

    # dry_run：匹配 2 / 未匹配 1 / 不写库；列名自动识别
    dry = await pl.record_ad_metrics_batch(experiment_id=exp_id, csv_text=csv, dry_run=True)
    assert dry["ok"]
    assert dry["summary"]["matched"] == 2 and dry["summary"]["unmatched"] == 1
    assert dry["summary"]["applied"] == 0
    assert dry["columns"]["name_column"] == "素材名称"
    assert dry["columns"]["id_column"] == "视频ID"
    assert dry["columns"]["metric_columns"]["完播率"] == "completion_rate"
    assert dry["columns"]["metric_columns"]["曝光量"] == "impressions"

    # 真写：2 条落库
    real = await pl.record_ad_metrics_batch(experiment_id=exp_id, csv_text=csv, dry_run=False)
    assert real["ok"] and real["summary"]["applied"] == 2

    # 排名：曝光量透出 + 臂码 + 曝光差 3.75x → 偏斜告警；n=1<5 → 不能正常锁
    s = await lab.experiment_status(exp_id)
    assert s["ok"]
    by = {a["arm_label"]: a for a in s["arms"]}
    assert by["A"]["impressions"] == 8000 and by["B"]["impressions"] == 30000
    assert by["A"]["arm_code"] == "R1A" and by["B"]["arm_code"] == "R1B"
    assert by["A"]["north_star_avg"] == 0.32
    assert s["exposure_skew_warning"] is not None
    assert s["can_lock"] is False


@pytest.mark.asyncio
async def test_next_version_seed_and_changelog(exp_with_two_scripts):
    exp_id, sids = exp_with_two_scripts
    a1 = await lab.attach_arm(experiment_id=exp_id, script_id=sids[0],
                              variable_value="悬念式钩子", swept_variable="opening_hook_3s")
    await lab.attach_arm(experiment_id=exp_id, script_id=sids[1], variable_value="痛点式钩子")
    csv = "素材名称,视频ID,完播率,曝光量\n和田宽_R1A,V1,0.4,5000\n和田宽_R1B,V2,0.3,5200\n"
    await pl.record_ad_metrics_batch(experiment_id=exp_id, csv_text=csv, dry_run=False)

    # 锁 A 臂（n<5 → force 旁路）
    lk = await lab.lock_winner(experiment_id=exp_id, round_no=1,
                               winning_arm_id=a1["arm"]["arm_id"], force=True)
    assert lk["ok"], lk
    assert lk["baseline"].get("opening_hook_3s") == "悬念式钩子"

    # 块B：出下一版——baseline 带上已锁钩子，建议扫下个变量（不重复扫已锁），预填生成参数
    seed = await lab.next_version_seed(exp_id)
    assert seed["ok"], seed
    assert seed["baseline"].get("opening_hook_3s") == "悬念式钩子"
    assert seed["next_round_no"] == 2
    nv = seed["next_variable"]["variable"]
    assert nv and nv != "opening_hook_3s"
    assert seed["generation"]["tool"] == "generate_director_brief"  # human_brief track
    ctx = seed["generation"]["suggested_args"]["experiment_context"]
    assert ctx["baseline"]["opening_hook_3s"] == "悬念式钩子"
    assert ctx["sweep"]["variable"] == nv and ctx["sweep"]["value"] is None

    # override 指定变量
    seed2 = await lab.next_version_seed(exp_id, override_variable="bgm")
    assert seed2["next_variable"]["variable"] == "bgm"

    # 块C：变更日志——第1轮锁定 + X→Y + markdown
    cl = await lab.get_changelog(exp_id)
    assert cl["ok"], cl
    e1 = next(e for e in cl["entries"] if e["round_no"] == 1)
    assert e1["status"] == "locked" and e1["to_value"] == "悬念式钩子"
    assert e1["forced"] is True
    assert "悬念式钩子" in cl["markdown"]
    assert cl["current_baseline"].get("opening_hook_3s") == "悬念式钩子"


# ══════════════════════════════════════════════════════════════════════════════
# 块A 焊触发器：experiment_adopt_script（采纳即自动 A/B：找/建实验 + 挂臂一步成）
# ══════════════════════════════════════════════════════════════════════════════
async def _mk_script(*, kind: str, intent: str | None, with_audience: bool = True) -> str:
    """造一条 draft 脚本，返回 script_id。with_audience=True 挂个 audience_record_id。"""
    pool = get_pool()
    return await pool.fetchval(
        "INSERT INTO pipeline.scripts (sku_id, script_md, status, kind, intent, audience_record_id) "
        "VALUES ($1,'测试脚本','draft',$2,$3,$4::uuid) RETURNING id::text",
        SKU_ADOPT, kind, intent, (str(uuid.uuid4()) if with_audience else None))


@pytest.mark.asyncio
async def test_adopt_script_autocreates_then_reuses():
    # 第 1 条 creative_pack（kind=video_planting、脚本无 intent → 从 kind 反推 planting，track=ai_video）
    s1 = await _mk_script(kind="video_planting", intent=None)
    r1 = await lab.adopt_script_as_arm(
        script_id=s1, variable_value="悬念式钩子", swept_variable="opening_hook_3s")
    assert r1["ok"], r1
    assert r1["created_experiment"] is True          # 没现成实验 → 自动建
    assert r1["intent"] == "planting" and r1["track"] == "ai_video"
    assert r1["arm"]["arm_code"] == "R1A" and r1["arm"]["round_no"] == 1
    assert r1["script_adopted"] is True
    exp_id = r1["experiment_id"]
    pool = get_pool()
    assert await pool.fetchval(
        "SELECT north_star_metric FROM pipeline.experiments WHERE id=$1::uuid", exp_id) == "completion_rate"
    assert await pool.fetchval(
        "SELECT status FROM pipeline.scripts WHERE id=$1::uuid", s1) == "adopted"

    # 第 2 条同 SKU×planting×ai_video → 复用同实验、追加到 open 的 round1 → 臂 B（不必再给 swept_variable）
    s2 = await _mk_script(kind="video_planting", intent="planting")
    r2 = await lab.adopt_script_as_arm(script_id=s2, variable_value="痛点式钩子")
    assert r2["ok"], r2
    assert r2["created_experiment"] is False
    assert r2["experiment_id"] == exp_id
    assert r2["arm"]["arm_code"] == "R1B"


@pytest.mark.asyncio
async def test_adopt_script_guards():
    # missing_swept_variable：新 intent(soft_ad) 没现成实验、又不给 swept → 提前拦（不建空实验）
    s = await _mk_script(kind="video_soft_ad", intent="soft_ad")
    g1 = await lab.adopt_script_as_arm(script_id=s, variable_value="x")
    assert not g1["ok"] and g1["error"] == "missing_swept_variable"
    pool = get_pool()
    assert await pool.fetchval(
        "SELECT count(*) FROM pipeline.experiments WHERE sku_id=$1 AND intent='soft_ad'", SKU_ADOPT) == 0

    # script_missing_audience：新 intent(harvest) 要自动建实验、但脚本没挂人群 → 拦
    s2 = await _mk_script(kind="video_harvest", intent=None, with_audience=False)
    g2 = await lab.adopt_script_as_arm(
        script_id=s2, variable_value="限时", swept_variable="opening_hook_3s")
    assert not g2["ok"] and g2["error"] == "script_missing_audience"

    # missing_intent：kind 不在反推表(graphic_harvest) 且脚本无 intent、又不显式给 → 拦
    s3 = await _mk_script(kind="graphic_harvest", intent=None)
    g3 = await lab.adopt_script_as_arm(
        script_id=s3, variable_value="y", swept_variable="opening_hook_3s")
    assert not g3["ok"] and g3["error"] == "missing_intent"
