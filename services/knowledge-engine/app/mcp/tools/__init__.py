"""W1 + W2 + W3a + W3b + W3c + W4-A + W4-B 切片 5/8/9/14 tools。

注册顺序：在 `app.mcp.server` import 时通过 `import app.mcp.tools.<x>` 等触发副作用。

35 tool 总览：
- W1 (5): list_skus, get_sku, list_kbs, search_kb, list_briefs
- W2 (5): query_costs, compute_margin, generate_brief, generate_image, generate_video
- W3a (3): gather_brief_context, record_cost, disable_cost_item
- W3b (7): fetch_compass_store_daily, fetch_compass_sku_detail,
           fetch_compass_search_traffic, fetch_yuntu_5a, fetch_yuntu_brand_mind,
           kb_upload_doc, kb_set_role
- W3c (3): summarize_text, parse_long_doc_with_gemini, query_template_chunks
- W4-A (4): rate_tool_call, agent_self_review, codify_pattern_to_skill,
            refresh_project_context
- W4-B 切片 5 (5): save_decision, schedule_observation, generate_image_compare,
                   send_wecom_message, dy_publish_creative
- W4-B 切片 8 (1): list_product_prices  # 工厂出厂价字典查询
- W4-B 切片 9 (1): list_channel_fees    # 渠道扣点率查询
- W4-B 切片 14 (1): generate_selling_points_matrix  # sku-pipeline step 2 卖点矩阵
"""
