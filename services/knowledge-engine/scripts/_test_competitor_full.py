"""端到端测竞品调研全链路：competitor_search（含相关性过滤 LLM）→ competitor_decompose（详情页抓图 + 视觉拆解 LLM）。
docker exec omni-knowledge-engine python /app/scripts/_test_competitor_full.py [query]
"""
import asyncio
import sys

from app.database import init_pool
from app.mcp.tools.competitor import competitor_decompose, competitor_search


async def main():
    q = sys.argv[1] if len(sys.argv) > 1 else "有机酱油"
    await init_pool()

    print("=== STAGE 1: competitor_search ===", flush=True)
    r = await competitor_search(query=q, top_n=8)
    if not r.get("ok"):
        print("search FAILED:", r.get("error"), r.get("hint"))
        return
    res = r["result"]
    print(res["markdown"][:1600])
    print(f"\n[items={res['count']} skipped={len(res['skipped'])} relevance={res['relevance_filter']}]", flush=True)
    items = res["items"]
    if not items:
        print("no items after filter")
        return

    pick = items[0]
    print(f"\n=== STAGE 2: competitor_decompose -> {pick.get('title','')[:40]} ===", flush=True)
    print(f"item_url={pick.get('item_url')} main_img={(pick.get('main_image_url') or '')[:55]}", flush=True)
    d = await competitor_decompose(
        items=[pick], focus_product=q,
        max_main_images=4, max_detail_images=4,
    )
    if not d.get("ok"):
        print("decompose FAILED:", d.get("error"), d.get("hint"), d.get("errors"))
        return
    print(d["result"]["markdown"][:3500])


asyncio.run(main())
