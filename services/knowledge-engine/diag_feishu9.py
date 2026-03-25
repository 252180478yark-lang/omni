"""Examine paginated client_vars responses structure."""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

async def diag():
    from playwright.async_api import async_playwright
    from pathlib import Path

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)

    auth_path = r"\app\data\feishu_auth.json"
    ctx_kw = {}
    if Path(auth_path).exists():
        ctx_kw["storage_state"] = auth_path
    ctx = await browser.new_context(**ctx_kw)
    page = await ctx.new_page()

    chunks = []

    async def on_cv_response(response):
        if "/docx/pages/client_vars" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            bmap = (body.get("data") or {}).get("block_map") or {}
            page_blocks = []
            for bid, block in bmap.items():
                bd = block.get("data", {})
                if bd.get("type") == "page":
                    page_blocks.append({
                        "bid": bid,
                        "children_count": len(bd.get("children", [])),
                        "children_first5": bd.get("children", [])[:5],
                        "children_last3": bd.get("children", [])[-3:] if bd.get("children") else [],
                    })

            chunks.append({
                "url_params": response.url.split("?")[1][:200] if "?" in response.url else "",
                "block_count": len(bmap),
                "page_blocks": page_blocks,
                "sample_types": {},
            })
            types = {}
            for bid, block in bmap.items():
                bt = block.get("data", {}).get("type", "?")
                types[bt] = types.get(bt, 0) + 1
            chunks[-1]["sample_types"] = types
        except Exception as e:
            chunks.append({"error": str(e)})

    page.on("response", on_cv_response)

    url = "https://bytedance.larkoffice.com/docx/BqWsdwuzGo611ix5Uq4cfT53nQb"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    page.remove_listener("response", on_cv_response)

    print(f"=== TOTAL CHUNKS: {len(chunks)} ===\n")
    for i, chunk in enumerate(chunks):
        if "error" in chunk:
            print(f"  Chunk {i}: ERROR - {chunk['error']}")
            continue
        print(f"  Chunk {i}: {chunk['block_count']} blocks, params={chunk['url_params'][:120]}")
        print(f"    Types: {chunk['sample_types']}")
        for pb in chunk["page_blocks"]:
            print(f"    PAGE BLOCK: {pb['bid']}, children={pb['children_count']}")
            print(f"      first5: {pb['children_first5']}")
            print(f"      last3: {pb['children_last3']}")
        print()

    # Merge all blocks and check the page block's children
    merged = {}
    for chunk in chunks:
        if "error" in chunk:
            continue
    # Re-fetch to get actual data
    all_blocks = {}
    page2 = await ctx.new_page()

    async def on_cv2(response):
        if "/docx/pages/client_vars" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            bmap = (body.get("data") or {}).get("block_map") or {}
            all_blocks.update(bmap)
        except:
            pass

    page2.on("response", on_cv2)
    await page2.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page2.wait_for_timeout(15000)
    page2.remove_listener("response", on_cv2)

    print(f"\n=== MERGED: {len(all_blocks)} total blocks ===")
    # Find all page blocks
    for bid, block in all_blocks.items():
        bd = block.get("data", {})
        if bd.get("type") == "page":
            children = bd.get("children", [])
            print(f"  Page block: {bid}, children={len(children)}")
            # Check if all children exist in merged
            missing = [c for c in children if c not in all_blocks]
            print(f"  Missing children: {len(missing)}")
            # Check: how many blocks are reachable from this page?
            visited = set()
            stack = [bid]
            while stack:
                curr = stack.pop()
                if curr in visited:
                    continue
                visited.add(curr)
                b = all_blocks.get(curr, {})
                ch = b.get("data", {}).get("children", [])
                # Also check cell_set for tables
                cell_set = b.get("data", {}).get("cell_set", {})
                for cv in cell_set.values():
                    cb = cv.get("block_id", "")
                    if cb:
                        ch.append(cb)
                stack.extend(ch)
            print(f"  Reachable blocks: {len(visited)} out of {len(all_blocks)}")
            print(f"  Unreachable: {len(all_blocks) - len(visited)}")

    await browser.close()
    await pw.stop()

asyncio.run(diag())
