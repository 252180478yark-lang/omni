"""Inspect XHR/fetch responses on a compass page — find the JSON endpoints
that return real KPI data. Once identified, we can hit them directly.
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


async def main():
    from playwright.async_api import async_playwright
    out = Path("./snapshots/_inspect")
    out.mkdir(parents=True, exist_ok=True)
    sess = Path("./sessions/douyin_compass/user_data")

    URL = "https://compass.jinritemai.com/shop/business-part"
    captured = []

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(sess), headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
                if "json" not in ct:
                    return
                if resp.status >= 400:
                    return
                url = resp.url
                # Filter out static / config / login responses; keep API calls
                if any(k in url for k in ["/api/", "/data/", "/dashboard/", "/metric/", "graphql"]):
                    body = await resp.text()
                    captured.append({
                        "url": url,
                        "status": resp.status,
                        "size": len(body),
                        "body_sample": body[:600],
                    })
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(15)  # let SPA finish all XHR loads
        # Scroll to trigger lazy-loaded data if any
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(5)

        # De-dup by URL
        seen = set()
        unique = []
        for r in captured:
            key = r["url"].split("?")[0]  # strip query
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)

        print(f"=== Captured {len(captured)} JSON responses, {len(unique)} unique endpoints ===\n")
        # Sort by body size descending — bigger usually = real data
        unique.sort(key=lambda x: x["size"], reverse=True)
        for i, r in enumerate(unique[:15]):
            print(f"[{i}] {r['size']}B  {r['url'][:100]}")
            sample = r['body_sample'][:200].replace('\n', ' ')
            print(f"     sample: {sample}")
            print()

        (out / "compass_xhr.json").write_text(
            json.dumps(unique[:30], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
