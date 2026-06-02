# 结合知识库做内容输出 / 检索的提示词写法指南

> 给"以后要写一个结合 KB 的新 prompt / tool"时对照用。结合 omni 这套系统的**真实机制**
> （不是泛泛 RAG 教程）。写新 KB-prompt 前先扫一遍这份 + 看现成范例,**复用而非重写**。

---

## 0. 先分清两个阶段

"结合知识库做内容"其实是两个不同的 prompt 阶段,写法完全不同:

| 阶段 | 目的 | 重点 |
|---|---|---|
| **检索** | 找到对的料 | query 怎么写 + 选哪些 kb_role + 要不要开 HyDE/重排 |
| **生成** | 基于料输出 | KB 注入格式 + 反幻觉约束 + 来源标注 + 缺料降级 |

---

## 1. 系统机制速览(写 prompt 前必须知道的底层)

- **检索方式**：向量(pgvector cosine) + jieba 全文 双路 **RRF 融合**（`hybrid_search.py`），可选 HyPE。
- **chunk 自带来源头**：ingest 时每个 chunk 开头自动加 `[文档: X | 章节: Y > Z]`（`chunking.py add_contextual_headers`）。
  → **注入时让 LLM 引用这个头即可，不用你额外造来源标注。**
- **6 个 kb_role**：`authoritative`（权威/官方）/ `methodology`（方法论）/ `template`（模板框架）/
  `private_doc`（公司产品/历史 brief）/ `personal_log`（录音转写=摘要+引语，非原文）/ `general`。
- **agent 实际走的检索入口**：`search_kb` / `gather_brief_context` / `query_template_chunks`
  → 都调 `rag_chain.retrieve_multi_kb`（向量+全文 RRF + 配额融合 + 可选重排/HyDE/窗口扩展）。
- **改 prompt 三通道**（按改动大小选）：
  1. **永久**：改 `config/prompts/<tool>.{system,user}.md`（KE 不用重启，mtime 自检）
  2. **一次性**：塞 `extra_context` 参数（下次自动忘）
  3. **结构化补料**：塞 `kb_context` 参数（`gather_brief_context` 出，或手拼）

### 检索参数速查（默认值，`app/config.py`）

| 项 | 默认 |
|---|---|
| Embedding | `gemini-embedding-2-preview` |
| chunk_size / overlap | 768 / 128 字符 |
| 召回 top_k | 15（重排后留 8） |
| 重排模型 | `gemini-3.1-flash-lite-preview`（LLM 当交叉编码，0-10 打分） |
| 上下文窗口 | ±2 邻块 |
| score 阈值 | 0.25（agent 路默认传 0=不过滤） |

---

## 2. 检索阶段：怎么写 query / 选参数

你的检索是"向量 + jieba 全文双路"，query 要**同时照顾两路**：

| 要点 | 怎么做 | 为什么 |
|---|---|---|
| 用具体名词 + 同义词 | `"180天发酵 酱油 提鲜 不齁咸"`，别写"这产品好在哪" | 全文检索靠 jieba 切词命中，抽象问句切不出有用 token |
| 别塞超长 SKU 标题 | 用"辣酱油"而非完整 SEO 标题串 | 长串稀释向量，召回偏 |
| query 跟 KB 文风差太远 → 开 HyDE | `search_kb(query=..., use_hyde=True)` | query 短、KB 是长描述时，HyDE 先扩成假设答案再 embed，匹配长文准 |
| 按用途选 kb_role，别全库扫 | `kb_roles=["authoritative","methodology"]` | 全库扫慢 + 噪声 |
| top_k 别贪 | 8 够（默认已开重排，前几条才准） | 太多噪声 chunk 拉低输出 |

### kb_role 怎么选（按"我要这料干啥"）

- `authoritative` → **事实锚**（数据/结论从这取）
- `methodology` → **方法框架**（"怎么做"从这取）
- `template` → **结构参考**（借框架，**不借文案**）
- `private_doc` → 公司产品 / 历史 brief
- `personal_log` → 录音转写（存的是摘要+引语，不是原文）

### 检索增强开关（`search_kb` / `gather_brief_context`）

| 开关 | 何时开 | 代价 |
|---|---|---|
| `rerank`（交叉编码重排） | 默认开 | 整池 +1 次 LLM ≈ +2s；要极速可关 |
| `use_hyde` | query 抽象 / 跟文档风格差异大、召回不理想时开 | +1 次 LLM |
| `context_window`（±N 邻块） | chunk 被切碎、命中半段时开（`gather_brief_context` 默认开） | DB 查询，几乎无成本 |

---

## 3. 生成阶段：KB 注入格式（决定会不会幻觉）

### 标准注入模板（抄这个）

```
## 可用知识库材料（只能用这里的，没有的不许编）

### 【官方/权威】authoritative   ← 当事实锚
- [来源:5A资产分级 / 银发圈层] 银发人群调味品消费占比 35%...（score 0.82）
- [来源:...] ...

### 【方法论】methodology
- [来源:圈人SOP / RFM分层] ...

### 【模板/框架】template   ← 只借结构，不抄文案
- [来源:爆款拆解 / 痛点-解决-行动三段式] ...
```

**两条铁律**：
1. **按 kb_role 分区放**，别混成一锅 —— 明确告诉 LLM "authoritative 是事实、template 只借框架"，
   否则它会把模板里的示例文案当成你的产品事实抄出来。
2. **每条带 `[来源]` + score** —— 让 LLM 引用时能标、让你能验真假。chunk 本身带 `[文档:X|章节:Y]` 头，直接用。

### 原文照搬 vs 可改写

- 要 LLM **1:1 不改原文**（如人群画像）→ 学 `audience_match.system.md`：用 `>` 引用块包起来 +
  "逐字粘贴，删一个字算违规" + "超长(>500字)整段保留不许摘要"。
- 允许 LLM **基于料发挥**（如写脚本）→ 普通注入即可，但要求"每个结论能追溯到某条来源"。

---

## 4. 反幻觉三件套（任何 KB-输出 prompt 必带）

```
## 硬约束
1. 只用上面 KB 材料里的事实。KB 没有的（具体数字/资质/检测项）一律不编。
2. 每个关键结论后标来源：[KB:文档名] / [matrix X.Y] / [行业推理] 三选一。
   - [KB:xxx]   = KB 材料里有原文
   - [行业推理] = 基于品类常识推的（必须标，不能伪装成事实）
3. 缺料降级（别留空也别编）：
   - 有部分数字 → 只用有的，不为凑句式补想象的
   - 整条缺硬数据 → 用弱断言（"已做多项检测"而非"检测 18 项"）
   - 某段实在没料 → 写"（此处资料不足，建议补 X）"
4. 说人话，禁 AI 化套话（赋能/打通/闭环/抢占心智/匠心/一站式）。
```

> 反 AI 化词库已外置在 `config/prompts/anti_ai_voice.md`，新 prompt 开头引一句"遵守 anti_ai_voice 规范"即可，不用重抄。

---

## 5. 别重写——复用现成的

**现成范例（照抄对应模式）**：
- 注入 + 缺料降级 → `config/prompts/generate_brief.system.md`
- 1:1 原文不许改（最严搬运工） → `config/prompts/audience_match.system.md`
- 证据门控防凑数 → `config/prompts/selling_points_matrix.system.md`

**最省事的复用**：`gather_brief_context` tool 已经把"检索 3 类 KB + 分角色注入 + 标来源"
打包好了，直接拿它返的 `kb_context` 喂 `generate_brief`。
**做新内容输出前，先看能不能复用这个管线，而不是从零写检索。**

---

## 6. 可抄的"新 KB-内容 prompt"骨架

```
你是<角色>。基于下面 KB 材料做<任务>。

## 输入
- 任务对象：{sku / 主题}
- KB 材料（按角色分区，带来源）：{kb_context}
- 临时要求：{extra_context}

## 你只做 <X>，不做 <下游 Y>      ← 严格边界，防越界（学 audience_match）
## 输出结构：<固定 N 段>          ← 下游要解析就固定标题名
## 硬约束：反幻觉三件套（见第 4 节）  ← 来源标注 + 缺料降级 + 反 AI 化
## 输出前自检：<3-5 条清单>        ← 学 selling_points_matrix 的自检表
```

---

## 7. 常见错误（踩过的坑）

- ❌ 不传 `kb_context` 直接调 generate_brief → LLM 裸跑出空泛内容（W3a 已踩，feedback memory 强约束）
- ❌ template 模板文案当产品事实抄出来 → 注入时必须标"template 只借框架"
- ❌ query 塞超长 SEO 标题 → 召回偏，用品类短词
- ❌ 缺料时 LLM 用套话把空洞填满 → 必须给降级策略（弱断言 / 标"资料不足"）
- ❌ 自己造来源标注 → chunk 自带 `[文档:X|章节:Y]` 头，用它就行
