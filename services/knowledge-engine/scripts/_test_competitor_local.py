"""测手动截图路线（B）：下一张真实商品图到本地 → competitor_decompose(local_images=) 拆解。"""
import asyncio
import os

import httpx

from app.database import init_pool
from app.mcp.tools.competitor import competitor_decompose


async def main():
    await init_pool()
    url = ("https://g-search3.alicdn.com/img/bao/uploaded/i1/725677994/"
           "O1CN018GgcEp28vJEyHKfQS_!!4611686018427385770-2-item_pic.png")
    p = "/app/data/_tb_test.jpg"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers={"Referer": "https://www.taobao.com/"})
        with open(p, "wb") as f:
            f.write(r.content)
    print("saved", os.path.getsize(p), "bytes ->", p, flush=True)

    d = await competitor_decompose(local_images=[p], focus_product="酱油")
    print("ok=", d.get("ok"))
    print((d.get("result", {}).get("markdown") if d.get("ok") else d.get("hint"))[:1800])


asyncio.run(main())
