"""一次性诊断脚本：实抓 compass.product_list / compass.flow_source_funnel 看真实结构。

用法（容器内）：PYTHONPATH=/app python /app/scripts/_probe_pl_funnel.py
输出顶层结构 + 关键节点摘要，不落库。
"""
import asyncio
import json
import sys
from pathlib import Path

from app.services.catalog_loader import CatalogLoader
from app.services.live_fetch import LiveFetchExecutor

# zoneinfo 自检
try:
    from zoneinfo import ZoneInfo
    from datetime import datetime
    print("zoneinfo OK, Asia/Shanghai now:", datetime.now(ZoneInfo("Asia/Shanghai")).isoformat())
except Exception as exc:
    print("zoneinfo FAIL:", exc)


def _shape(node, depth=0, max_depth=4):
    """递归打结构骨架（list 只看第一个元素）。"""
    pad = "  " * depth
    if depth > max_depth:
        return pad + "...\n"
    if isinstance(node, dict):
        out = ""
        for k, v in list(node.items())[:30]:
            if isinstance(v, (dict, list)):
                out += f"{pad}{k}: ({type(v).__name__} len={len(v)})\n"
                out += _shape(v, depth + 1, max_depth)
            else:
                sv = str(v)
                out += f"{pad}{k} = {sv[:80]}\n"
        return out
    if isinstance(node, list):
        if not node:
            return pad + "[]\n"
        return _shape(node[0], depth + 1, max_depth)
    return pad + str(node)[:80] + "\n"


async def main():
    cat_dir = Path("/app/catalog")
    files = {p: cat_dir / f"{p}.json" for p in ("yuntu", "compass", "doudian")
             if (cat_dir / f"{p}.json").exists()}
    ctx_file = cat_dir / "context.json"
    context = json.loads(ctx_file.read_text("utf-8")) if ctx_file.exists() else {}
    cat = CatalogLoader.from_files(files, context)
    ex = LiveFetchExecutor(cat, Path("/app/sessions"))

    for ep in ("compass.product_list", "compass.flow_source_funnel"):
        print("=" * 70)
        print("##", ep)
        r = await ex.fetch_raw("compass", ep)
        print("ok:", r.get("ok"), "status:", r.get("status"), "error:", r.get("error"))
        print("url:", r.get("url"))
        parsed = r.get("parsed")
        if parsed is None:
            print("hint:", r.get("hint"))
            continue
        dump = Path(f"/app/downloads/_probe_{ep.replace('.', '_')}.json")
        dump.write_text(json.dumps(parsed, ensure_ascii=False, indent=1)[:2_000_000],
                        encoding="utf-8")
        print("dumped ->", dump)
        print("-- shape --")
        print(_shape(parsed, max_depth=5)[:6000])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
