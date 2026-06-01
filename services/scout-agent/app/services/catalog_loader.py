"""端点目录载入 + 检索 + 参数模板解析（纯逻辑，无浏览器/IO 副作用除读 json）。"""
from __future__ import annotations

import json
from datetime import date as date_cls
from pathlib import Path
from typing import Any


def build_render_context(platform_context: dict[str, Any], today: date_cls) -> dict[str, str]:
    """合并业务上下文 ID + 日期派生量，供 render_params 用。"""
    ctx = {k: str(v) for k, v in (platform_context or {}).items()}
    ctx["today_yyyymmdd"] = today.strftime("%Y%m%d")
    ctx["today_iso"] = today.isoformat()
    ctx["this_month"] = today.strftime("%Y-%m")
    ctx["this_month_compact"] = today.strftime("%Y%m")
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
