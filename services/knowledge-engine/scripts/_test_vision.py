"""验证 gemini-3.5-flash 视觉拆解（绕开被封的抓取，直接喂一张公开 alicdn 商品图）。"""
import asyncio

from app.mcp import prompts
from app.services import competitor_research as cr
from app.services.ai_hub_client import AIHubClient

IMG = "https://g-search3.alicdn.com/img/bao/uploaded/i1/725677994/O1CN018GgcEp28vJEyHKfQS_!!4611686018427385770-2-item_pic.png"


async def main():
    blocks, ok = await cr.fetch_images_as_blocks([IMG], max_count=1)
    print(f"fetched image blocks={len(blocks)} ok_urls={len(ok)}", flush=True)
    if not blocks:
        print("image fetch failed")
        return
    system = prompts.load("competitor_decompose.system")
    user = prompts.render("competitor_decompose.user", focus_product="酱油",
                          main_count=1, detail_count=0, extra_block="")
    content = [{"type": "text", "text": user},
               {"type": "text", "text": "—— 1 张【主图】 ——"}, *blocks]
    r = await AIHubClient().chat(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": content}],
        provider="gemini", model="gemini-3.5-flash",
        temperature=0.3, max_tokens=2000, enforce_human_voice=True,
    )
    print(f"provider={r.get('provider')} model={r.get('model')}\n", flush=True)
    print((r.get("content") or "")[:2600])


asyncio.run(main())
