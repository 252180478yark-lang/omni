from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from httpx import AsyncClient

from app.config import Settings
from app.sources.base import RawArticle

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
你是一个 AI 资讯分析助手。对每篇输入文章输出结构化 JSON。

## 输出格式
{
  "articles": [
    {
      "index": 0,
      "summary_zh": "中文摘要 2-3 句话，概括核心内容",
      "tags": ["标签1", "标签2"],
      "relevance_score": 0.95
    }
  ]
}

## 纪律
- 只基于文章标题 + 摘要作判断，**禁止编造文章中未出现的事实**（发布时间、融资金额、模型名称等）。
- `index` 必须与输入中的 `[N]` 编号一一对应。
- `summary_zh` 是纯中文，不包含英文原文段。

## 标签规则（tags）
- **必须从以下清单中选择**（不在清单中的标签视为无效）：
  `LLM` / `RAG` / `Agent` / `多模态` / `图像生成` / `语音` / `芯片/GPU` /
  `开源` / `融资` / `产品发布` / `论文` / `监管/政策` / `应用落地` /
  `OpenAI` / `Google` / `Anthropic` / `Meta` / `百度` / `阿里` / `字节` / `深度求索`
- 每篇文章 1-3 个标签，按相关性从高到低排列。
- 若无任何标签匹配，返回空数组 `[]`。

## 相关性评分规则（relevance_score，0.0-1.0 浮点）
- `[0.80, 1.00]` — 直接相关：大模型研究、AI 产品发布、AI Agent 应用
- `[0.50, 0.80)` — 间接相关：AI 芯片、云服务、数据隐私、监管政策
- `[0.00, 0.50)` — 弱相关或无关：泛科技、手机评测、消费电子
- 区间端点归属：**左闭右开**，`0.80` 属于上一档。
""".strip()


@dataclass(slots=True)
class EnrichedArticle:
    raw: RawArticle
    summary_zh: str | None
    tags: list[str]
    relevance_score: float | None


class ArticleEnricher:
    def __init__(self, sp3_client: AsyncClient, settings: Settings):
        self.sp3_client = sp3_client
        self.settings = settings

    async def enrich(self, articles: list[RawArticle]) -> list[EnrichedArticle]:
        if not articles:
            return []

        all_results: list[EnrichedArticle] = []
        batch_size = max(1, self.settings.sp5_enrich_batch_size)
        for start in range(0, len(articles), batch_size):
            batch = articles[start : start + batch_size]
            batch_results = await self._enrich_batch_with_retry(batch)
            all_results.extend(batch_results)
        return all_results

    def filter_by_relevance(self, articles: list[EnrichedArticle]) -> list[EnrichedArticle]:
        threshold = self.settings.sp5_relevance_threshold
        return [item for item in articles if item.relevance_score is None or item.relevance_score >= threshold]

    async def _enrich_batch_with_retry(self, batch: list[RawArticle]) -> list[EnrichedArticle]:
        try:
            return await self._enrich_batch(batch)
        except Exception as exc:
            logger.warning("enricher first attempt failed, retrying once: %s", str(exc))
            try:
                return await self._enrich_batch(batch)
            except Exception as retry_exc:
                logger.error("enricher retry failed, fallback to raw snippet: %s", str(retry_exc))
                return [
                    EnrichedArticle(raw=item, summary_zh=None, tags=[], relevance_score=None)
                    for item in batch
                ]

    async def _enrich_batch(self, batch: list[RawArticle]) -> list[EnrichedArticle]:
        # 飞轮：累积规则拼到 SYSTEM_PROMPT 末尾
        system_with_rules = SYSTEM_PROMPT
        try:
            from httpx import AsyncClient as _AC
            ke_base = (self.settings.sp4_base_url or "").rstrip("/")
            if ke_base:
                async with _AC(timeout=5.0) as c:
                    r = await c.post(
                        f"{ke_base}/api/v1/prompt/render-rules",
                        json={"node_id": "news.enrich", "scope": None},
                    )
                    if r.status_code == 200:
                        suffix = ((r.json() or {}).get("data") or {}).get("suffix") or ""
                        if suffix:
                            system_with_rules = SYSTEM_PROMPT + suffix
        except Exception:
            pass

        response = await self.sp3_client.post(
            "/api/v1/ai/chat",
            json={
                "messages": [
                    {"role": "system", "content": system_with_rules},
                    {"role": "user", "content": self._build_user_prompt(batch)},
                ],
                "provider": self.settings.enricher_provider,
                "model": self.settings.enricher_model,
                "temperature": 0.3,
                "max_tokens": self.settings.enricher_max_tokens,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        content = ((payload.get("data") or {}).get("content")) if isinstance(payload, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("invalid SP3 response: missing data.content")

        parsed = self._parse_model_json(content)
        items = parsed.get("articles")
        if not isinstance(items, list):
            raise ValueError("invalid model output: articles is not a list")

        by_index: dict[int, dict] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if isinstance(index, int) and 0 <= index < len(batch):
                by_index[index] = item

        results: list[EnrichedArticle] = []
        for idx, raw in enumerate(batch):
            model_item = by_index.get(idx, {})
            tags = model_item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            score = model_item.get("relevance_score")
            parsed_score: float | None = float(score) if isinstance(score, (int, float)) else None
            summary = model_item.get("summary_zh")
            results.append(
                EnrichedArticle(
                    raw=raw,
                    summary_zh=summary.strip() if isinstance(summary, str) and summary.strip() else None,
                    tags=[str(tag).strip() for tag in tags if str(tag).strip()][:5],
                    relevance_score=parsed_score,
                )
            )
        return results

    @staticmethod
    def _build_user_prompt(batch: list[RawArticle]) -> str:
        lines = ["请分析以下文章：", ""]
        for idx, item in enumerate(batch):
            lines.extend(
                [
                    f"[{idx}] 标题: {item.title}",
                    f"摘要: {item.snippet}",
                    f"来源: {item.source_name or item.source_type}",
                    "",
                ]
            )
        lines.append("请严格按 JSON 格式输出。")
        return "\n".join(lines)

    @staticmethod
    def _parse_model_json(raw_text: str) -> dict:
        text = raw_text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```json" in text:
            start = text.find("```json")
            end = text.find("```", start + 7)
            if start >= 0 and end > start:
                fenced = text[start + 7 : end].strip()
                return json.loads(fenced)

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])

        raise ValueError("model output is not valid JSON")
