"""内容↔人群向量匹配（投前预测分）+ 北极星闭环（migration 066）。

老板要"向量相似度 + 北极星匹配度 同时升级"：
- 投前：内容三路(文字/画面/音乐)文本 + 人群算法信号文本 → embed（复用 embed_texts，gemini 1536 维）
  → 余弦相似度（pgvector <=>）→ 预测匹配分（三路分开看 + 简单平均）写进 experiment_arms。
- 投后：北极星(完播率/cvr) 经 record_ad_metrics 落库，跟预测分同锚在臂上。
- 闭环：(预测分, 北极星) 天然配对 → calibrate 看相关性 + 四象限偏差 → 建议三路权重（确定性记账，
  不训练、不自动改）。

**铁律**：预测分只是投前冷启动代理（用词/语义近 ≠ 会买），winner 永远只认北极星，预测分只当旁证。
"""
from __future__ import annotations

import json
import logging
import re
import statistics
from typing import Any

import numpy as np

from app.config import settings
from app.database import get_pool
from app.services.embedding_client import embed_texts

logger = logging.getLogger(__name__)

# 三路默认等权（MVP 排序用简单平均，权重仅供 calibrate 建议 + 加权总分展示，老板拍板才改）
_DEFAULT_WEIGHTS = {"text": 1.0, "visual": 1.0, "music": 1.0}
_TRACKS = ("text", "visual", "music")
_DISCLAIMER = ("投前向量预测分只是冷启动代理（两段文本余弦近=用词/语义像，可能像得毫无意义、≠会买），"
               "只用于排序候选、少烧广告费；winner 永远只认投后北极星，过关≠带货。")


def _as_dict(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v) or {}
        except Exception:
            return {}
    return {}


def _emb_model() -> str:
    return getattr(settings, "embedding_model", "gemini-embedding-2-preview")


def _emb_provider() -> str | None:
    return getattr(settings, "embedding_provider", "gemini")


# ── 文本抽取（纯函数，确定性，可单测不调 API）────────────────────────────────────
def extract_content_tracks(script_md: str, kind: str, scenes: list[dict] | None) -> dict[str, str]:
    """从脚本抽出 文字/画面/音乐 三路文本（自适应降级，缺哪路就不出哪路）。

    优先级：① director_brief 的「算法信号三向量」段（最干净，标题对齐）
           ② creative_pack 节点 scenes 的 visual+shot/dialog/sound 字段
           ③ whole_prompt 新形态/兜底 → 整段当 text 单路（粗匹配，诚实降级）。
    """
    md = script_md or ""
    scenes = scenes or []
    tracks: dict[str, str] = {}

    # ① 算法信号三向量（画面向量/文案向量/音乐向量，标题逐字固定）
    for title, key in (("画面向量", "visual"), ("文案向量", "text"), ("音乐向量", "music")):
        m = re.search(
            rf"{title}\s*[：:]\s*(.+?)(?=\n\s*(?:画面向量|文案向量|音乐向量)\s*[：:]|\n#{{1,4}}\s|\Z)",
            md, re.S)
        if m and m.group(1).strip():
            tracks[key] = m.group(1).strip()[:2000]
    if tracks:
        return tracks

    # ② 节点 scenes 字段（非 whole_prompt）
    if scenes and not all(s.get("whole_prompt") for s in scenes):
        vis = " ".join((s.get("visual") or "") + " " + (s.get("shot") or "") for s in scenes).strip()
        txt = " ".join((s.get("dialog") or "") for s in scenes).strip()
        mus = " ".join((s.get("sound") or "") for s in scenes).strip()
        if vis:
            tracks["visual"] = vis[:2000]
        if txt:
            tracks["text"] = txt[:2000]
        if mus:
            tracks["music"] = mus[:2000]
        if tracks:
            return tracks

    # ③ whole_prompt / 兜底：整段叙事当 text 单路（粗匹配）
    whole = " ".join((s.get("video_prompt") or "") for s in scenes).strip() or md.strip()
    if whole:
        tracks["text"] = whole[:2000]
    return tracks


def extract_audience_text(portrait_md: str) -> str:
    """从画像抽「1.3 算法信号原料」段当人群向量料；找不到退而取"算法信号"附近 / 整段。"""
    md = portrait_md or ""
    m = re.search(r"(1\.3[^\n]*算法信号[\s\S]+?)(?=\n#{1,4}\s|\n\s*1\.4|\Z)", md)
    if m and m.group(1).strip():
        return m.group(1).strip()[:3000]
    i = md.find("算法信号")
    if i >= 0:
        return md[i:i + 3000].strip()
    return md[:3000].strip()


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


# ── embed 落库 ─────────────────────────────────────────────────────────────────
async def embed_and_store_audience(portrait_id: str) -> dict:
    from app.services.pipeline_lineage import get_audience_portrait
    p = await get_audience_portrait(portrait_id)
    if not p:
        return {"ok": False, "error": "portrait_not_found"}
    text = extract_audience_text(p.get("portrait_md") or "")
    if not text.strip():
        return {"ok": False, "error": "empty_audience_text"}
    vecs = await embed_texts([text], model=_emb_model(), provider=_emb_provider())
    vec = np.array(vecs[0], dtype=np.float32)
    pool = get_pool()
    await pool.execute(
        """INSERT INTO pipeline.audience_vectors (portrait_id, sku_id, source_text, embedding, model)
           VALUES ($1::uuid,$2,$3,$4,$5)
           ON CONFLICT (portrait_id) DO UPDATE SET
             source_text=EXCLUDED.source_text, embedding=EXCLUDED.embedding,
             model=EXCLUDED.model, updated_at=NOW()""",
        portrait_id, p.get("sku_id"), text, vec, _emb_model())
    return {"ok": True, "portrait_id": portrait_id, "chars": len(text)}


async def embed_and_store_content(script_id: str) -> dict:
    from app.services.pipeline_lineage import get_creative_pack
    s = await get_creative_pack(script_id)
    if not s:
        return {"ok": False, "error": "script_not_found"}
    tracks = extract_content_tracks(s.get("script_md") or "", s.get("kind") or "", s.get("scenes") or [])
    if not tracks:
        return {"ok": False, "error": "no_content_text"}
    keys = list(tracks.keys())
    texts = [tracks[k] for k in keys]
    vecs = await embed_texts(texts, model=_emb_model(), provider=_emb_provider())
    pool = get_pool()
    for k, txt, v in zip(keys, texts, vecs):
        await pool.execute(
            """INSERT INTO pipeline.content_vectors
                 (script_id, sku_id, track, source_field, source_text, embedding, model)
               VALUES ($1::uuid,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (script_id, track) DO UPDATE SET
                 source_field=EXCLUDED.source_field, source_text=EXCLUDED.source_text,
                 embedding=EXCLUDED.embedding, model=EXCLUDED.model, updated_at=NOW()""",
            script_id, s.get("sku_id"), k, k, txt, np.array(v, dtype=np.float32), _emb_model())
    return {"ok": True, "script_id": script_id, "tracks": keys,
            "note": ("仅抽出 text 单路（whole_prompt 整段叙事无法分三路）——三路分开看需脚本带结构化三向量段"
                     if keys == ["text"] else None)}


# ── 投前预测匹配分（余弦交叉，三路分开看 + 简单平均）────────────────────────────
async def predict_match(experiment_id: str, round_no: int | None = None) -> dict:
    pool = get_pool()
    exp = await pool.fetchrow(
        "SELECT id::text AS id, sku_id, portrait_id::text AS portrait_id "
        "FROM pipeline.experiments WHERE id=$1::uuid", experiment_id)
    if not exp:
        return {"ok": False, "error": "experiment_not_found"}
    if not exp["portrait_id"]:
        return {"ok": False, "error": "no_portrait",
                "hint": "实验没绑画像(portrait_id)——向量匹配要画像当人群锚；建实验时传 portrait_id。"}
    if not await pool.fetchval(
            "SELECT 1 FROM pipeline.audience_vectors WHERE portrait_id=$1::uuid", exp["portrait_id"]):
        return {"ok": False, "error": "audience_not_embedded",
                "hint": f"先 embed_content_and_audience(portrait_id='{exp['portrait_id']}')"}

    if round_no is None:
        r = await pool.fetchrow(
            "SELECT round_no FROM pipeline.experiment_rounds WHERE experiment_id=$1::uuid "
            "ORDER BY (status='open') DESC, round_no DESC LIMIT 1", experiment_id)
        round_no = int(r["round_no"]) if r else None
    if round_no is None:
        return {"ok": False, "error": "no_rounds", "hint": "实验还没轮次——先 experiment_attach_arm 挂臂"}

    arms = await pool.fetch(
        "SELECT id::text AS arm_id, arm_label, variable_value, script_id::text AS script_id "
        "FROM pipeline.experiment_arms WHERE experiment_id=$1::uuid AND round_no=$2 ORDER BY arm_label",
        experiment_id, round_no)
    if not arms:
        return {"ok": False, "error": "no_arms"}

    out = []
    for a in arms:
        if not a["script_id"]:
            out.append({"arm_label": a["arm_label"], "skipped": "no_script"})
            continue
        rows = await pool.fetch(
            "SELECT cv.track, (1-(cv.embedding <=> av.embedding))::float AS score "
            "FROM pipeline.content_vectors cv "
            "JOIN pipeline.audience_vectors av ON av.portrait_id=$2::uuid "
            "WHERE cv.script_id=$1::uuid", a["script_id"], exp["portrait_id"])
        if not rows:
            out.append({"arm_label": a["arm_label"], "skipped": "content_not_embedded",
                        "hint": f"先 embed_content_and_audience(script_id='{a['script_id']}')"})
            continue
        tracks = {r["track"]: round(float(r["score"]), 4) for r in rows}
        avg = round(sum(tracks.values()) / len(tracks), 4)  # 简单平均（仅用有的路）
        meta = {"tracks": tracks, "portrait_id": exp["portrait_id"],
                "weights": _DEFAULT_WEIGHTS, "n_tracks": len(tracks)}
        await pool.execute(
            "UPDATE pipeline.experiment_arms SET predicted_match_score=$2, "
            "predicted_match_meta=$3::jsonb WHERE id=$1::uuid",
            a["arm_id"], avg, json.dumps(meta, ensure_ascii=False))
        out.append({"arm_label": a["arm_label"], "variable_value": a["variable_value"],
                    "predicted_match_score": avg, "tracks": tracks})

    ranked = sorted([o for o in out if "predicted_match_score" in o],
                    key=lambda x: x["predicted_match_score"], reverse=True)
    return {
        "ok": True, "experiment_id": experiment_id, "round_no": round_no,
        "arms": out, "ranking": [o["arm_label"] for o in ranked],
        "disclaimer": _DISCLAIMER,
        "next_step_hint": ("挑预测分高的臂去投放 → 投后 record_ad_metrics → experiment_status 看"
                           "预测分 vs 北极星并排 → 攒够再 calibrate_match_predictor 看向量准不准。"),
    }


# ── 闭环校准（投后北极星 vs 投前预测分，确定性记账，不训练）──────────────────────
async def calibrate(sku_id: str | None = None, experiment_id: str | None = None,
                    min_pairs: int = 8) -> dict:
    pool = get_pool()
    where = ["r.predicted_match_score IS NOT NULL", "r.north_star_avg IS NOT NULL",
             "r.sample_status <> 'preliminary'"]
    params: list[Any] = []
    if experiment_id:
        params.append(experiment_id)
        where.append(f"r.experiment_id=${len(params)}::uuid")
    if sku_id:
        params.append(sku_id)
        where.append(f"r.sku_id=${len(params)}")
    rows = await pool.fetch(
        f"""SELECT r.arm_id::text AS arm_id, r.intent,
                   r.predicted_match_score::float AS pred, r.north_star_avg::float AS ns,
                   am.predicted_match_meta
            FROM pipeline.v_experiment_round_results r
            JOIN pipeline.experiment_arms am ON am.id = r.arm_id
            WHERE {' AND '.join(where)}""", *params)
    n = len(rows)
    if n < min_pairs:
        return {"ok": True, "status": "insufficient_samples", "n_pairs": n, "min_pairs": min_pairs,
                "hint": (f"只有 {n} 对(预测分,北极星)配对（需 ≥{min_pairs} 个 n≥5 的臂）——校准是空中楼阁，"
                         "先让投前排序+投后验证多跑几轮攒数据再来。"),
                "disclaimer": _DISCLAIMER}

    preds = [r["pred"] for r in rows]
    nss = [r["ns"] for r in rows]
    overall_r = _pearson(preds, nss)
    pmed, nmed = statistics.median(preds), statistics.median(nss)
    quad = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}  # tp=高高对、fp=向量高北极星低(假阳)、fn=向量低北极星高(假阴)
    for p, s in zip(preds, nss):
        hi_p, hi_s = p >= pmed, s >= nmed
        key = "tp" if (hi_p and hi_s) else "fp" if (hi_p and not hi_s) else "fn" if (not hi_p and hi_s) else "tn"
        quad[key] += 1

    track_r: dict[str, float] = {}
    for t in _TRACKS:
        xs, ys = [], []
        for r in rows:
            tv = (_as_dict(r["predicted_match_meta"]).get("tracks") or {}).get(t)
            if tv is not None:
                xs.append(float(tv))
                ys.append(r["ns"])
        if len(xs) >= min_pairs:
            track_r[t] = round(_pearson(xs, ys), 3)
    pos = {t: max(0.0, c) for t, c in track_r.items()}
    tot = sum(pos.values()) or 1.0
    suggested_w = ({t: round(v / tot, 2) for t, v in pos.items()} if track_r else None)

    return {
        "ok": True, "status": "calibrated", "n_pairs": n,
        "overall_correlation": round(overall_r, 3),
        "quadrants": quad,
        "track_correlation": track_r,
        "suggested_weights": suggested_w,
        "reading": _calib_reading(overall_r, quad, track_r, suggested_w),
        "disclaimer": ("相关性是观察不是因果；n≥5 是工程门槛非统计显著；抖音冷启动波动可能让北极星本身就是噪声。"
                       "建议权重只供老板参考拍板，系统不自动改、不做回归训练。" + _DISCLAIMER),
    }


def _calib_reading(overall_r: float, quad: dict, track_r: dict, suggested_w: dict | None) -> list[str]:
    lines: list[str] = []
    if overall_r >= 0.4:
        lines.append(f"向量预测分跟北极星正相关 {overall_r:+.2f}——向量在当前样本里**有点准**，可信度中上。")
    elif overall_r <= -0.2:
        lines.append(f"向量预测分跟北极星**负相关 {overall_r:+.2f}**——向量在当前样本里**反着的/不准**，别信投前排序，纯看北极星。")
    else:
        lines.append(f"向量预测分跟北极星相关性弱 {overall_r:+.2f}——向量目前**说明不了啥**，当噪声看，靠投放数据。")
    fp, fn = quad.get("fp", 0), quad.get("fn", 0)
    if fp:
        lines.append(f"{fp} 个臂「向量看着对路、投出去北极星低」=假阳性（被向量骗了，这类内容/人群组合要警惕）。")
    if fn:
        lines.append(f"{fn} 个臂「向量看着不对路、投出去北极星却高」=假阴性（差点被向量漏掉的好内容）。")
    if track_r:
        best = max(track_r, key=lambda k: track_r[k])
        worst = min(track_r, key=lambda k: track_r[k])
        zh = {"text": "文字", "visual": "画面", "music": "音乐"}
        lines.append(f"三路里 **{zh[best]}向量** 跟北极星最相关({track_r[best]:+.2f})、**{zh[worst]}向量** 最弱({track_r[worst]:+.2f})。")
        if suggested_w:
            lines.append(f"按相关性建议权重：{ {('文字' if t=='text' else '画面' if t=='visual' else '音乐'): w for t, w in suggested_w.items()} }（仅建议，老板拍板才改）。")
    return lines
