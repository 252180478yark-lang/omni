"""Test Playwright browser access to yuntu with saved auth cookies."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_FILES = [
    Path(r"E:\app\data\harvester_auth.json"),
    Path(r"E:\agent\omni\services\knowledge-engine\data\harvester_auth.json"),
]
URL = "https://yuntu.oceanengine.com/support/content/2258?graphId=610&pageId=445&spaceId=221"


async def main():
    auth_file = None
    for f in AUTH_FILES:
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                n = len(data.get("cookies", []))
                print(f"[AUTH] {f}: {n} cookies")
                auth_file = f
                break
            except Exception as e:
                print(f"[AUTH] {f}: Error reading - {e}")

    if not auth_file:
        print("[ERROR] No valid auth file found")
        return

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state=str(auth_file))
    page = await ctx.new_page()

    print(f"\n[NAV] Going to {URL}")
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"[NAV] Failed: {e}")
        await browser.close()
        await pw.stop()
        return

    final_url = page.url
    print(f"[NAV] Final URL: {final_url}")
    if "login" in final_url.lower() or "passport" in final_url.lower():
        print("[WARN] Redirected to login — cookies are expired!")
        await browser.close()
        await pw.stop()
        return

    print("[OK] Page loaded, looking for Feishu iframe...")
    target_frame = None
    for attempt in range(15):
        for frame in page.frames:
            if any(k in frame.url for k in ["larkoffice", "feishu", "larksuite"]):
                target_frame = frame
                break
        if target_frame:
            print(f"[OK] Found iframe: {target_frame.url[:100]}")
            break
        await page.wait_for_timeout(2000)
        print(f"  Waiting... ({(attempt+1)*2}s)")

    if not target_frame:
        print("[FAIL] No Feishu iframe found")
        frames = [f.url for f in page.frames]
        print(f"  Available frames: {frames[:5]}")
    else:
        js = """() => {
            try {
                if (window.DATA && window.DATA.clientVars) {
                    return JSON.stringify(window.DATA.clientVars).length;
                }
            } catch(e) {}
            return 0;
        }"""
        for attempt in range(5):
            try:
                size = await target_frame.evaluate(js)
                if size > 100:
                    print(f"[OK] Got clientVars data: {size} chars")
                    break
                print(f"  Data not ready ({attempt+1})")
            except Exception as e:
                print(f"  Eval error ({attempt+1}): {e}")
            await page.wait_for_timeout(2000)

    await browser.close()
    await pw.stop()
    print("\n[DONE]")


if __name__ == "__main__":
    asyncio.run(main())
