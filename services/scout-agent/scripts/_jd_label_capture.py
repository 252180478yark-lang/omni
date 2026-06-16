"""切片2 口径确认：抓商智概况页渲染的中文指标名+数值，按数值反查指标码（定 PV/UV 等口径，不靠猜）。

headed+session 加载 jdsz → 提取页面里"中文标签+数字"的指标卡文本 → agent 用数值交叉匹配
响应里的指标码（如 DOM "商品访问人数 85" + 响应 page_cnt=85 → page_cnt=访问人数(UV)）。
    docker exec -w /app -e DISPLAY=:99 omni-scout-agent python scripts/_jd_label_capture.py
"""
import asyncio
from playwright.async_api import async_playwright

SESS = "/app/sessions/jd/storage_state.json"
KW = ("访客", "访问", "浏览", "曝光", "成交", "转化", "加购", "停留", "客单", "人数", "UV", "PV", "价值")


async def main() -> None:
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await b.new_context(storage_state=SESS, locale="zh-CN", viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        try:
            await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print("GOTO_ERR", str(exc)[:140]); await b.close(); return
        await pg.wait_for_timeout(9000)
        # 抓所有"短文本里同时含指标关键词的"叶子元素 innerText（指标卡通常 label+value 在一块）
        texts = await pg.evaluate(
            """(kw) => {
                const out = [];
                const els = document.querySelectorAll('div,span,td,li,p,label');
                for (const e of els) {
                    if (e.children.length > 3) continue;            // 只要叶子/小容器
                    const t = (e.innerText || '').trim();
                    if (!t || t.length > 30) continue;
                    if (kw.some(k => t.includes(k))) out.push(t);
                }
                return [...new Set(out)];
            }""",
            list(KW),
        )
        print(f"CAPTURED {len(texts)} 指标卡文本：")
        for t in texts[:80]:
            print("  " + t.replace("\n", " | "))
        await b.close()


asyncio.run(main())
