---
name: audience-pack-sizing
description: Use when a 巨量云图 audience pack has been created and its estimated audience pack size is too large, too small, or outside launchable range.
---

# audience-pack-sizing: 巨量云图人群包量级校准

## Scope

Use after `crowd-sop` or `generate_audience_pack` has been executed in 巨量云图 and the created/previewed pack shows a real size problem. Do not use for writing a new circle-pack SOP from zero.

Core principle: **源图优先, 场景链继承, 证据决策.** Keep the original selling point -> scene -> audience signal lineage. A sizing edit is allowed only when it still inherits the adopted scene chain and can be clicked in the real Yuntu backend.

## Evidence Gate

Before deciding whether to shrink or expand, collect:

- Original SOP, audience units, combination formula, and target launch range.
- `include_ecommerce_data` from the adopted upstream run.
- 云图真实预估人数, screenshot or 截图, and exported audience analysis or 导出结果.

不得只凭画像占比、经验量级或 LLM 估算决策. 每一轮缩减/扩大后都要重新读取云图真实预估人数, save the screenshot/export evidence, and compare it with the previous round.

Volume is only the first gate. If the count is acceptable, still read the exported audience profile and judge precision before saying done. 不要把 acceptable size 判成 done by itself.

## Adjustment Order

先调整标签、时间窗、频次、组合公式，再考虑 lookalike.

Lookalike is not a repair tool. lookalike 只能在基础包有效但量级仍过小时使用. 不要靠 lookalike 补坏包, do not use it to mask wrong labels, broken scene inheritance, overly narrow keywords, or a polluted base pack.

## 量级满意但准度不足

Use this branch when real Yuntu count is inside range, but the exported profile shows weak scene/product intent or broad unrelated interests.

- Diagnosis wording: **量级满意但准度不足**. Do not call it too large, too small, failed, or complete.
- If the profile mostly comes from A base demographics/interests and B/C search/content intent layers are weak, classify it as **放量主包 / 内容探索包**.
- If the profile keeps strong search/product/content intent tied to `卖点 -> 场景 -> 人群 -> 内容信号`, classify it as **精准核心包**.
- Check 泛兴趣污染 explicitly: 汽车、游戏、二次元、影视、时尚 and other broad interests are pollution signals when they dominate without scene-chain justification.
- Next step is not a size ladder by default. Either add one intent gate / prune one pollution cluster, or keep this as reach_master and create a separate precision_core pack.
- Always include 后续内容生成继承建议: creative work should inherit the final exported profile and pack type, not just the original audience name.

## 过小放宽阶梯

Move down this ladder one step at a time, then re-check real Yuntu size:

1. **Check construction errors**: wrong intersection, accidental exclusion, missing keyword import, or data factory label not referenced back into custom audience.
2. **放宽标签**: replace too-specific child labels with parent/sibling labels that still match the scene chain; add adjacent content/search clusters inherited from L1/L2/L3.
3. **放宽时间窗**: 7/15 days -> 30/60/90 days when the behavior remains meaningful.
4. **放宽频次**: >=3 -> >=2 -> >=1; broaden from deep interaction to view/search/content exposure only when it still captures the intended person.
5. **放宽组合公式**: change unnecessary `A ∩ B ∩ C` into `A ∩ (B ∪ C)` or split into multiple valid scene clusters with `A ∪ B`.
6. **Expand keywords**: 关键词默认 500 词 through `generate_keyword_pack(target_count=500, recall_mode="reach", keyword_strategy="audience_content")` for non-commerce packs; keep seeds tied to scene-chain content interests.
7. **Only then consider lookalike** if the base pack is clean, source-grounded, and still too small.

## 过大收窄阶梯

Move down this ladder one step at a time, then re-check real Yuntu size:

1. **Check formula breadth**: accidental broad union, missing required intent signal, or all-purpose demographics that swallow the pack.
2. **收窄标签**: replace broad parent labels with precise child labels, industry/content subcategories, or source-graph labels that still inherit the scene chain.
3. **收窄时间窗**: 90/60 days -> 30/15/7 days according to funnel freshness.
4. **收窄频次**: >=1 -> >=2 -> >=3; prefer repeated search/view/interaction over one-off exposure.
5. **收窄组合公式**: change loose `A ∪ B ∪ C` into scene-specific packs, add `A ∩ B` intent gates, or exclude obvious pollution with `A - B`.
6. **Prune keywords**: remove pure SKU terms, unrelated viral words, and clusters that no longer inherit the scene chain; keep content/search words that describe the real target person.

## Ecommerce Guardrails

Preserve `include_ecommerce_data` exactly.

- `include_ecommerce_data=False`: 非电商包 must stay non-commerce. 禁止把非电商包改成电商成交标签. Do not add 商品人群标签, 电商品类成交偏好, 电商品牌成交偏好, purchase, add-to-cart, browse, or transaction labels. Use content/search audience tags, Douyin content preferences, attributes, region, and non-commerce interest signals. Keyword route uses `keyword_strategy="audience_content"`.
- `include_ecommerce_data=True`: commerce labels may be used, but only when they are scene-relevant and not a shortcut that erases the original audience strategy.

## Output Contract

Return an operator-facing sizing note with:

| Field | Required content |
|---|---|
| Current evidence | 云图真实预估人数 + screenshot/export path or description |
| Diagnosis | Too small, too large, acceptable, or 量级满意但准度不足; cite the target range and pack type |
| Next adjustment | One ladder step only: label, time window, frequency, formula, keyword, or lookalike |
| Constraint check | Source graph, scene-chain inheritance, `include_ecommerce_data`, keyword strategy, 泛兴趣污染, and bottom/base vs intent-layer contribution |
| Re-check instruction | Exact place to read the next Yuntu estimate and what screenshot/export to keep |

Stop only when the pack is inside range **and** pack type, precision status, and content inheritance direction are clear, or when further edits would break source grounding, scene inheritance, or ecommerce policy.
