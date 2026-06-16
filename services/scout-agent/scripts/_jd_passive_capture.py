"""切片2 passive 抓取（端到端第一步）：headed+session 加载商智，SPA 自己签名发请求，
我 page.on(response) 抓 szgateway 响应存盘（gitignore），并打印每个接口的 code/data 结构，
供写抽取器。零签名 forge、零对抗。
    docker exec -w /app -e DISPLAY=:99 omni-scout-agent python scripts/_jd_passive_capture.py
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

SESS = "/app/sessions/jd/storage_state.json"
OUT = "/app/catalog/_jd_responses.jsonl"   # catalog/_jd_* 已 gitignore（含真实业务数据）
captured: list[dict] = []


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(storage_state=SESS, locale="zh-CN",
                                        viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()

        async def on_resp(resp):
            u = resp.url
            if "szgateway.jd.com/api/lowcode" in u:
                try:
                    body = await resp.text()
                    captured.append({"url": u, "req": resp.request.post_data, "body": body[:40000]})
                except Exception:
                    pass

        pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
        try:
            await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print("GOTO_ERR", str(exc)[:140], flush=True)
        await pg.wait_for_timeout(8000)
        for kw in ("经营概况", "实时", "交易", "成交", "流量", "流量概况", "商品", "数据"):
            try:
                loc = pg.get_by_text(kw, exact=False).first
                if await loc.count():
                    await loc.click(timeout=3000)
                    await pg.wait_for_timeout(5000)
            except Exception:
                continue
        await pg.wait_for_timeout(3000)
        Path(OUT).write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in captured), "utf-8")
        print(f"CAPTURED {len(captured)} szgateway responses -> {OUT}\n", flush=True)
        # 摘要：每接口 code + body.data 类型/规模（不打印真实数值）
        ok = 0
        for c in captured:
            try:
                j = json.loads(c["body"])
                code = j.get("header", {}).get("code")
                data = j.get("body", {}).get("data")
                if isinstance(data, list):
                    dt = f"list[{len(data)}]"
                elif isinstance(data, dict):
                    dt = "dict{" + ",".join(list(data.keys())[:6]) + "}"
                else:
                    dt = type(data).__name__
                if code == 0 and data:
                    ok += 1
                tail = c["url"].split("/lowcode/")[-1][:55]
                print(f"  code={code} data={dt:<28} {tail}", flush=True)
            except Exception:
                pass
        print(f"\n{ok} 个接口 code=0 且 data 非空（有真数据）", flush=True)
        await browser.close()


asyncio.run(main())
