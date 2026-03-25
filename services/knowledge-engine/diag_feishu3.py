"""Trace actual extraction: compare raw block data vs parsed markdown."""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

async def diag():
    from playwright.async_api import async_playwright
    from pathlib import Path
    sys.path.insert(0, ".")
    from app.services.harvester import parse_feishu_document, _blocks_to_md, _get_text, _cell_to_text

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)

    auth_path = r"\app\data\feishu_auth.json"
    ctx_kw = {}
    if Path(auth_path).exists():
        ctx_kw["storage_state"] = auth_path
    ctx = await browser.new_context(**ctx_kw)
    page = await ctx.new_page()

    url = "https://bytedance.larkoffice.com/docx/BqWsdwuzGo611ix5Uq4cfT53nQb"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    raw = await page.evaluate("""() => {
        try {
            if (window.DATA && window.DATA.clientVars) {
                return JSON.stringify(window.DATA.clientVars);
            }
        } catch(e) {}
        return null;
    }""")

    await browser.close()
    await pw.stop()

    if not raw:
        print("ERROR: No clientVars data")
        return

    cv = json.loads(raw)
    bmap = cv["data"]["block_map"]

    # Parse and get markdown
    doc = parse_feishu_document(raw)
    if doc:
        md = doc["markdown"]
        print(f"=== PARSED: {len(doc['text'])} chars, {doc['block_count']} blocks ===")
        print(f"MD length: {len(md)} chars")
        print()
        print("=== FULL MARKDOWN ===")
        print(md[:3000])
        print("...")
        print()

    # Trace the 3rd table (the big one with 7 columns)
    table_bid = "doxcng5qQLknr8tFokn9OprVxih"
    table_data = bmap[table_bid]["data"]
    rows = table_data.get("rows_id", [])
    cols = table_data.get("columns_id", [])
    cell_set = table_data.get("cell_set", {})
    print(f"=== TABLE {table_bid}: {len(rows)} rows x {len(cols)} cols ===")

    for ri, row_id in enumerate(rows[:4]):
        print(f"\n  Row {ri}: {row_id}")
        for ci, col_id in enumerate(cols):
            key = row_id + col_id
            cell_info = cell_set.get(key, {})
            cell_bid = cell_info.get("block_id", "")
            merge = cell_info.get("merge_info", {})
            rs = merge.get("row_span", 1)
            cs = merge.get("col_span", 1)

            if not cell_bid:
                print(f"    Col {ci}: NO CELL BID (key={key[:30]}...)")
                continue

            cell_block = bmap.get(cell_bid, {})
            cell_bd = cell_block.get("data", {})
            cell_ch = cell_bd.get("children", [])
            cell_text_result = _cell_to_text(bmap, cell_ch)

            # Also trace what the children actually are
            child_details = []
            for cid in cell_ch[:3]:
                cb = bmap.get(cid, {}).get("data", {})
                ct = _get_text(cb)
                child_details.append(f"{cb.get('type','?')}:'{ct[:40]}'" if ct else f"{cb.get('type','?')}:EMPTY")

            print(f"    Col {ci} (span={rs}x{cs}): result='{cell_text_result[:60]}' children={child_details}")

asyncio.run(diag())
