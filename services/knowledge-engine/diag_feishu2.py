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

    url = "https://bytedance.larkoffice.com/docx/BqWsdwuzGo611ix5Uq4cfT53nQb"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    result = await page.evaluate("""() => {
        const cv = window.DATA && window.DATA.clientVars;
        if (!cv || !cv.data) return JSON.stringify({error: 'no data'});
        const bmap = cv.data.block_map || {};

        // Find all table blocks and dump their structure
        const tables = [];
        for (const [bid, block] of Object.entries(bmap)) {
            const bd = block.data || {};
            if (bd.type !== 'table') continue;
            tables.push({
                bid,
                rows_id: bd.rows_id,
                columns_id: bd.columns_id,
                cell_set_keys: bd.cell_set ? Object.keys(bd.cell_set).slice(0, 10) : [],
                cell_set_sample: bd.cell_set ? JSON.stringify(Object.entries(bd.cell_set).slice(0, 3)).substring(0, 600) : 'null',
                children: bd.children,
            });
        }

        // For the first table, trace a cell's children to see if the child has text
        let cellChildTrace = null;
        if (tables.length > 0 && tables[0].cell_set_keys.length > 0) {
            const tableData = bmap[tables[0].bid].data;
            const firstCellKey = Object.keys(tableData.cell_set)[0];
            const cellInfo = tableData.cell_set[firstCellKey];
            const cellBid = cellInfo.block_id;
            if (cellBid && bmap[cellBid]) {
                const cellBlock = bmap[cellBid].data;
                const cellChildren = cellBlock.children || [];
                const childBlocks = cellChildren.map(cid => {
                    const cb = bmap[cid];
                    return cb ? {
                        cid,
                        type: cb.data.type,
                        text: cb.data.text ? JSON.stringify(cb.data.text).substring(0, 300) : 'null',
                        children: cb.data.children,
                    } : {cid, missing: true};
                });
                cellChildTrace = {
                    cellKey: firstCellKey,
                    cellBid,
                    cellType: cellBlock.type,
                    cellChildren: childBlocks,
                };
            }
        }

        // Also check: how does table cell_set key relate to rows_id and columns_id?
        let keyAnalysis = null;
        if (tables.length > 0) {
            const t = tables[0];
            const firstRow = t.rows_id ? t.rows_id[0] : null;
            const firstCol = t.columns_id ? t.columns_id[0] : null;
            const concat = firstRow && firstCol ? firstRow + firstCol : null;
            keyAnalysis = {
                firstRow,
                firstCol,
                concat,
                concatInKeys: concat ? t.cell_set_keys.includes(concat) : false,
                firstKey: t.cell_set_keys[0],
            };
        }

        return JSON.stringify({tables, cellChildTrace, keyAnalysis});
    }""")

    r = json.loads(result)
    print("=== TABLES ===")
    for t in r["tables"]:
        print(f"  Table {t['bid']}:")
        print(f"    rows_id ({len(t.get('rows_id') or [])}): {(t.get('rows_id') or [])[:3]}")
        print(f"    columns_id ({len(t.get('columns_id') or [])}): {(t.get('columns_id') or [])[:5]}")
        print(f"    cell_set_keys: {t['cell_set_keys']}")
        print(f"    cell_set_sample: {t['cell_set_sample']}")
        print()

    print("=== KEY ANALYSIS ===")
    ka = r["keyAnalysis"]
    if ka:
        print(f"  firstRow: {ka['firstRow']}")
        print(f"  firstCol: {ka['firstCol']}")
        print(f"  concat: {ka['concat']}")
        print(f"  concatInKeys: {ka['concatInKeys']}")
        print(f"  firstKey: {ka['firstKey']}")
    print()

    print("=== CELL CHILD TRACE ===")
    ct = r["cellChildTrace"]
    if ct:
        print(f"  cellKey: {ct['cellKey']}")
        print(f"  cellBid: {ct['cellBid']}")
        print(f"  cellType: {ct['cellType']}")
        for ch in ct["cellChildren"]:
            print(f"    child {ch['cid']}: type={ch.get('type')}, text={ch.get('text','')[:200]}")

    await browser.close()
    await pw.stop()

asyncio.run(diag())
