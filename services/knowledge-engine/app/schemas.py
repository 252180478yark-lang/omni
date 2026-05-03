from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


# ═══ Knowledge Base ═══

# kb_role 枚举：与数据库 CHECK 约束保持同步（migration 014）
KB_ROLE_VALUES = (
    "authoritative",  # 官方文档（千川/云图等）—— 严格引用
    "methodology",    # 方法论（管理/心理/易经）—— 借框架不引事实
    "personal_log",   # 个人录音转写 —— 摘要式入库
    "template",       # 素材模板 —— 按结构标签检索
    "private_doc",    # 公司文档（历史/奖项/产品介绍）—— 标准 RAG
    "general",        # 兜底
)
KbRole = Literal[
    "authoritative",
    "methodology",
    "personal_log",
    "template",
    "private_doc",
    "general",
]


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    embedding_provider: str | None = None
    embedding_model: str | None = None
    dimension: int | None = Field(default=None, gt=0)
    kb_role: KbRole = "general"


class KnowledgeBaseUpdateRequest(BaseModel):
    kb_role: KbRole


# ═══ Ingestion ═══

class IngestRequest(BaseModel):
    kb_id: str
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_url: str | None = None
    source_type: str = "manual"
    metadata: dict = Field(default_factory=dict)
    skip_chunking: bool = False


# ═══ Query / Search ═══

class QueryRequest(BaseModel):
    kb_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    kb_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=100)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    search_type: str = Field(default="hybrid", pattern="^(vector|fulltext|hybrid)$")
    filter_source_type: str | None = None
    filter_tags: list[str] | None = None


# ═══ RAG ═══

class RAGRequest(BaseModel):
    kb_id: str = ""
    kb_ids: list[str] | None = None
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    model: str | None = None
    provider: str | None = None
    stream: bool = False
    session_id: str | None = None
    # 目标字数（字符数，含中文）；>0 时自动多轮调用模型续写直至接近目标或达到轮次上限
    target_chars: int | None = Field(default=None, ge=0, le=500_000)
    continue_max_rounds: int | None = Field(default=None, ge=1, le=100)
    # SP9 Persona: injected before RAG system prompt in knowledge-engine
    persona_prompt: str | None = None

    def resolved_kb_ids(self) -> list[str]:
        """Return deduplicated list of KB IDs (kb_ids takes priority over kb_id)."""
        if self.kb_ids:
            return list(dict.fromkeys(self.kb_ids))
        if self.kb_id:
            return [self.kb_id]
        return []


# ═══ Response Models ═══

class QueryResult(BaseModel):
    id: str
    title: str | None = None
    content: str
    source_url: str | None = None
    score: float = 0.0
    search_source: str = "hybrid"


class DocumentDetail(BaseModel):
    id: str
    kb_id: str
    title: str
    source_url: str | None = None
    source_type: str = "manual"
    raw_text: str = ""
    chunk_count: int = 0


# ═══ Accounting (migration 015) ═══

# 与 DB CHECK 约束保持同步
COST_CATEGORY_VALUES = ("product", "logistics", "partner_quote")
CostCategory = Literal["product", "logistics", "partner_quote"]


class CostItemCreateRequest(BaseModel):
    sku_id: str | None = None
    category: CostCategory
    item_name: str = Field(min_length=1, max_length=200)
    unit_cost: float = Field(ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    unit: str = Field(default="件", min_length=1, max_length=20)
    quantity_per_unit: float = Field(default=1.0, gt=0)
    vendor: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str | None = None


class CostItemUpdateRequest(BaseModel):
    sku_id: str | None = None
    category: CostCategory | None = None
    item_name: str | None = Field(default=None, min_length=1, max_length=200)
    unit_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity_per_unit: float | None = Field(default=None, gt=0)
    vendor: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    is_active: bool | None = None
    notes: str | None = None


class MarginRequest(BaseModel):
    """计算 SKU 的净利率（按当前有效成本）。"""
    sku_id: str = Field(min_length=1)
    sale_price: float = Field(gt=0)
    quantity: float = Field(default=1.0, gt=0, description="售卖件数（用于均摊固定成本）")
    platform_fee_rate: float = Field(default=0.0, ge=0, le=1, description="平台佣金率 0.05=5%")
    include_shared_logistics: bool = Field(default=True, description="是否纳入未绑定 SKU 的共享物流成本")


class CostNLQueryRequest(BaseModel):
    """自然语言查询成本（"这款产品净利率多少" → LLM 翻译为结构化）。"""
    query: str = Field(min_length=1)
    sku_id: str | None = Field(default=None, description="若上下文已知 SKU 可传入，省一次 LLM 推理")
    sale_price: float | None = Field(default=None, gt=0)
    model: str | None = None


class CostItemBulkCreateRequest(BaseModel):
    """批量创建（前端预览编辑后的最终列表）."""
    items: list[CostItemCreateRequest] = Field(min_length=1, max_length=500)


# ═══ Harvester ═══

class HarvesterChapter(BaseModel):
    index: int = 0
    title: str = ""
    graph_path: str = ""
    markdown: str = ""
    word_count: int = 0
    block_count: int = 0
    source_url: str | None = None
    error: str | None = None
