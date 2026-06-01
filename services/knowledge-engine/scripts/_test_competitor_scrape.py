"""快速测淘宝抓取（competitor 调试用，可反复跑）。
docker exec omni-knowledge-engine python /app/scripts/_test_competitor_scrape.py [query] [top_n] [max_pages]
"""
import asyncio
import json
import sys

import httpx


async def main():
    q = sys.argv[1] if len(sys.argv) > 1 else "有机酱油"
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    async with httpx.AsyncClient(timeout=220) as cli:
        r = await cli.post(
            "http://scout-agent:8009/api/v1/scout/taobao/search",
            json={"query": q, "top_n": top_n, "max_pages": max_pages, "scroll_steps": 6},
        )
        d = r.json()
    print("ok=", d.get("ok"), "count=", d.get("count"), "error=", d.get("error"))
    if d.get("hint"):
        print("hint=", d["hint"])
    print("debug=", json.dumps(d.get("debug", {}), ensure_ascii=False)[:600])
    for it in (d.get("items") or [])[:8]:
        print(f"  #{it.get('rank')} | {(it.get('title') or '')[:42]} | ¥{it.get('price')} "
              f"| {it.get('sales_text')} | {(it.get('shop') or '')[:14]} | {(it.get('main_image_url') or '')[:55]}")


asyncio.run(main())
