"""从 Excel / PDF / Word / CSV 报价单文本里抽取成本项 (cost_items) 草稿.

输出用于前端预览 + 用户编辑后批量入库；本模块不写 DB.

调用约定：
- 输入：document_parser.extract_text 的产物（可能是 markdown 表格或自由段落）
- 输出：list[dict]，每项尽量贴近 cost_items 表字段
- 不确定字段留 None；LLM 不强行编造
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT = """以下是从一份报价单 / Excel / PDF / Word 文档里抽取的文本，请把里面的成本项一条条整理出来。

**输出要求**：
严格 JSON 数组，不要 markdown 代码块，不要任何额外文字。每条结构如下：

[
  {{
    "category": "product" | "logistics" | "partner_quote",
    "item_name": "瓶身-玻璃250ml",
    "unit_cost": 0.45,
    "currency": "CNY",
    "unit": "瓶",
    "quantity_per_unit": 1,
    "vendor": "山东瓶厂",
    "sku_id": null,
    "notes": "原报价单备注：批量起订量 5000",
    "confidence": 0.9
  }}
]

**字段规则**：
- category 三选一：
  * product = 产品成本（原料 / 包装 / 瓶身 / 标签 / 箱 / 人工 / 加工费）
  * logistics = 物流（快递 / 专线 / 同城 / 仓储费）
  * partner_quote = 合作方报价（代工厂 / OEM / 服务商整体报价）
- unit_cost 必须是数字（"￥0.45/瓶" 提取成 0.45），不带货币符号
- unit 是单价的计量单位（瓶 / 箱 / 件 / kg / 单 / 公里 / 公斤）
- quantity_per_unit 默认 1；如果说"一箱 24 瓶"且单价是箱单价 → 填 24
- vendor 是供应商或合作方名称；没写就 null
- sku_id 一般 null（除非文件里明确标注了 SKU 编号）
- confidence 是你对这条解析的置信度 0-1（数字模糊 / 描述含混的填 0.5 以下）
- notes 把原文中没结构化的信息（备注 / 批次 / 起订量）写进去
- 如果整段没有任何成本项可提取 → 返回空数组 []
- 同一物品多个规格分别抽成多条（如"24瓶箱 240元、30瓶箱 280元"）

**文档原文**：

{text}"""


_MAX_INPUT_CHARS = 40000  # 单次 LLM 输入字符数上限；大表/长 PDF 分段


async def extract_cost_items(text: str, *, model: str | None = None) -> list[dict]:
    """text → LLM → 标准化 cost_items 草稿列表."""
    text = (text or "").strip()
    if not text:
        return []

    segments = _split_long_text(text, _MAX_INPUT_CHARS)
    items: list[dict] = []
    for seg_idx, seg in enumerate(segments):
        try:
            seg_items = await _call_extractor(seg, model=model)
        except Exception:
            logger.warning("cost extractor failed seg=%d", seg_idx, exc_info=True)
            continue
        for it in seg_items:
            normalized = _normalize_item(it)
            if normalized:
                items.append(normalized)
    return items


def _split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    segs: list[str] = []
    cursor = 0
    while cursor < len(text):
        chunk = text[cursor:cursor + limit]
        cut = max(chunk.rfind("\n\n"), chunk.rfind("\n"), chunk.rfind("。"))
        if cut < int(limit * 0.5):
            cut = limit
        segs.append(text[cursor:cursor + cut].strip())
        cursor += cut
    return [s for s in segs if s]


async def _call_extractor(text: str, *, model: str | None) -> list[dict]:
    payload: dict = {
        "messages": [{"role": "user", "content": _PROMPT.format(text=text)}],
        "temperature": 0.1,
        "max_tokens": 4000,
    }
    if model:
        payload["model"] = model

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
            json=payload,
        )
        resp.raise_for_status()
        raw = (resp.json().get("content") or "").strip()

    return _parse_json_array(raw)


def _parse_json_array(raw: str) -> list[dict]:
    if not raw:
        return []
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    s = cleaned.find("[")
    e = cleaned.rfind("]")
    if s < 0 or e <= s:
        logger.warning("LLM 输出未找到 JSON 数组: %s", raw[:200])
        return []
    try:
        parsed = json.loads(cleaned[s:e+1])
    except json.JSONDecodeError:
        logger.warning("JSON 解析失败: %s", cleaned[:200])
        return []
    if not isinstance(parsed, list):
        return []
    return [x for x in parsed if isinstance(x, dict)]


_VALID_CATEGORIES = {"product", "logistics", "partner_quote"}


def _normalize_item(raw: dict) -> dict | None:
    """LLM 输出 → 贴近 cost_items 表的字段；不合规直接丢弃."""
    category = (raw.get("category") or "").strip()
    if category not in _VALID_CATEGORIES:
        return None
    name = (raw.get("item_name") or "").strip()
    if not name:
        return None
    try:
        unit_cost = float(raw.get("unit_cost"))
    except (TypeError, ValueError):
        return None
    if unit_cost < 0:
        return None
    try:
        qpu = float(raw.get("quantity_per_unit") or 1)
    except (TypeError, ValueError):
        qpu = 1.0
    if qpu <= 0:
        qpu = 1.0
    currency = (raw.get("currency") or "CNY").strip().upper()[:3] or "CNY"
    unit = (raw.get("unit") or "件").strip() or "件"
    vendor = (raw.get("vendor") or None) or None
    sku_id = raw.get("sku_id") or None
    notes = (raw.get("notes") or None) or None
    try:
        confidence = float(raw.get("confidence") or 0.7)
    except (TypeError, ValueError):
        confidence = 0.7
    return {
        "category": category,
        "item_name": name[:200],
        "unit_cost": unit_cost,
        "currency": currency,
        "unit": unit[:20],
        "quantity_per_unit": qpu,
        "vendor": (vendor or None) and str(vendor)[:200],
        "sku_id": (sku_id or None) and str(sku_id)[:64],
        "notes": (notes or None) and str(notes)[:1000],
        "confidence": max(0.0, min(1.0, confidence)),
    }
