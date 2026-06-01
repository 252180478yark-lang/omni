"""端点目录载入 + 检索 + 参数模板解析（纯逻辑，无浏览器/IO 副作用除读 json）。"""
from __future__ import annotations

import json
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from typing import Any


def build_render_context(platform_context: dict[str, Any], today: date_cls) -> dict[str, str]:
    """合并业务上下文 ID + 日期派生量，供 render_params 用。

    日期占位符按"角色 + 格式"提供，覆盖三平台实测用到的全部日期形态：
    - 单点参考日（云图等 T+1 数据，留 2 天缓冲）：ref_*
    - 昨日：yest_*
    - 近 7 天滚动窗口（罗盘 date_type=21）：win_begin_* / win_end_*（end=昨日，begin=今天-8）
    - 月份：this_month / last_month / this_month_compact
    斜杠带时分秒格式（罗盘 begin_date/end_date）：*_slashdt
    """
    ctx = {k: str(v) for k, v in (platform_context or {}).items()}
    ref = today - timedelta(days=2)
    yest = today - timedelta(days=1)
    win_begin = today - timedelta(days=8)
    win_end = yest
    first_of_month = today.replace(day=1)
    last_month = (first_of_month - timedelta(days=1)).strftime("%Y-%m")

    ctx.update({
        "today_yyyymmdd": today.strftime("%Y%m%d"),
        "today_iso": today.isoformat(),
        "this_month": today.strftime("%Y-%m"),
        "this_month_compact": today.strftime("%Y%m"),
        "last_month": last_month,
        "ref_yyyymmdd": ref.strftime("%Y%m%d"),
        "ref_iso": ref.isoformat(),
        "yest_yyyymmdd": yest.strftime("%Y%m%d"),
        "yest_iso": yest.isoformat(),
        "win_begin_yyyymmdd": win_begin.strftime("%Y%m%d"),
        "win_end_yyyymmdd": win_end.strftime("%Y%m%d"),
        "win_begin_iso": win_begin.isoformat(),
        "win_end_iso": win_end.isoformat(),
        "win_begin_slashdt": win_begin.strftime("%Y/%m/%d 00:00:00"),
        "win_end_slashdt": win_end.strftime("%Y/%m/%d 00:00:00"),
    })
    return ctx


def render_params(
    params: dict[str, Any] | None,
    ctx: dict[str, str],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """把 params 里的 {placeholder} 用 ctx 填充；overrides 覆盖最终值。

    未知占位符原样保留（不抛错，便于 sweep 暴露问题而非静默崩）。
    """
    out: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
            key = v[1:-1]
            out[k] = ctx.get(key, v)
        else:
            out[k] = v
    for k, v in (overrides or {}).items():
        out[k] = v
    return out


class CatalogLoader:
    """载入若干平台目录文件，提供 get/search。"""

    def __init__(self, entries: list[dict], context: dict[str, dict]):
        self._entries = entries
        self._by_key = {e["key"]: e for e in entries}
        self.context = context or {}

    @classmethod
    def from_files(cls, files: dict[str, Path], context: dict[str, dict]) -> "CatalogLoader":
        entries: list[dict] = []
        for _platform, path in files.items():
            entries.extend(json.loads(Path(path).read_text(encoding="utf-8")))
        return cls(entries, context)

    def get(self, key: str) -> dict | None:
        return self._by_key.get(key)

    def search(
        self,
        platform: str | None = None,
        query: str | None = None,
        verified_only: bool = False,
    ) -> list[dict]:
        res = self._entries
        if platform:
            res = [e for e in res if e.get("platform") == platform]
        if verified_only:
            res = [e for e in res if e.get("verified")]
        if query:
            q = query.lower()

            def hit(e: dict) -> bool:
                hay = " ".join([
                    e.get("key", ""),
                    e.get("category", ""),
                    e.get("path", ""),
                    " ".join(e.get("aliases", [])),
                ]).lower()
                return q in hay

            res = [e for e in res if hit(e)]
        return list(res)
