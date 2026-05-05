"""W1 + W2 + W3a + W3b tools。

注册顺序：在 `app.mcp.server` import 时通过 `import app.mcp.tools.<x>` 等触发副作用。

20 tool 总览：
- W1 (5): list_skus, get_sku, list_kbs, search_kb, list_briefs
- W2 (5): query_costs, compute_margin, generate_brief, generate_image, generate_video
- W3a (3): gather_brief_context, record_cost, disable_cost_item
- W3b (7): fetch_compass_store_daily, fetch_compass_sku_detail,
           fetch_compass_search_traffic, fetch_yuntu_5a, fetch_yuntu_brand_mind,
           kb_upload_doc, kb_set_role
"""
