from __future__ import annotations

from typing import Any


def enrich_material_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """根据原始指标计算衍生字段。CSV 已有的值优先，没有才自动计算。"""
    plays = row.get("plays") or 0
    clicks = row.get("clicks") or 0
    impressions = row.get("impressions") or 0
    cost = row.get("cost")
    shares = row.get("shares_7d") or 0
    comments = row.get("comments") or 0
    play_3s = row.get("play_3s") or 0

    out = dict(row)

    if out.get("play_3s_rate") is None and plays > 0:
        out["play_3s_rate"] = round(play_3s / plays, 6)

    if out.get("interaction_rate") is None and plays > 0:
        out["interaction_rate"] = round((shares + comments) / plays, 6)

    if out.get("cpm") is None and impressions > 0 and cost is not None:
        out["cpm"] = round(float(cost) / impressions * 1000, 6)

    if out.get("cpc") is None and clicks > 0 and cost is not None:
        out["cpc"] = round(float(cost) / clicks, 6)

    return out
