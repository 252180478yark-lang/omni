"""knowledge-engine 侧 prompt 共用常量。

跨 Content Studio / Briefs / Digital Humans / RAG 等模块共享，
保证 AI 腔禁用词、JSON 输出纪律、人物一致性要求等约束措辞统一。
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════
# AI 腔禁用词 — 文案 / 脚本 / Brief 通用
# ═══════════════════════════════════════════════════════════

NO_AI_SLANG = """## 语言纪律（必须遵守）

- **禁用 AI 腔词汇**：焕新、赋能、匠心、臻选、臻享、致敬、绽放、蜕变、沉淀、解锁、开启新篇章、邂逅美好、品味非凡、匠人精神、致力于、精心打造、倾力呈献、一键开启。
- **禁用空洞形容词套路**：极致 XX、一站式 XX、全方位 XX、沉浸式 XX、颠覆性 XX、突破性 XX、革命性 XX。
- **要人话**：像朋友当面推荐一样说，有细节、有体验、有具体数字或场景，不要总结陈词。
- **允许**：口语化表达、第一人称经历、具体数字、场景化描述、反问、感叹。"""


# ═══════════════════════════════════════════════════════════
# JSON 输出纪律 — 所有要求 LLM 返回 JSON 的地方
# ═══════════════════════════════════════════════════════════

JSON_OUTPUT_DISCIPLINE = """## JSON 输出纪律
- 直接输出合法 JSON，不要加前缀说明、不要 markdown 代码块包裹、不要注释。
- 字符串值内的双引号必须转义为 `\\"`。
- 如果某字段在输入中没有依据，写 `null` 而不是编造值；禁止用占位符（如 "待定""TBD"）。"""


# ═══════════════════════════════════════════════════════════
# 人物 / 产品一致性锚定 — 图像 / 视频 prompt 翻译器共用
# ═══════════════════════════════════════════════════════════

CONSISTENCY_ANCHOR_RULE = """## 一致性锚定规则（跨场景硬约束）
- 同一人物在所有场景中的外貌描述必须使用**完全相同的英文词组**（锚定一致性）。一旦选定例如 "a young asian woman with shoulder-length black hair, round face"，后续所有场景不得改写为同义表述。
- 同一产品在所有场景中的外观描述必须使用**完全相同的英文词组**（形状、颜色、logo 位置、材质、包装细节）。
- 若参考图不足以支撑某个细节，宁可简化描述，也不得生造细节造成跨场景漂移。"""


# ═══════════════════════════════════════════════════════════
# 知识库使用规则 — 按"知识库在任务中扮演的角色"分 4 种
# ═══════════════════════════════════════════════════════════
#
# 选用指南：
#   A. KB_AS_SOLE_SOURCE     —— 问答/RAG，知识库是唯一事实源
#   B. KB_AS_SUPPORT         —— 诊断/分析，输入数据是主体,知识库辅助
#   C. KB_AS_CREATIVE_MATERIAL — 创作（文案/Brief/脚本），知识库提供素材
#   D. KB_AS_STYLE_SAMPLE    —— 风格样本（few-shot 口播示例等）
#
# 引用格式：统一使用 [KB:{source}#{id}]，与 format_kb_snippets() 输出对齐。
# ═══════════════════════════════════════════════════════════

KB_AS_SOLE_SOURCE = """## 知识库使用规则（角色：唯一事实源）

1. **本次 `<kb_context>` 中的资料是回答的唯一事实依据**。离开它不能提供具体事实（数字、政策、人名、产品参数、操作路径）。
2. **允许**用你的常识做"分析框架"（如"可从 X/Y/Z 三个角度看"），**不允许**用常识补充具体事实。
3. **引用格式**：每个事实性结论后必须标 `[KB:{source}#{id}]`。综合多条来源时全部列出：`[KB:doc1#3][KB:doc2#1]`。
4. **缺失处置**：若资料不足以回答，先明确声明"知识库中没有直接依据"；再按需给出通用建议，这部分**必须单独起段**并加前缀"【知识库未覆盖，通用经验】"。
5. **冲突处置**：若多条资料互相矛盾，列出两种说法并标来源，请用户决定，不要自行仲裁。"""


KB_AS_SUPPORT = """## 知识库使用规则（角色：辅助参考）

1. **证据权重**：用户输入的数据（指标、视频分析、产品信息）>> 知识库内容 >> 你的常识。
2. **知识库不得推翻数据**：若知识库经验与输入数据冲突，以数据为准。写法："数据呈现 A；知识库经验是 B；可能原因：……"。
3. **引用格式**：
   - 引用知识库：`[KB:{source}#{id}]`
   - 引用输入数据：用字段名，如 `(依据：CTR=2.1%, CVR=0.3%)`
   - 自己的推断：`（推断：基于 XX 逻辑）`
4. **缺失处置**：若知识库无召回，直接忽略这部分，不需专门声明（输入数据已足够支撑分析）。"""


KB_AS_CREATIVE_MATERIAL = """## 知识库使用规则（角色：创作素材）

1. **产品/输入信息是硬事实**，不得违反（产品名、价格、成分、卖点）。
2. **知识库素材**用来提示"怎么写、写什么"——人群洞察、场景线索、钩子参考、历史经验。综合使用，不要原样复读。
3. **evidence 字段必填**（≥ 10 字），三选一格式：
   - `来自 [KB:{source}#{id}]`
   - `来自 [USER_INPUT:字段名]`
   - `推断（依据：XX 品类常识 / 资料中的 XX 线索）`
4. **缺失处置**：若知识库无召回，evidence 全部写"推断（依据：...）"，并在输出开头加一行"⚠️ 知识库未提供有效召回，以下内容基于通用品类常识"。
5. **禁止编造**：产品参数、竞品数据、历史投放指标——若素材与产品信息都没有，不得凭空生造具体数字。"""


KB_AS_STYLE_SAMPLE = """## 风格样本使用规则（素材角色：语感参考，不是事实）

1. 下方 `<style_samples>` 只是**语气/句长/节奏/用词习惯**的模仿样本。
2. **禁止抄袭其内容**——产品名、场景、具体数字、卖点一概不得照搬。
3. **禁止当作事实引用**——不要在输出中引用这些样本的内容作依据。
4. 它只影响"怎么说"，不影响"说什么"。"""


# ═══════════════════════════════════════════════════════════
# 知识库片段渲染器 — 所有节点共用
# ═══════════════════════════════════════════════════════════

def format_kb_snippets(snippets: list[dict]) -> str:
    """把检索结果渲染为统一的 XML <kb_context> 段。

    入参格式（兼容 retrieve_only 返回 + 简化版）：
      {"source": "ocean_engine", "id": "chunk_id", "content": "...",
       "score": 0.87, "title": "..."}
      或原始 chunk：
      {"id": "chunk_uuid", "content": "...", "score": 0.87, "title": "..."}

    输出示例：
      <kb_context>
        <snippet source="ocean_engine" id="2" score="0.87">...</snippet>
        <snippet source="audience_report" id="1" score="0.71">...</snippet>
      </kb_context>

    空输入时返回明确的"无召回"标记，让 LLM 知道本次没检索到资料。
    """
    if not snippets:
        return '<kb_context empty="true" note="本次检索无召回结果" />'

    lines = ["<kb_context>"]
    for i, s in enumerate(snippets, start=1):
        source = s.get("source") or s.get("kb_name") or "unknown"
        snippet_id = str(s.get("id") or s.get("chunk_id") or i)
        score = float(s.get("score") or 0)
        content = (s.get("content") or "").strip()
        if not content:
            continue
        # XML 转义最小集（避免 < > & 打断标签）
        content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(
            f'  <snippet source="{source}" id="{snippet_id}" score="{score:.2f}">\n'
            f'    {content}\n'
            f'  </snippet>'
        )
    lines.append("</kb_context>")
    return "\n".join(lines)


def format_style_samples(samples: list[str]) -> str:
    """把语感样本渲染为 <style_samples> 段（不带引用 ID，因为不引用）。"""
    if not samples:
        return ""
    lines = ["<style_samples>"]
    for i, text in enumerate(samples, start=1):
        text = (text or "").strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if not text:
            continue
        lines.append(f'  <sample id="{i}">\n    {text}\n  </sample>')
    lines.append("</style_samples>")
    return "\n".join(lines)
