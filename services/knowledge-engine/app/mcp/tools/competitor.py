"""竞品调研 tools（W1 竞品调研切片 · 2026-06-01）。

reverse_storyboard 的"竞品镜像"：拆别人淘宝的主图/详情页 → 卖点/构图/配色/设计/内容。
两段式（老板拍板）：
  - competitor_search：搜词 → 抓前 N 卡片 → LLM 相关性过滤 → md 榜单（老板挑）
  - competitor_decompose：对挑中的商品 → 抓主图+详情页 → 多模态 LLM 拆 5 维度 md

浏览器层在 scout-agent（competitor_research service 经 HTTP 调）；本文件只做
LLM（相关性过滤 + 视觉拆解）+ trace + 审计。老板选了"只出 md 报告"——不落 DB。
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services import competitor_research as cr
from app.services.ai_hub_client import AIHubClient

_MAX_DECOMPOSE_ITEMS = 12   # 两段式下老板通常挑几个；硬上限防跑飞


def _extract_json(text: str) -> dict | None:
    """从 LLM 自由文本里抠 JSON 对象。失败返 None。"""
    if not text:
        return None
    for attempt in (text, ):
        try:
            return json.loads(attempt)
        except Exception:
            pass
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m2 = re.search(r"\{[\s\S]*\}", text)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return None


@tool_with_audit(mcp, require_approval=False)
async def competitor_search(
    query: str,
    top_n: int = 50,
    platform: str = "taobao",
    relevance_filter: bool = True,
    headless: bool | None = None,
    max_pages: int = 3,
) -> dict:
    """竞品调研第 1 步：淘宝搜词 → 抓前 N 个商品卡片 → 相关性过滤 → markdown 榜单。

    抓的是搜索页**显示价 + 月销 + 主图 + 链接**（不进详情页，反爬风险低）。
    用 LLM 把"不是该产品本身"的（配件/赠品/工具/不同品类）过滤掉。

    Args:
        query: 要调研的产品词，如 "有机酱油"
        top_n: 抓前几个（默认 50）
        platform: 当前仅 'taobao'（京东后续接）
        relevance_filter: True=LLM 过滤掉不相关商品（默认）；False=原样全返
        headless: None=用 scout-agent 默认；淘宝拦得狠时传 False（需 host 跑非 headless）
        max_pages: 翻几页凑够 top_n（一页约 44 条）

    Returns:
        {ok, result:{items, skipped, count, markdown, debug}, trace, next_step_hint}
    """
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "empty_query", "hint": "query 不能为空，如 '有机酱油'"}
    if platform != "taobao":
        return {"ok": False, "error": "unsupported_platform",
                "hint": f"当前只支持 taobao，京东后续接。收到 platform={platform}"}

    scout = await cr.scout_search(query, top_n=top_n, headless=headless, max_pages=max_pages)
    if not scout.get("ok"):
        # 把 scout 的 error/hint/debug 透出去（含 login_required 引导）
        return {
            "ok": False,
            "error": scout.get("error", "scout_failed"),
            "hint": scout.get("hint", "scout-agent 抓取失败"),
            "debug": scout.get("debug"),
        }

    items: list[dict] = scout.get("items") or []
    cfg = get_model_for_tool("competitor_search")
    provider, model = cfg["provider"], cfg["model"]
    relevance_meta = "off"
    skipped: list[dict] = []
    final_prompt_preview = ""

    if relevance_filter and items:
        titles_block = "\n".join(
            f"{it.get('rank', i + 1)}. {(it.get('title') or '').strip()[:120]}"
            for i, it in enumerate(items)
        )
        try:
            system_prompt = prompts.load("competitor_relevance.system")
            user_prompt = prompts.render(
                "competitor_relevance.user", query=query, titles_block=titles_block,
            )
            final_prompt_preview = (system_prompt + "\n\n---\n\n" + user_prompt)[:6000]
            client = AIHubClient()
            resp = await client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                provider=provider, model=model,
                temperature=float(cfg.get("temperature", 0.1)),
                max_tokens=int(cfg.get("max_tokens", 2048)),
            )
            parsed = _extract_json(resp.get("content") or "")
            if parsed and isinstance(parsed.get("relevant_ranks"), list):
                # LLM JSON 的 rank 可能是 int / float(1.0) / 数字字符串，都归一成 int
                # （否则 float 会被 isdigit 漏掉 → 该商品被静默误删）
                relevant: set[int] = set()
                for r in parsed["relevant_ranks"]:
                    if isinstance(r, bool):
                        continue
                    if isinstance(r, int):
                        relevant.add(r)
                    elif isinstance(r, float) and r == int(r):
                        relevant.add(int(r))
                    elif isinstance(r, str) and r.strip().isdigit():
                        relevant.add(int(r.strip()))
                reason_by_rank = {
                    int(s.get("rank")): (s.get("reason") or "判定不相关")
                    for s in (parsed.get("skipped") or [])
                    if str(s.get("rank", "")).lstrip("-").isdigit()
                }
                kept, dropped = [], []
                for it in items:
                    rk = it.get("rank")
                    if rk in relevant:
                        kept.append(it)
                    else:
                        dropped.append({"rank": rk, "title": it.get("title"),
                                        "reason": reason_by_rank.get(rk, "判定不相关")})
                if kept:                     # 过滤后还有货才采用，否则 fail-open
                    items, skipped = kept, dropped
                    relevance_meta = f"on (kept {len(kept)}/{len(kept) + len(dropped)})"
                else:
                    relevance_meta = "on_but_empty_fallback_all"
            else:
                relevance_meta = "parse_failed_fallback_all"
        except Exception as exc:
            logger.warning("competitor_search relevance filter failed (fallback to all): %s", exc)
            relevance_meta = f"error_fallback_all:{type(exc).__name__}"

    markdown = cr.render_listing_markdown(query, items, skipped, platform="淘宝")

    result = {
        "ok": True,
        "result": {
            "query": query,
            "count": len(items),
            "items": items,
            "skipped": skipped,
            "relevance_filter": relevance_meta,
            "markdown": markdown,
            "debug": scout.get("debug"),
        },
        "trace": build_trace(
            provider=provider, model=model,
            prompt=final_prompt_preview or f"(relevance_filter={relevance_meta}; 无 LLM 调用)",
            params={"query": query, "top_n": top_n, "n_items": len(items),
                    "n_skipped": len(skipped), "relevance": relevance_meta},
            cost_estimate=f"relevance 过滤 1 次 LLM（{len(items) + len(skipped)} 标题）",
        ),
    }
    # 建议深拆前 3 个（老板可改）
    suggest_urls = [it.get("item_url") for it in items[:3] if it.get("item_url")]
    return attach_next_step(
        result,
        suggested_tool="competitor_decompose",
        suggested_args={"item_urls": suggest_urls, "focus_product": query},
        human_text=(
            f"抓到 {len(items)} 个相关竞品。挑你要深拆的（给序号或链接），"
            f"我对每个出「卖点/构图/配色/设计/内容」。"
        ),
    )


@tool_with_audit(mcp, require_approval=False)
async def competitor_decompose(
    item_url: str | None = None,
    item_urls: list[str] | None = None,
    items: list[dict] | None = None,
    local_images: list[str] | None = None,
    focus_product: str = "",
    headless: bool | None = None,
    max_main_images: int = 6,
    max_detail_images: int = 8,
    model: str | None = None,
) -> dict:
    """竞品调研第 2 步：对挑中的商品抓主图+详情页 → 多模态 LLM 拆 5 维度 markdown。

    5 维度：卖点 / 构图 / 配色 / 设计 / 内容。每条标依据哪张图，反幻觉（图里没有的不编）。
    图片是 alicdn CDN（公开可取），KE 下载转 base64 data URI 喂 gemini 多模态。

    **详情页兜底**：淘宝 PC 详情页常"验证码拦截"抓不到图。若传 `items`（competitor_search
    返的 items，带 main_image_url），详情页被挡时自动退用**搜索主图**拆解（卖点/构图/配色/设计
    仍可出，详情页内容缺会标注）。所以优先传 items 而非 item_urls。

    Args:
        item_url: 单个商品链接（跟 item_urls 二选一/可叠加）
        item_urls: 多个商品链接（无主图兜底）
        items: competitor_search 的 items（含 item_url + main_image_url），详情页被挡时兜底用主图
        focus_product: 产品词（如 '有机酱油'），帮模型聚焦 + 作详情页"先搜再进"的搜索词
        headless: None=scout 默认；淘宝拦得狠传 False
        max_main_images: 每个商品取几张主图喂模型（默认 6）
        max_detail_images: 每个商品取几张详情页图（默认 8）
        model: 覆盖 tool_models.yaml 的视觉模型（None=用 yaml）

    Returns:
        {ok, result:{products, markdown, errors}, trace}
    """
    # 工作单：优先 items（带 main_image_url 兜底）；否则 item_url(s)
    work: list[dict] = []
    seen_u: set[str] = set()
    for it in (items or []):
        u = (it.get("item_url") or "").strip()
        if u and u not in seen_u:
            seen_u.add(u)
            work.append({"item_url": u, "main_image_url": it.get("main_image_url"),
                         "title": it.get("title"), "price": it.get("price")})
    for u in ([item_url] if item_url else []) + (item_urls or []):
        u = (u or "").strip()
        if u and u not in seen_u:
            seen_u.add(u)
            work.append({"item_url": u})
    if not work and not local_images:
        return {"ok": False, "error": "no_url",
                "hint": "给 items / item_url / item_urls / local_images（从 competitor_search 榜单里挑，或手动截图）"}
    if len(work) > _MAX_DECOMPOSE_ITEMS:
        return {"ok": False, "error": "too_many",
                "hint": f"一次最多拆 {_MAX_DECOMPOSE_ITEMS} 个（烧 vision token），收到 {len(work)} 个。分批来。"}

    cfg = get_model_for_tool("competitor_decompose")
    provider = cfg["provider"]
    used_model = (model or cfg["model"]).strip()
    temperature = float(cfg.get("temperature", 0.3))
    max_tokens = int(cfg.get("max_tokens", 6000))

    try:
        system_prompt = prompts.load("competitor_decompose.system")
    except FileNotFoundError as exc:
        return {"ok": False, "error": "prompt_missing", "hint": str(exc)}

    client = AIHubClient()
    products: list[dict] = []
    errors: list[dict] = []
    total_images = 0
    final_prompt_preview = ""

    # ── 手动截图模式（B）：老板自己截的详情页/主图（容器内路径），直接拆，绕开抓取 ──
    if local_images:
        blocks, ok_paths = cr.read_local_images_as_blocks(
            local_images, max_count=max_main_images + max_detail_images)
        if not blocks:
            return {"ok": False, "error": "no_local_images",
                    "hint": "本地图读不到；路径要容器内可访问（如 /host/Desktop/x.jpg）"}
        user_prompt = prompts.render(
            "competitor_decompose.user", focus_product=focus_product or "(未指定，按图自判品类)",
            main_count=len(blocks), detail_count=0,
            extra_block="（这些是老板手动截的商品详情页/主图截图，按整体拆解全部 5 维度）")
        content = [{"type": "text", "text": user_prompt},
                   {"type": "text", "text": f"—— 老板手动提供的 {len(blocks)} 张商品截图 ——"}, *blocks]
        try:
            resp = await client.chat(
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": content}],
                provider=provider, model=used_model,
                temperature=temperature, max_tokens=max_tokens, enforce_human_voice=True)
            md = (resp.get("content") or "").strip()
        except Exception as exc:
            return {"ok": False, "error": "llm_call_failed", "hint": f"{type(exc).__name__}: {exc}"}
        if not md:
            return {"ok": False, "error": "empty_llm_output", "hint": "模型没返内容，图太多就少传几张"}
        report = f"# 竞品拆解（手动截图{('：' + focus_product) if focus_product else ''}）\n\n" + md
        return {
            "ok": True,
            "result": {"products": [{"title": "(手动截图)", "markdown": md, "image_count": len(ok_paths)}],
                       "errors": [], "markdown": report},
            "trace": build_trace(
                provider=provider, model=used_model,
                prompt=(system_prompt + "\n---\n" + user_prompt)[:4000],
                params={"mode": "local_images", "n_images": len(blocks)},
                cost_estimate=f"1 次多模态（{len(blocks)} 张手动截图）"),
        }

    for w in work:
        url = w["item_url"]
        fallback_note = ""
        main_blocks, main_ok = [], []
        detail_blocks, detail_ok = [], []
        # 详情页走移动 H5 滚动截图（PC item 页/DOM 抓不到）；渲染出来就用截图当详情
        shotsr = await cr.scout_detail_shots(url, headless=headless, search_query=focus_product or None)
        if shotsr.get("ok") and not shotsr.get("blocked") and shotsr.get("shots"):
            for b64 in shotsr["shots"][: max_detail_images + 2]:
                detail_blocks.append({"type": "image_url",
                                      "image_url": {"url": "data:image/jpeg;base64," + b64}})
            detail_ok = list(range(len(detail_blocks)))

        # 详情页被挡 → 退用搜索主图（仍能拆卖点/构图/配色/设计）
        if not detail_blocks and w.get("main_image_url"):
            mb, mok = await cr.fetch_images_as_blocks([w["main_image_url"]], max_count=1)
            if mb:
                main_blocks, main_ok = mb, mok
                fallback_note = "⚠️ 详情页被淘宝反爬挡，本拆解**仅基于搜索主图**——详情页内容(第5节)缺。"

        title = w.get("title") or "(无标题)"

        if not main_blocks and not detail_blocks:
            errors.append({"item_url": url, "error": "no_images",
                           "hint": "详情页被挡且无搜索主图兜底；传 items（带 main_image_url）可兜底"})
            continue

        try:
            extra_block = fallback_note
            user_prompt = prompts.render(
                "competitor_decompose.user",
                focus_product=focus_product or "(未指定，按图自判品类)",
                main_count=len(main_blocks),
                detail_count=len(detail_blocks),
                extra_block=extra_block,
            )
            if not final_prompt_preview:
                final_prompt_preview = (system_prompt + "\n\n---\n\n" + user_prompt)[:6000]

            content: list[dict] = [{"type": "text", "text": user_prompt}]
            if main_blocks:
                content.append({"type": "text", "text": f"—— 以下是 {len(main_blocks)} 张【主图】 ——"})
                content.extend(main_blocks)
            if detail_blocks:
                content.append({"type": "text", "text": f"—— 以下是 {len(detail_blocks)} 张【详情页图】 ——"})
                content.extend(detail_blocks)

            resp = await client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                provider=provider, model=used_model,
                temperature=temperature, max_tokens=max_tokens,
                enforce_human_voice=True,
            )
            decomp_md = (resp.get("content") or "").strip()
            if not decomp_md:
                errors.append({"item_url": url, "error": "empty_llm_output",
                               "hint": "模型没返内容；可能图太多超 token，调小 max_*_images"})
                continue

            total_images += len(main_blocks) + len(detail_blocks)
            price = w.get("price")
            header = (
                f"## {title}\n\n"
                f"- 链接：{url}\n"
                f"- 显示价：{price or '—'}　|　主图 {len(main_ok)} 张、详情页 {len(detail_ok)} 张（已喂模型）\n"
                + (f"- {fallback_note}\n" if fallback_note else "")
            )
            products.append({
                "item_url": url, "title": title, "price": price,
                "main_image_count": len(main_ok), "detail_image_count": len(detail_ok),
                "markdown": header + "\n" + decomp_md,
            })
        except Exception as exc:
            logger.exception("competitor_decompose LLM failed for %s", url)
            errors.append({"item_url": url, "error": "llm_call_failed",
                           "hint": f"{type(exc).__name__}: {exc}"})

    if not products:
        return {
            "ok": False, "error": "all_failed",
            "hint": "所有商品都没拆成（抓图/模型失败）。看 errors。",
            "errors": errors,
        }

    parts = [f"# 竞品拆解（{len(products)} 个）" + (f"：{focus_product}" if focus_product else ""), ""]
    for p in products:
        parts.append(p["markdown"])
        parts.append("\n---\n")
    if errors:
        parts.append(f"> ⚠️ {len(errors)} 个没拆成：" + "；".join(
            f"{e['item_url'][:40]}…（{e.get('error')}）" for e in errors))
    report_md = "\n".join(parts)

    return {
        "ok": True,
        "result": {
            "products": products,
            "errors": errors,
            "markdown": report_md,
        },
        "trace": build_trace(
            provider=provider, model=used_model,
            prompt=final_prompt_preview,
            params={"n_products": len(products), "n_errors": len(errors),
                    "total_images_sent": total_images, "focus_product": focus_product},
            cost_estimate=f"{len(products)} 次多模态调用，共喂 ~{total_images} 张图",
        ),
    }
