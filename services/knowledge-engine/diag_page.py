"""Diagnostic: test crawl quality for a specific Yuntu page."""
import asyncio
import json
import re
import sys

sys.path.insert(0, ".")

async def diag():
    from playwright.async_api import async_playwright

    url = (
        "https://yuntu.oceanengine.com/support/content/143250"
        "?graphId=610&mappingType=2&pageId=445&spaceId=221"
    )
    auth = "./data/harvester_auth.json"

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state=auth)
    page = await ctx.new_page()

    print("[1] Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"[2] Page loaded: {page.url[:100]}")

    if "login" in page.url.lower() or "passport" in page.url.lower():
        print("!!! Redirected to login - auth expired")
        await browser.close()
        await pw.stop()
        return

    await page.wait_for_timeout(5000)

    print(f"[3] Found {len(page.frames)} frames:")
    for i, frame in enumerate(page.frames):
        print(f"  Frame {i}: {frame.url[:150]}")

    target_frame = None
    for frame in page.frames:
        if any(k in frame.url for k in ["larkoffice", "feishu", "larksuite"]):
            target_frame = frame
            break

    if target_frame:
        print(f"[4] Found Feishu iframe: {target_frame.url[:150]}")

        js = """() => {
            try {
                if (window.DATA && window.DATA.clientVars) {
                    return JSON.stringify(window.DATA.clientVars);
                }
            } catch(e) {}
            return null;
        }"""

        for attempt in range(8):
            raw = await target_frame.evaluate(js)
            if raw:
                cv = json.loads(raw)
                bmap = (cv.get("data") or {}).get("block_map") or {}
                print(f"[5] clientVars blocks: {len(bmap)} (attempt {attempt+1})")

                types = {}
                for bid, block in bmap.items():
                    bt = block.get("data", {}).get("type", "unknown")
                    types[bt] = types.get(bt, 0) + 1
                print(f"[6] Block types: {json.dumps(types, ensure_ascii=False)}")

                # Force reload to pick up code changes
                import importlib
                import app.services.harvester as _h
                importlib.reload(_h)
                from app.services.harvester import parse_feishu_document
                doc = parse_feishu_document(raw)
                if doc:
                    md = doc["markdown"]
                    title = doc["title"]
                    text_len = len(doc["text"])
                    print(f"[7] Parsed: title={title}, md_len={len(md)}, text_len={text_len}")

                    table_lines = [l for l in md.split("\n") if l.strip().startswith("|")]
                    print(f"[8] Table lines found: {len(table_lines)}")
                    if table_lines:
                        for tl in table_lines[:5]:
                            print(f"  {tl[:150]}")

                    img_re = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
                    imgs = img_re.findall(md)
                    print(f"[9] Images found: {len(imgs)}")
                    for alt, u in imgs[:5]:
                        print(f"  [{alt}] -> {u[:100]}")

                    # Save full markdown to file for proper UTF-8 inspection
                    out_path = "diag_output.md"
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(f"# Diagnostic Output\n\n")
                        f.write(f"- Title: {title}\n")
                        f.write(f"- Markdown length: {len(md)}\n")
                        f.write(f"- Text length: {text_len}\n")
                        f.write(f"- Table lines: {len(table_lines)}\n")
                        f.write(f"- Images: {len(imgs)}\n\n")
                        f.write(f"---\n\n## Full Markdown\n\n")
                        f.write(md)
                    print(f"[10] Full markdown saved to {out_path}")
                else:
                    print("[7] parse_feishu_document returned None")
                break
            await target_frame.page.wait_for_timeout(2000)
        else:
            print("[5] clientVars not found after 8 attempts")

            # Fallback: try getting rendered text
            html = await page.content()
            print(f"[F1] Page HTML length: {len(html)}")
            content_text = await page.evaluate("""() => {
                const el = document.querySelector('[class*="doc"], [class*="content"], article, main');
                return el ? el.innerText.substring(0, 3000) : 'No content container found';
            }""")
            print(f"[F2] Rendered text preview:\n{content_text[:2000]}")
    else:
        print("[4] No Feishu iframe found - trying rendered content fallback")
        html = await page.content()
        print(f"[5] Page HTML length: {len(html)}")

        content_text = await page.evaluate("""() => {
            const el = document.querySelector('[class*="doc"], [class*="content"], article, main, .ql-editor');
            return el ? el.innerText.substring(0, 3000) : 'No content container found';
        }""")
        print(f"[6] Rendered text:\n{content_text[:2000]}")

        # Also try getting tables from DOM
        tables_html = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            return Array.from(tables).map(t => t.outerHTML.substring(0, 500)).join('\\n---\\n');
        }""")
        if tables_html:
            print(f"[7] Tables HTML:\n{tables_html[:2000]}")

    await browser.close()
    await pw.stop()
    print("\n[DONE]")


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(diag())
