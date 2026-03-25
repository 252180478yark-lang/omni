"""Check: does page block's children get extended when merging all chunks?"""
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

    all_api_blocks = {}
    chunk_order = []

    async def on_cv(response):
        if "/docx/pages/client_vars" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            bmap = (body.get("data") or {}).get("block_map") or {}
            chunk_order.append(list(bmap.keys()))
            all_api_blocks.update(bmap)
        except:
            pass

    page.on("response", on_cv)

    url = "https://bytedance.larkoffice.com/docx/BqWsdwuzGo611ix5Uq4cfT53nQb"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # Get initial clientVars
    raw = await page.evaluate("""() => {
        try {
            if (window.DATA && window.DATA.clientVars) {
                return JSON.stringify(window.DATA.clientVars);
            }
        } catch(e) {}
        return null;
    }""")

    await page.wait_for_timeout(12000)
    page.remove_listener("response", on_cv)

    if not raw:
        print("No initial clientVars")
        return

    cv = json.loads(raw)
    initial_bmap = cv["data"]["block_map"]

    # Find page block in initial data
    page_bid = None
    for bid, block in initial_bmap.items():
        bd = block.get("data", {})
        if bd.get("type") == "page":
            page_bid = bid
            children = bd.get("children", [])
            print(f"PAGE BLOCK: {bid}")
            print(f"  Children count: {len(children)}")
            print(f"  First 5: {children[:5]}")
            print(f"  Last 5: {children[-5:]}")
            break

    # Check if any API chunks also have a page block
    for bid, block in all_api_blocks.items():
        bd = block.get("data", {})
        if bd.get("type") == "page":
            print(f"\nAPI also has page block: {bid}")
            print(f"  Children: {len(bd.get('children', []))}")

    # Merge and check reachability
    merged = dict(initial_bmap)
    merged.update(all_api_blocks)
    print(f"\nMerged total: {len(merged)} blocks")

    # Check: does the page block in merged have same children?
    page_data = merged[page_bid]["data"]
    page_children = page_data.get("children", [])
    print(f"Page children after merge: {len(page_children)}")

    # Check reachability
    visited = set()
    stack = [page_bid]
    while stack:
        curr = stack.pop()
        if curr in visited:
            continue
        visited.add(curr)
        b = merged.get(curr, {})
        bd = b.get("data", {})
        ch = list(bd.get("children", []))
        cell_set = bd.get("cell_set", {})
        for cv_val in cell_set.values():
            cb = cv_val.get("block_id", "")
            if cb:
                ch.append(cb)
        stack.extend(ch)

    print(f"Reachable from page: {len(visited)} out of {len(merged)}")
    print(f"Unreachable: {len(merged) - len(visited)}")

    # Check: what types are in unreachable blocks?
    unreachable = set(merged.keys()) - visited
    unreachable_types = {}
    for bid in unreachable:
        bt = merged[bid].get("data", {}).get("type", "?")
        unreachable_types[bt] = unreachable_types.get(bt, 0) + 1
    print(f"Unreachable types: {unreachable_types}")

    # Check: do unreachable blocks have parent_id that points to reachable blocks?
    orphan_parents = set()
    for bid in list(unreachable)[:10]:
        bd = merged[bid].get("data", {})
        parent = bd.get("parent_id", "")
        if parent:
            orphan_parents.add(parent)
            in_merged = parent in merged
            is_reachable = parent in visited
            print(f"  Unreachable {bid} ({bd.get('type','?')}): parent={parent}, in_merged={in_merged}, parent_reachable={is_reachable}")

    await browser.close()
    await pw.stop()

asyncio.run(diag())
