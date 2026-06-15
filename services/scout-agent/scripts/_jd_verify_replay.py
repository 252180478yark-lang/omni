"""切片2 首验：scout 容器（xvfb headed）能否用 session 过 jdsz 反爬 + 回放 szgateway 业务接口。

这是轨 A（XHR 回放）在生产环境（scout 容器）成立与否的一票。过 = 切片2 全自动落库可行；
不过 = 退 host headed 定时跑 / 导出轨。读 sessions/jd（host 抓的，cookie 跨 chromium 可移植）。
    docker exec -w /app -e DISPLAY=:99 omni-scout-agent python scripts/_jd_verify_replay.py
"""
import asyncio
import json
from playwright.async_api import async_playwright

SESS = "/app/sessions/jd/storage_state.json"
URL = "https://szgateway.jd.com/api/lowcode/indexSummary/summary.ajax"
# 日级核心成交额（比 realtime 简单稳定）。日期硬编码昨日做验证。
PAYLOAD = {
    "realtime": False, "interval": "DAY", "dateType": "day",
    "startDate": "2026-06-14", "endDate": "2026-06-14",
    "compareStartDate": "2026-06-13", "compareEndDate": "2026-06-13",
    "compareType": "hb", "page": 1, "pageSize": 1,
    "indicators": ["jdr_sch_trade_deal_ord_ord_amt_sz_trade_deal_snapshot"],
}


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(storage_state=SESS, locale="zh-CN",
                                        viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        try:
            await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
            print("JDSZ_LOADED", pg.url, flush=True)
        except Exception as exc:
            print("JDSZ_ERR", str(exc)[:160], flush=True)
        await pg.wait_for_timeout(3500)
        res = await pg.evaluate(
            """async ({url, payload}) => {
                try {
                    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                                                body: JSON.stringify(payload), credentials:'include'});
                    const t = await r.text();
                    let code = null;
                    try { code = JSON.parse(t).header.code; } catch(e) {}
                    return {status: r.status, biz_code: code, len: t.length, head: t.slice(0, 240)};
                } catch(e) { return {fetch_error: String(e)}; }
            }""",
            {"url": URL, "payload": PAYLOAD},
        )
        print("FETCH_RESULT", json.dumps(res, ensure_ascii=False)[:600], flush=True)
        await browser.close()


asyncio.run(main())
