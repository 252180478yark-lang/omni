# W3c 实施计划：summarize_text + parse_long_doc_with_gemini + query_template_chunks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 omni MCP server 加 3 个通用专家 tool（文本摘要 / 长文档解析 / 模板素材检索），doctor 升 20 → 23。

**Architecture:** 全部 F 类（require_approval=False）。复用 W3a/W3b 全部基建（prompts 外置 / ai_hub_client / hybrid_search / document_parser / tool_with_audit）。query_template_chunks 设计为 hybrid_search 的"模板 KB 专用 alias"——按 query 检索 template KB + post-filter source_type。

**Tech Stack:** FastMCP 3.x · asyncpg · pytest-asyncio · ai_hub_client · hybrid_search.py · document_parser.py · embedding_client.py · prompts.py（mtime cache）

---

## 起手就要看的文件（implementer 必读）

- **design doc**：`docs/superpowers/specs/2026-05-03-omni-agent-uplift-design.md` §3.2 W3 行 line 475-477（summarize_text / parse_long_doc / query_template_chunks）
- **memory 进度**：`C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` §十九 W3b 落地 + §二 W3c 入口
- **W3b plan 范本**：`docs/superpowers/plans/2026-05-05-omni-agent-uplift-W3b-plan.md`
- **W3a/W3b 已用基建**：
  - `app/mcp/audit.py` — `tool_with_audit` 装饰器
  - `app/mcp/prompts.py` — load/render（mtime cache）
  - `app/mcp/trace.py` — `build_trace(model, params, prompt, cost)`
  - `app/services/ai_hub_client.py` — chat/image/video 统一入口
  - `app/services/hybrid_search.py` — `hybrid_search(kb_id, query, query_embedding, top_k)`
  - `app/services/embedding_client.py` — `embed_texts(texts, model, provider)`
  - `app/services/document_parser.py` — `extract_text(content: bytes, filename: str) -> str`
  - `app/services/ingestion.py` — `list_kbs() / get_kb(kb_id)`
- **prompt 外置目录**：`config/prompts/` 当前 8 个模板（anti_ai_voice / generate_brief.{system,user} / compute_margin.{system,user} / channel_profiles/{douyin,tmall,jd}）

---

## 关键决策（已锁定，禁止再讨论）

1. **3 tool 全部 F 类**（require_approval=False，纯查询/生成/解析，可逆）
2. **每 tool 必返 trace 字段**（model/params/cost_estimate）
3. **summarize_text / parse_long_doc 走 ai_hub_client.chat**，model 通过 tool_models.yaml 配置（plan 默认值见各 task）
4. **prompt 外置**：summarize_text / parse_long_doc 各 1 套（system + user），生成时 mtime 自检 hot reload
5. **query_template_chunks 设计 = hybrid_search 包装 + source_type post-filter**：默认 source_type='livestream-analysis'，默认 kb_role='template'（多 KB 时合并 top_k）
6. **复用 W3a/W3b 全部基建**：禁止新建 chat 客户端 / 新 hybrid 实现 / 新 prompt 加载器
7. **个人自用**，禁止过度工程：不写微服务 / SLA / 分布式
8. **doctor expected_tools 20 → 23**
9. **enforce_human_voice=True 仅给 summarize_text**（默认）；parse_long_doc 是结构化解析不要文风干扰，关掉

---

## 文件结构

### 待建（1 个）
- `services/knowledge-engine/app/mcp/tools/general.py` — 3 个 W3c tool 集中（~250 行）

### 待新增 prompts（4 个 .md）
- `config/prompts/summarize_text.system.md`
- `config/prompts/summarize_text.user.md`
- `config/prompts/parse_long_doc.system.md`
- `config/prompts/parse_long_doc.user.md`

### 待改（3 个）
- `services/knowledge-engine/app/mcp/server.py` — `import general as _general`（+1 行）
- `services/knowledge-engine/app/mcp/doctor.py` — `_EXPECTED_TOOLS` 加 3 名（+3 行）+ wanted 集合扩到 23
- `services/knowledge-engine/app/mcp/tools/__init__.py` — docstring 加 W3c 段（+~5 行）
- `services/knowledge-engine/config/tool_models.yaml` — 加 keyed override（+~10 行）

### 待建测试（1 个）
- `services/knowledge-engine/tests/test_mcp_general.py` — 3 tool 测试（~250 行）

---

## 已知坑（W3a/W3b 期间踩的，防重踩）

1. **fixture sync 写法跑不通**：用 `@pytest_asyncio.fixture(scope="module", autouse=True)` async 写法
2. **PowerShell 5.1 `\"` 不是合法转义**：容器内调 `docker exec ... bash -c "..."` 包装跑容器内 bash，禁止 host 嵌套引号
3. **pytest 命令必须带 PYTHONPATH + cwd**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/... -v"`
4. **bind mount 改 docker-compose 后必须 `up -d --no-deps --force-recreate`**：但 W3c 仅改 .py / .md，restart 即可
5. **测试 vs 实现 name 冲突**：测试的字段名（如 `query`）跟函数 positional arg 重名时，函数签名加 `/` posonly 标记
6. **plan 字面 vs 实测偏差**：W3b 撞过 `_SHOP_` sentinel。**implementer 跑测试前先 SELECT 抽样看实际数据结构**（query_template_chunks 看 metadata 真值）
7. **hub /chat 响应结构**：`{"content": str, "provider": str, "model": str, "usage": {...}}`，**不是 OpenAI ChatCompletion 风格**
8. **doctor 用 wanted-only check**：T4 改 `_EXPECTED_TOOLS` 列表 + `wanted` 集合（doctor.py 内同步）
9. **ai_hub_client.chat 默认 anthropic**：但项目 anthropic 是 Claude Code Max 订阅 ≠ API key，**chat 必须显式 `provider='gemini'` 或 yaml 默认改**。tool_models.yaml W3c 默认走 gemini。
10. **pdf 抽取走 PyMuPDF (fitz)**：document_parser._extract_pdf 已用 fitz，不要再装新库
11. **embed_texts 需要 model + provider**：从 KB row 取，不要硬编码

---

## 任务总览（5 task）

| Task | 名称 | 类型 | 估时 |
|---|---|---|---|
| T1 | summarize_text | F LLM | 60 min |
| T2 | parse_long_doc_with_gemini | F LLM + 文件 | 75 min |
| T3 | query_template_chunks | F KB 检索 | 60 min |
| T4 | doctor expected_tools=23 + tools/__init__.py + tool_models.yaml | chore | 15 min |
| T5 | e2e 容器内自检 + 老板侧 grant 累积清单 | chore | 30 min |

总计：5 task / ~4 小时落地（subagent-driven 模式）。

---

## Task 1: summarize_text

**Goal:** 海量文本摘要 tool。接受任意文本 + 可选 instruction，调 chat（默认 gemini-3-flash-preview，prompt 外置 + enforce_human_voice），返回摘要。

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/general.py`
- Create: `services/knowledge-engine/config/prompts/summarize_text.system.md`
- Create: `services/knowledge-engine/config/prompts/summarize_text.user.md`
- Create: `services/knowledge-engine/tests/test_mcp_general.py`

**接口约定**：

```python
async def summarize_text(
    text: str,
    instruction: str | None = None,
    max_input_chars: int = 30000,
) -> dict:
    """对一段文本出摘要。

    Args:
        text: 待摘要文本（utf-8 字符串）
        instruction: 可选方向指引（如"只关注价格信息"、"按章节分点"）
        max_input_chars: 单次输入字符上限，超过截断

    Returns:
        {ok: True, result: {summary, length_in, length_out, truncated}, trace}

    错误：
        - text 为空或全空白 → {ok: False, error: "empty_text"}
        - LLM 调用失败 → {ok: False, error: "llm_call_failed", hint: "..."}
    """
```

- [ ] **Step 1: 写 prompt 模板**

写入 `services/knowledge-engine/config/prompts/summarize_text.system.md`：

```markdown
你是一个文本摘要助手。你的任务是把用户给的文本浓缩成精炼摘要。

要求：
1. 只用文本中已有的信息，不补充外部知识，不推测
2. 保留具体数字、人名、地点等关键事实
3. 删除套话、重复、铺垫，直接说重点
4. 如果用户给了 instruction，按 instruction 的方向重组
5. 摘要长度按文本量动态：≤500 字给 50 字以内，500-3000 字给 100-200 字，3000+ 字给 300-500 字
6. 输出只给摘要正文，不要"以下是摘要："这种导言

如果文本里有冲突信息，列出所有版本，标注"原文有 X 处出入"。
```

写入 `services/knowledge-engine/config/prompts/summarize_text.user.md`：

```markdown
{instruction_block}

待摘要文本：
{text}
```

- [ ] **Step 2: 写 failing test**

写入 `services/knowledge-engine/tests/test_mcp_general.py`：

```python
"""W3c: general 3 tool 测试。"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools.general import summarize_text


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_summarize_text_empty():
    """空文本 → empty_text 错误。"""
    result = await summarize_text(text="")
    assert result["ok"] is False
    assert result["error"] == "empty_text"


@pytest.mark.asyncio
async def test_summarize_text_whitespace():
    """全空白 → empty_text 错误。"""
    result = await summarize_text(text="   \n\t  ")
    assert result["ok"] is False
    assert result["error"] == "empty_text"


@pytest.mark.asyncio
async def test_summarize_text_basic():
    """普通文本应返回非空摘要。"""
    text = (
        "今天天气不错，我去市场买了 3 斤苹果，每斤 5 块钱共 15 元。"
        "苹果是红富士品牌，老板说今年果园丰收所以便宜。"
        "回家路上下雨了，没带伞，淋了一身。"
    )
    result = await summarize_text(text=text)
    assert result["ok"] is True
    summary = result["result"]["summary"]
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert result["result"]["length_in"] == len(text)
    assert result["result"]["length_out"] == len(summary)
    assert result["result"]["truncated"] is False
    # trace 字段必备
    assert "model" in result["trace"]
    assert "provider" in result["trace"]


@pytest.mark.asyncio
async def test_summarize_text_with_instruction():
    """带 instruction 时摘要应按方向走（不验内容，仅验流程跑通）。"""
    text = "苹果 5 块, 香蕉 3 块, 梨 4 块, 三种水果共 12 块。"
    result = await summarize_text(
        text=text,
        instruction="只列出水果名称，不要价格",
    )
    assert result["ok"] is True
    summary = result["result"]["summary"]
    assert len(summary) > 0


@pytest.mark.asyncio
async def test_summarize_text_truncation():
    """超长文本应被截断 + truncated=True。"""
    long_text = "测试 " * 20000  # 60000 字符
    result = await summarize_text(text=long_text, max_input_chars=1000)
    assert result["ok"] is True
    assert result["result"]["truncated"] is True
    # length_in 是原始长度，截断后实际送给 LLM 的是 max_input_chars
    assert result["result"]["length_in"] == len(long_text)
```

- [ ] **Step 3: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_general.py -v -k summarize"
```

期望：`ImportError: cannot import name 'summarize_text' from 'app.mcp.tools.general'`

- [ ] **Step 4: 写实现**

写入 `services/knowledge-engine/app/mcp/tools/general.py`：

```python
"""W3c: 3 个通用专家 tool。

- summarize_text(text, instruction?) — 文本摘要
- parse_long_doc_with_gemini(file_path, instruction?) — 长文档解析
- query_template_chunks(query, kb_id?, source_type?, top_k?) — 模板素材检索
"""
from __future__ import annotations

import logging
from typing import Any

from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import resolve_model
from app.mcp.server import mcp
from app.mcp.trace import build_trace
from app.services.ai_hub_client import AIHubClient

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def summarize_text(
    text: str,
    instruction: str | None = None,
    max_input_chars: int = 30000,
) -> dict:
    """对一段文本出摘要。

    Args:
        text: 待摘要文本
        instruction: 可选方向指引
        max_input_chars: 输入字符上限，超过截断

    Returns:
        {ok, result: {summary, length_in, length_out, truncated}, trace}
    """
    text = text or ""
    if not text.strip():
        return {
            "ok": False,
            "error": "empty_text",
            "hint": "text 不能为空或纯空白",
        }

    length_in = len(text)
    truncated = length_in > max_input_chars
    text_for_llm = text[:max_input_chars] if truncated else text

    instruction_block = (
        f"额外要求：{instruction}\n" if (instruction and instruction.strip()) else ""
    )

    system_prompt = prompts.load("summarize_text.system")
    user_prompt = prompts.render(
        "summarize_text.user",
        instruction_block=instruction_block,
        text=text_for_llm,
    )

    cfg = resolve_model("summarize_text")
    client = AIHubClient()
    try:
        resp = await client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=cfg["provider"],
            model=cfg["model"],
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 2048),
            enforce_human_voice=True,
        )
    except Exception as exc:
        logger.exception("summarize_text chat failed")
        return {
            "ok": False,
            "error": "llm_call_failed",
            "hint": f"ai-hub /chat 调用失败: {exc}",
        }

    summary = (resp.get("content") or "").strip()
    return {
        "ok": True,
        "result": {
            "summary": summary,
            "length_in": length_in,
            "length_out": len(summary),
            "truncated": truncated,
        },
        "trace": build_trace(
            model=resp.get("model") or cfg["model"],
            provider=resp.get("provider") or cfg["provider"],
            params={
                "temperature": cfg.get("temperature", 0.3),
                "max_tokens": cfg.get("max_tokens", 2048),
                "input_chars": len(text_for_llm),
            },
            final_prompt=f"[system]\n{system_prompt}\n\n[user]\n{user_prompt[:500]}...",
            cost=resp.get("usage"),
        ),
    }
```

- [ ] **Step 5: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_general.py -v -k summarize"
```

期望：5 个测试全 PASS（empty / whitespace / basic / with_instruction / truncation）。

如果 LLM 调用失败：检查 ai-provider-hub 容器是否 Up + tool_models.yaml summarize_text 默认 provider/model 是否正确（T4 配，但 T1 期间可能撞 anthropic 没 key）。

T1 实施期间如果发现 yaml 还没 summarize_text 配置导致 resolve_model 走 `__default__`（anthropic），需要先在 yaml 加：

```yaml
summarize_text:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.3
  max_tokens: 2048
```

（这步在 T4 集中改 yaml，T1 实施期间临时加 OK，不要 commit；T4 commit 时一起 add）

- [ ] **Step 6: 注册到 server.py**

修改 `services/knowledge-engine/app/mcp/server.py`，加 import：

```python
from app.mcp.tools import general as _general  # noqa: E402, F401  # W3c T1+
```

放在 W3b 的 `from app.mcp.tools import scout as _scout  # ...` 后面。

KE 容器需要 restart：

```bash
docker restart omni-knowledge-engine
```

等 5 秒后跑 doctor（doctor 期望 20 → 报 21 mismatch，预期）：

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

- [ ] **Step 7: commit**

```bash
git add services/knowledge-engine/app/mcp/tools/general.py services/knowledge-engine/tests/test_mcp_general.py services/knowledge-engine/config/prompts/summarize_text.system.md services/knowledge-engine/config/prompts/summarize_text.user.md services/knowledge-engine/app/mcp/server.py
git commit -m "$(cat <<'EOF'
feat(mcp): summarize_text 文本摘要 tool (W3c T1)

W3c 第 1 个 tool。F 类 require_approval=False。接受任意文本 +
可选 instruction，调 ai_hub_client.chat（默认 gemini-3-flash-preview，
yaml 可调）+ enforce_human_voice。

prompt 外置：config/prompts/summarize_text.{system,user}.md。

支持长文截断（max_input_chars 默认 30k）+ truncated 字段提醒。

测试 5 case：空 / 全空白 / 基础 / 带 instruction / 超长截断。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- `prompts.render(name, **ctx)` 内部用 `str.format`，{instruction_block} / {text} 占位必须传 keyword 参数
- summary = resp.get("content") 而不是 resp["choices"][0]["message"]["content"]（hub 不是 OpenAI 兼容格式）
- length_in 是**原始**输入长度，length_out 是摘要长度；truncated 仅当 length_in > max_input_chars
- enforce_human_voice=True 让 ai_hub_client 自动在 system 头拼 ANTI_AI_HUMAN_VOICE

---

## Task 2: parse_long_doc_with_gemini

**Goal:** 200 页+ PDF / DOCX 长文档解析 tool。读文件 → document_parser.extract_text 出 raw text → 调 chat（默认 gemini-2.5-flash，1M context）出结构化大纲 + 关键章节。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/general.py`（追加新函数）
- Create: `services/knowledge-engine/config/prompts/parse_long_doc.system.md`
- Create: `services/knowledge-engine/config/prompts/parse_long_doc.user.md`
- Modify: `services/knowledge-engine/tests/test_mcp_general.py`（追加新测试）

**接口约定**：

```python
async def parse_long_doc_with_gemini(
    file_path: str,
    instruction: str | None = None,
    max_input_chars: int = 800000,
) -> dict:
    """长文档解析 tool。

    Args:
        file_path: 文件绝对路径（容器内可访问）
        instruction: 可选方向指引（如"重点抽出人群定位段落"）
        max_input_chars: 输入字符上限（gemini-2.5-flash 1M context，留余量）

    Returns:
        {ok, result: {markdown_outline, length_in, length_out, source_type, truncated}, trace}

    错误：
        - file_not_found / is_directory / extract_failed / llm_call_failed
    """
```

- [ ] **Step 1: 写 prompt 模板**

写入 `services/knowledge-engine/config/prompts/parse_long_doc.system.md`：

```markdown
你是一个长文档结构化分析助手。任务是把用户给的长文本（可能是 PDF / DOCX 抽取出的几十页内容）整理成结构化 markdown 大纲。

要求：
1. 只用文本中已有的信息，绝不补充外部知识、绝不推测
2. 输出 markdown 结构：## 一级章节 / ### 二级 / 列表 / 关键引语用 > 引用块
3. 关键数据、人名、产品名、年份等具体事实保留原文表述（**加粗**）
4. 章节顺序按原文出现顺序，不重排
5. 如果用户给了 instruction，按 instruction 重点抽取相关章节，其他段落简略
6. 输出只给 markdown 正文，不要"以下是大纲："这种导言
7. 文档冲突信息列出所有版本，标"原文 P.x 与 P.y 不一致"

不要省略数字（"约 50%"不要简化为"接近一半"）。
```

写入 `services/knowledge-engine/config/prompts/parse_long_doc.user.md`：

```markdown
{instruction_block}

文档原文（{source_type} 抽取，{length_in} 字符）：

{text}
```

- [ ] **Step 2: 写 failing test（追加到 test_mcp_general.py）**

更新 import：

```python
from app.mcp.tools.general import summarize_text, parse_long_doc_with_gemini
```

追加测试：

```python
@pytest.mark.asyncio
async def test_parse_long_doc_file_not_found():
    """文件不存在 → file_not_found。"""
    result = await parse_long_doc_with_gemini(file_path="/nonexistent/path.pdf")
    assert result["ok"] is False
    assert result["error"] == "file_not_found"


@pytest.mark.asyncio
async def test_parse_long_doc_is_directory():
    """传目录 → is_directory。"""
    result = await parse_long_doc_with_gemini(file_path="/tmp")
    assert result["ok"] is False
    assert result["error"] == "is_directory"


@pytest.mark.asyncio
async def test_parse_long_doc_basic_txt():
    """普通 .txt 文件应解析成功。"""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write(
            "## 第一章 产品概况\n这是一段产品描述。营收 1000 万。\n\n"
            "## 第二章 用户画像\n核心用户 25-35 岁女性。\n"
        )
        tmp = f.name

    try:
        result = await parse_long_doc_with_gemini(file_path=tmp)
        assert result["ok"] is True
        outline = result["result"]["markdown_outline"]
        assert isinstance(outline, str)
        assert len(outline) > 0
        assert result["result"]["source_type"] == "text"
        assert result["result"]["truncated"] is False
        assert "model" in result["trace"]
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_parse_long_doc_with_instruction():
    """带 instruction 应正常返回（不验内容，仅验流程跑通）。"""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
        f.write("# 标题\n卖点 1: 价格便宜\n卖点 2: 质量好\n卖点 3: 配送快\n")
        tmp = f.name

    try:
        result = await parse_long_doc_with_gemini(
            file_path=tmp,
            instruction="只抽取卖点列表",
        )
        assert result["ok"] is True
        assert len(result["result"]["markdown_outline"]) > 0
    finally:
        os.unlink(tmp)
```

- [ ] **Step 3: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_general.py -v -k parse_long"
```

期望：`ImportError: cannot import name 'parse_long_doc_with_gemini'`

- [ ] **Step 4: 写实现（追加到 general.py）**

```python
import os

from app.services.document_parser import extract_text, detect_content_type


@tool_with_audit(mcp, require_approval=False)
async def parse_long_doc_with_gemini(
    file_path: str,
    instruction: str | None = None,
    max_input_chars: int = 800000,
) -> dict:
    """长文档（PDF / DOCX / TXT 等）结构化解析 tool。

    内部走 document_parser.extract_text → chat (gemini-2.5-flash by default)。
    支持的文件类型：text / markdown / pdf / docx / html / srt / csv / xlsx。

    Args:
        file_path: 文件绝对路径（容器内可访问）
        instruction: 可选方向指引
        max_input_chars: 输入字符上限（默认 800k，留余量给 1M context）

    Returns:
        {ok, result: {markdown_outline, length_in, length_out, source_type, truncated}, trace}
    """
    if not os.path.exists(file_path):
        return {
            "ok": False,
            "error": "file_not_found",
            "hint": f"file_path={file_path} 容器内不存在；确认 bind mount 路径",
        }
    if os.path.isdir(file_path):
        return {
            "ok": False,
            "error": "is_directory",
            "hint": f"file_path={file_path} 是目录不是文件",
        }

    try:
        with open(file_path, "rb") as f:
            content = f.read()
        filename = os.path.basename(file_path)
        text = extract_text(content, filename)
    except Exception as exc:
        logger.exception("parse_long_doc extract failed for %s", file_path)
        return {
            "ok": False,
            "error": "extract_failed",
            "hint": f"document_parser 抽取失败: {exc}",
        }

    text = (text or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "empty_extracted",
            "hint": f"file_path={file_path} 抽取后为空（图片型 PDF？老板用 OCR 工具先转）",
        }

    source_type = detect_content_type(filename)
    length_in = len(text)
    truncated = length_in > max_input_chars
    text_for_llm = text[:max_input_chars] if truncated else text

    instruction_block = (
        f"额外要求：{instruction}\n" if (instruction and instruction.strip()) else ""
    )

    system_prompt = prompts.load("parse_long_doc.system")
    user_prompt = prompts.render(
        "parse_long_doc.user",
        instruction_block=instruction_block,
        source_type=source_type,
        length_in=length_in,
        text=text_for_llm,
    )

    cfg = resolve_model("parse_long_doc_with_gemini")
    client = AIHubClient()
    try:
        resp = await client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=cfg["provider"],
            model=cfg["model"],
            temperature=cfg.get("temperature", 0.2),
            max_tokens=cfg.get("max_tokens", 8192),
            enforce_human_voice=False,  # 结构化解析不要文风干扰
        )
    except Exception as exc:
        logger.exception("parse_long_doc chat failed")
        return {
            "ok": False,
            "error": "llm_call_failed",
            "hint": f"ai-hub /chat 调用失败: {exc}",
        }

    outline = (resp.get("content") or "").strip()
    return {
        "ok": True,
        "result": {
            "markdown_outline": outline,
            "length_in": length_in,
            "length_out": len(outline),
            "source_type": source_type,
            "truncated": truncated,
        },
        "trace": build_trace(
            model=resp.get("model") or cfg["model"],
            provider=resp.get("provider") or cfg["provider"],
            params={
                "temperature": cfg.get("temperature", 0.2),
                "max_tokens": cfg.get("max_tokens", 8192),
                "source_file": file_path,
                "source_type": source_type,
                "input_chars": len(text_for_llm),
            },
            final_prompt=f"[system]\n{system_prompt}\n\n[user]\n{user_prompt[:500]}...",
            cost=resp.get("usage"),
        ),
    }
```

注意：`resolve_model` 来自 `app.mcp.model_config`，T1 已 import；`detect_content_type` 来自 `app.services.document_parser`。

- [ ] **Step 5: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_general.py -v"
```

期望：9 个测试全 PASS（5 summarize + 4 parse_long_doc）。

T2 实施期间临时加 yaml（T4 commit 一起）：

```yaml
parse_long_doc_with_gemini:
  provider: gemini
  model: gemini-2.5-flash
  temperature: 0.2
  max_tokens: 8192
```

- [ ] **Step 6: KE restart + commit**

```bash
docker restart omni-knowledge-engine
git add services/knowledge-engine/app/mcp/tools/general.py services/knowledge-engine/tests/test_mcp_general.py services/knowledge-engine/config/prompts/parse_long_doc.system.md services/knowledge-engine/config/prompts/parse_long_doc.user.md
git commit -m "$(cat <<'EOF'
feat(mcp): parse_long_doc_with_gemini 长文档解析 tool (W3c T2)

W3c 第 2 个 tool。F 类。读文件 → document_parser.extract_text →
ai_hub_client.chat（默认 gemini-2.5-flash，1M context）出结构化
markdown 大纲。

支持文件类型（document_parser 已支持）：text / markdown / pdf / docx /
html / srt / csv / xlsx。

prompt 外置：config/prompts/parse_long_doc.{system,user}.md。
enforce_human_voice=False（结构化解析不要文风干扰）。

测试 4 case：file_not_found / is_directory / 基础 .txt / 带 instruction。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- 图片型 PDF 抽取后是空字符串，加 empty_extracted 错误（提醒老板先用 OCR）
- `extract_text(bytes, filename)` 是 sync 函数（不是 async）；签名传 bytes 不是 path
- `detect_content_type(filename)` 返回 "text"/"markdown"/"pdf"/"docx" 等，作为 trace 的 source_type 字段
- gemini-2.5-flash context 1M tokens ≈ 800k 字符；max_input_chars=800000 留余量给 system prompt
- enforce_human_voice=False —— 长文档抽取要"忠实原文结构"，跟"说人话"是冲突的（说人话适合摘要 / brief 类生成，不适合 OCR 风格的解析）

---

## Task 3: query_template_chunks

**Goal:** 模板素材检索 tool。从 kb_role='template' KB 里按 query 用 hybrid_search 检索，返回带 metadata 的 chunks（默认筛 source_type='livestream-analysis'）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/general.py`（追加新函数）
- Modify: `services/knowledge-engine/tests/test_mcp_general.py`（追加新测试）

**接口约定**：

```python
async def query_template_chunks(
    query: str,
    kb_id: str | None = None,
    source_type: str | None = "livestream-analysis",
    top_k: int = 10,
) -> dict:
    """从模板 KB 检索素材 chunks（按 source_type 过滤）。

    Args:
        query: 自然语言查询
        kb_id: 显式指定 KB id；None = 自动找所有 kb_role='template' KB
        source_type: 过滤 source_type；None = 不限制
        top_k: 返回数量上限

    Returns:
        {ok, result: {hits: [{kb_id, kb_name, chunk_id, content, source_type,
            metadata, score}], count}, trace}
    """
```

- [ ] **Step 1: 写 failing test**

更新 import：

```python
from app.mcp.tools.general import (
    summarize_text,
    parse_long_doc_with_gemini,
    query_template_chunks,
)
```

追加测试：

```python
@pytest.mark.asyncio
async def test_query_template_chunks_empty_query():
    """空 query → invalid_query。"""
    result = await query_template_chunks(query="")
    assert result["ok"] is False
    assert result["error"] == "invalid_query"


@pytest.mark.asyncio
async def test_query_template_chunks_basic():
    """基础查询应返回 hits（topology 取决于真实数据）。"""
    result = await query_template_chunks(
        query="直播开场怎么吸引观众",
        top_k=5,
    )
    assert result["ok"] is True
    res = result["result"]
    assert "hits" in res
    assert isinstance(res["hits"], list)
    # template KB 现状有 60 条 livestream-analysis chunks，应该 hits>=1
    assert res["count"] >= 1
    assert res["count"] <= 5
    # 默认 source_type='livestream-analysis'，hits 应全部命中此 type
    for h in res["hits"]:
        assert h["source_type"] == "livestream-analysis"
        assert "content" in h
        assert "score" in h
        assert "kb_id" in h


@pytest.mark.asyncio
async def test_query_template_chunks_no_source_type_filter():
    """source_type=None 不限制，应返回所有命中。"""
    result = await query_template_chunks(
        query="直播",
        source_type=None,
        top_k=20,
    )
    assert result["ok"] is True
    # 至少能找到 livestream-analysis 命中
    assert result["result"]["count"] >= 1


@pytest.mark.asyncio
async def test_query_template_chunks_invalid_kb_id():
    """指定不存在的 kb_id → kb_not_found。"""
    import uuid
    fake = str(uuid.uuid4())
    result = await query_template_chunks(query="any", kb_id=fake)
    assert result["ok"] is False
    assert result["error"] == "kb_not_found"


@pytest.mark.asyncio
async def test_query_template_chunks_no_template_kbs():
    """当系统真没 kb_role='template' KB 时返 no_template_kbs。"""
    # 这测试不能真删 KB（生产数据），用 monkeypatch 模拟
    from app.services import ingestion as _ingestion

    original = _ingestion.list_kbs

    async def mock_no_template():
        kbs = await original()
        return [k for k in kbs if k.get("kb_role") != "template"]

    _ingestion.list_kbs = mock_no_template
    try:
        result = await query_template_chunks(query="any")
    finally:
        _ingestion.list_kbs = original

    assert result["ok"] is False
    assert result["error"] == "no_template_kbs"
```

- [ ] **Step 2: 跑测试看 fail**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_general.py -v -k query_template"
```

期望：`ImportError: cannot import name 'query_template_chunks'`

- [ ] **Step 3: 写实现（追加到 general.py）**

```python
from app.services import ingestion
from app.services.embedding_client import embed_texts
from app.services.hybrid_search import hybrid_search


@tool_with_audit(mcp, require_approval=False)
async def query_template_chunks(
    query: str,
    kb_id: str | None = None,
    source_type: str | None = "livestream-analysis",
    top_k: int = 10,
) -> dict:
    """从模板 KB 检索素材 chunks。

    默认行为：找所有 kb_role='template' 的 KB，按 query 走 hybrid_search，
    post-filter source_type='livestream-analysis'，返 top_k。

    Args:
        query: 自然语言查询
        kb_id: 显式指定 KB id（跳过 role 解析）
        source_type: 过滤 source_type；None = 不限
        top_k: 返回数量上限

    Returns:
        {ok, result: {hits, count}, trace}
    """
    query = (query or "").strip()
    if not query:
        return {
            "ok": False,
            "error": "invalid_query",
            "hint": "query 不能为空",
        }

    # 解析 kb_ids
    if kb_id:
        kb = await ingestion.get_kb(kb_id)
        if not kb:
            return {
                "ok": False,
                "error": "kb_not_found",
                "hint": f"kb_id={kb_id} 不存在；用 list_kbs 查可用",
            }
        target_kbs = [kb]
    else:
        all_kbs = await ingestion.list_kbs()
        target_kbs = [k for k in all_kbs if k.get("kb_role") == "template"]
        if not target_kbs:
            return {
                "ok": False,
                "error": "no_template_kbs",
                "hint": "系统中没有 kb_role='template' 的 KB；用 kb_set_role 改一个，或显式传 kb_id",
            }

    # 对每个 KB 跑 hybrid_search，融合结果
    all_hits: list[dict] = []
    over_fetch = top_k * 3  # 留余量给 post-filter
    for kb in target_kbs:
        kb_id_str = str(kb["id"])
        embedding_model = kb.get("embedding_model") or "gemini-embedding-2-preview"
        embedding_provider = kb.get("embedding_provider") or "gemini"
        try:
            vectors = await embed_texts(
                [query], model=embedding_model, provider=embedding_provider
            )
        except Exception as exc:
            logger.warning(
                "query_template_chunks embed failed for kb=%s: %s",
                kb_id_str[:8],
                exc,
            )
            continue
        if not vectors:
            continue
        try:
            hits = await hybrid_search(
                kb_id=kb_id_str,
                query=query,
                query_embedding=vectors[0],
                top_k=over_fetch,
            )
        except Exception as exc:
            logger.warning(
                "query_template_chunks hybrid_search failed for kb=%s: %s",
                kb_id_str[:8],
                exc,
            )
            continue
        for h in hits:
            h["kb_id"] = kb_id_str
            h["kb_name"] = kb.get("name")
            all_hits.append(h)

    # post-filter source_type
    if source_type:
        all_hits = [h for h in all_hits if h.get("source_type") == source_type]

    # 按 score 降序，截 top_k
    all_hits.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
    all_hits = all_hits[:top_k]

    # 整形 hits（精简字段）
    hits = [
        {
            "kb_id": h["kb_id"],
            "kb_name": h["kb_name"],
            "chunk_id": str(h.get("id")) if h.get("id") else None,
            "title": h.get("title"),
            "content": h.get("content"),
            "source_type": h.get("source_type"),
            "metadata": h.get("metadata") or {},
            "score": float(h.get("score") or 0),
        }
        for h in all_hits
    ]

    return {
        "ok": True,
        "result": {
            "hits": hits,
            "count": len(hits),
        },
        "trace": build_trace(
            model="hybrid_search",
            provider="db",
            params={
                "kb_count": len(target_kbs),
                "query": query[:200],
                "source_type_filter": source_type,
                "top_k": top_k,
                "over_fetch": over_fetch,
            },
            final_prompt=None,
            cost=None,
        ),
    }
```

- [ ] **Step 4: 跑测试看 pass**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_general.py -v"
```

期望：14 个测试全 PASS（5 summarize + 4 parse_long_doc + 5 query_template）。

如果 test_query_template_chunks_basic 返 0 hits：检查 livestream-analysis 60 条数据是否真在 template KB 内：

```bash
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT kb.kb_role, c.source_type, COUNT(*) FROM knowledge.knowledge_chunks c JOIN knowledge.knowledge_bases kb ON c.kb_id = kb.id WHERE kb.kb_role='template' GROUP BY 1, 2;"
```

预期至少有一行 `template | livestream-analysis | N>0`。

- [ ] **Step 5: KE restart + commit**

```bash
docker restart omni-knowledge-engine
git add services/knowledge-engine/app/mcp/tools/general.py services/knowledge-engine/tests/test_mcp_general.py
git commit -m "$(cat <<'EOF'
feat(mcp): query_template_chunks 模板素材检索 tool (W3c T3)

W3c 第 3 个 tool。F 类。从 kb_role='template' 的 KB 里按 query 走
hybrid_search（向量+全文+HyPE 三路 RRF 融合），post-filter source_type
（默认 'livestream-analysis'），返 top_k chunks。

设计为 hybrid_search 的"模板 KB 专用 alias"，跟 search_kb 区别：
- 自动锁定 kb_role='template'
- 默认按 source_type 筛素材
- 返回结构含完整 metadata 字段（让老板看 contextual_header 等）

测试 5 case：空 query / 基础查询 / 不限 source_type / kb_not_found /
no_template_kbs（用 monkeypatch 模拟）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- KB row 的 `embedding_provider` / `embedding_model` 是必填列（schema 默认值），但拉到内存可能是空——加 fallback 防 None
- `embed_texts` 接收的是文本**列表**，返回向量列表；query 传 `[query]` 拿 `vectors[0]`
- hybrid_search 返回 hits 直接含 `id` / `content` / `metadata` / `source_type` / `score`，不需要二次查 DB
- monkeypatch ingestion.list_kbs 时记得 finally 还原（同 W3b T6/T7 模式）
- over_fetch = top_k * 3 是为了 source_type post-filter 后还能凑够 top_k；如果 source_type 过滤太严格 hits 可能少于 top_k

---

## Task 4: doctor expected_tools=23 + tools/__init__.py + tool_models.yaml

**Goal:** 注册 W3c 3 tool 到 doctor + tool_models.yaml 加 keyed override + tools/__init__.py docstring 更新。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/doctor.py`
- Modify: `services/knowledge-engine/app/mcp/tools/__init__.py`
- Modify: `services/knowledge-engine/config/tool_models.yaml`

- [ ] **Step 1: 改 doctor.py**

修改 `_check_tools_registered` 内的 wanted 集合（W3a/W3b 已设的列表，追加 3 个）：

```python
        wanted = {
            # W1
            "list_skus", "get_sku", "search_kb", "list_kbs", "list_briefs",
            # W2
            "query_costs", "compute_margin",
            "generate_brief", "generate_image", "generate_video",
            # W3a
            "record_cost", "disable_cost_item", "gather_brief_context",
            # W3b
            "fetch_compass_store_daily", "fetch_compass_sku_detail",
            "fetch_compass_search_traffic",
            "fetch_yuntu_5a", "fetch_yuntu_brand_mind",
            "kb_upload_doc", "kb_set_role",
            # W3c
            "summarize_text", "parse_long_doc_with_gemini",
            "query_template_chunks",
        }
```

注释也跟着改：`# W1 5 + W2 5 + W3a 3 + W3b 7 + W3c 3 = 23`

- [ ] **Step 2: 改 tools/__init__.py**

```python
"""W1 + W2 + W3a + W3b + W3c tools。

注册顺序：在 `app.mcp.server` import 时通过 `import app.mcp.tools.<x>` 等触发副作用。

23 tool 总览：
- W1 (5): list_skus, get_sku, list_kbs, search_kb, list_briefs
- W2 (5): query_costs, compute_margin, generate_brief, generate_image, generate_video
- W3a (3): gather_brief_context, record_cost, disable_cost_item
- W3b (7): fetch_compass_store_daily, fetch_compass_sku_detail,
           fetch_compass_search_traffic, fetch_yuntu_5a, fetch_yuntu_brand_mind,
           kb_upload_doc, kb_set_role
- W3c (3): summarize_text, parse_long_doc_with_gemini, query_template_chunks
"""
```

- [ ] **Step 3: 改 tool_models.yaml**

先看现有内容：

```bash
docker exec omni-knowledge-engine cat /app/config/tool_models.yaml
```

在 `__default__` / `compute_margin` / `generate_brief` / `generate_image` / `generate_video` 之后追加：

```yaml
summarize_text:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.3
  max_tokens: 2048

parse_long_doc_with_gemini:
  provider: gemini
  model: gemini-2.5-flash
  temperature: 0.2
  max_tokens: 8192
```

注：query_template_chunks 不调 LLM 不需要 yaml 配置。

- [ ] **Step 4: KE restart + 跑 doctor**

```bash
docker restart omni-knowledge-engine
sleep 5
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

期望输出：

```
omni MCP doctor 报告
  [OK  ] DB pool
  [OK  ] mcp schema tables: found 2/2
  [OK  ] tool_models.yaml: keys=[..., 'summarize_text', 'parse_long_doc_with_gemini', ...]
  [OK  ] prompt templates: all 8 ok      ← W3c 加了 4 个 .md 但 doctor 只检 W3a 的 8 个，不报错
  [OK  ] 23 tools registered: all 23 ok
  [OK  ] /mcp HTTP: status=200

结论：全绿 ✓
```

- [ ] **Step 5: commit**

```bash
git add services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/app/mcp/tools/__init__.py services/knowledge-engine/config/tool_models.yaml
git commit -m "$(cat <<'EOF'
feat(mcp): doctor expected_tools=23 + yaml W3c keyed + tools/__init__.py 更新 (W3c T4)

W3c 3 tool 全部注册到 server，doctor 升 20 → 23。新增 summarize_text /
parse_long_doc_with_gemini / query_template_chunks。

tool_models.yaml 加 W3c keyed override：
- summarize_text: gemini-3-flash-preview / temp 0.3
- parse_long_doc_with_gemini: gemini-2.5-flash / temp 0.2

跑 doctor 期望 [OK] 23 tools registered: all 23 ok。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**容易撞的坑**：
- doctor.py 的 wanted 集合常量名（看 W3b T8 commit `0d82d22`）—— 行内 `wanted = {...}` 在 `_check_tools_registered` 函数内
- yaml 的 indentation 错就是 yaml.safe_load 抛错，model_config.py 启动期挂——改 yaml 后必须 KE restart 验证
- yaml 不存在 query_template_chunks 配置不报错（resolve_model 走 __default__）

---

## Task 5: e2e 容器内自检 + 老板侧 grant 累积清单

**Goal:** 容器内跑 3 tool 一遍 sanity + 给老板列出需要 grant 的 mcp__omni__ 权限清单。

**Files:**
- Create: `services/knowledge-engine/scripts/_w3c_e2e.py`（**throwaway 跑完删**）
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: 写容器内 e2e 脚本**

```python
# services/knowledge-engine/scripts/_w3c_e2e.py（throwaway）
"""W3c e2e 容器内自检：跑 3 tool。

用法：
    docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python scripts/_w3c_e2e.py"
"""
import asyncio
import os
import tempfile

from app.database import init_pool, close_pool
from app.mcp.tools.general import (
    summarize_text,
    parse_long_doc_with_gemini,
    query_template_chunks,
)


async def main():
    await init_pool()

    print("\n=== T1 summarize_text ===")
    sample = (
        "今天去市场买苹果，3 斤 15 元，是红富士。"
        "回家路上下雨没带伞淋了一身，到家发现忘记买香蕉。"
    )
    r = await summarize_text(text=sample, instruction="只列出买的水果")
    if r["ok"]:
        print(f"ok=True length_in={r['result']['length_in']} length_out={r['result']['length_out']}")
        print(f"summary: {r['result']['summary'][:200]}")
    else:
        print(f"ok=False error={r.get('error')} hint={r.get('hint')}")

    print("\n=== T2 parse_long_doc_with_gemini ===")
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
        f.write(
            "# 产品分析报告\n\n"
            "## 1. 概况\n销量 1000 件，营收 5 万。\n\n"
            "## 2. 用户画像\n核心用户 25-35 岁女性，复购率 30%。\n\n"
            "## 3. 卖点\n- 价格便宜\n- 质量好\n- 包邮\n"
        )
        tmp = f.name
    try:
        r = await parse_long_doc_with_gemini(file_path=tmp)
        if r["ok"]:
            print(f"ok=True source_type={r['result']['source_type']} length_in={r['result']['length_in']}")
            print(f"outline (first 300 chars): {r['result']['markdown_outline'][:300]}")
        else:
            print(f"ok=False error={r.get('error')} hint={r.get('hint')}")
    finally:
        os.unlink(tmp)

    print("\n=== T3 query_template_chunks ===")
    r = await query_template_chunks(query="直播开场怎么吸引观众", top_k=3)
    if r["ok"]:
        print(f"ok=True count={r['result']['count']}")
        for i, h in enumerate(r["result"]["hits"], 1):
            content = (h.get("content") or "")[:80]
            print(f"  [{i}] kb={h['kb_name'][:20]} score={h['score']:.3f} content={content}...")
    else:
        print(f"ok=False error={r.get('error')} hint={r.get('hint')}")

    print("\n=== W3c e2e 完成 ===")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 跑容器内 e2e**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python scripts/_w3c_e2e.py"
```

期望：
- T1 summarize_text 返 summary（应该提到"苹果"，不提价格）
- T2 parse_long_doc_with_gemini 返结构化 markdown outline（含 ## 章节）
- T3 query_template_chunks count >= 1（livestream-analysis 60 条命中至少 1 条）

- [ ] **Step 3: 删 throwaway 脚本**

```bash
rm services/knowledge-engine/scripts/_w3c_e2e.py
```

- [ ] **Step 4: 给 settings.local.json 加 grant**

修改 `.claude/settings.local.json`，在 `permissions.allow` 列表的 `mcp__omni__*` 区域追加 3 项：

```json
"mcp__omni__summarize_text",
"mcp__omni__parse_long_doc_with_gemini",
"mcp__omni__query_template_chunks"
```

按现有 `mcp__omni__*` 顺序追加（参考 W3b T9 commit `b56bb5e` 的格式）。

- [ ] **Step 5: commit settings + W3c 收尾**

```bash
git add .claude/settings.local.json
git commit -m "$(cat <<'EOF'
chore(claude): grant W3c 3 tool 权限 (W3c T5)

老板侧 e2e 不再每次提示批准。grant summarize_text /
parse_long_doc_with_gemini / query_template_chunks。

容器内 e2e 自检通过：
- T1 summarize_text: gemini 出指令型摘要
- T2 parse_long_doc_with_gemini: gemini-2.5-flash 出结构化 markdown
- T3 query_template_chunks: 命中 livestream-analysis chunks

W3c 落地完毕，doctor 23/23 OK。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: 老板侧客户端 e2e（在 Claude Code 里测）**

老板自己在 Claude Code 里跑：

```
帮我把这段话浓缩 50 字: <粘贴一段长文>
解析这个 PDF: /path/to/<某份白皮书>.pdf
找一个直播开场钩子素材
```

如果 prompt 里"浓缩"/"解析"/"找素材"触发 Claude 调对应 tool，看返回是否合理。grant 已加，不会卡审。

**容易撞的坑**：
- `_w3c_e2e.py` throwaway 标记前缀 `_`；step 3 直接删，不要留
- settings.local.json 顺序无关键；保持跟 W3b 风格一致即可
- 老板侧 e2e 需要 ai-provider-hub 的 gemini key 有效（之前 b811c51 commit 已确认 hub 容器化 + key 注入；如果 chat 报错先 `docker logs omni-ai-provider-hub --tail 30` 看）

---

## Self-Review

### 1. Spec coverage check

design doc §3.2 W3 行 13 tool：
- ✅ W3b 落了 7 个（5 scout + 2 KB 管理）
- ✅ W3c 落 3 个（summarize_text / parse_long_doc_with_gemini / query_template_chunks）
- ❌ W3 录音 3 个（list_recordings / get_recording / generate_recording_insights）—— **老板拍板不做**（自己手动转文字进 KB，retrieval 走 search_kb）

### 2. Placeholder scan

- [x] 无 "TBD" / "TODO" / "fill in details"
- [x] 每 task 含完整测试代码 + 实现代码
- [x] 每 commit 含完整 commit message
- [x] 每 task 含 commands + expected output

### 3. Type / 签名 consistency

- `summarize_text(text: str, instruction: str | None = None, max_input_chars: int = 30000)` ✓
- `parse_long_doc_with_gemini(file_path: str, instruction: str | None = None, max_input_chars: int = 800000)` ✓
- `query_template_chunks(query: str, kb_id: str | None = None, source_type: str | None = "livestream-analysis", top_k: int = 10)` ✓
- 所有返 dict 都带 `{ok, result | error, hint?, trace}` 结构（同 W2/W3a/W3b）✓
- `build_trace(model, provider, params, final_prompt, cost)` 签名跟 W2 / W3a 已用一致（trace.py 内）✓

### 4. 已知风险 / 待补

- **livestream-analysis 60 条数据可能在 deflate 后命中率低**：T3 测试期间真打 hybrid_search 看 hits ≥ 1 是必须；如果命中 0 检查 embedding cache 是否旧（embedding 表 / redis 缓存）
- **gemini-2.5-flash 模型名**：tool_models.yaml 写的是 `gemini-2.5-flash`，需要 ai-provider-hub gemini_provider 已注册此 model；如果 hub 报"unknown model"切回 `gemini-3-flash-preview`（容量小但快）
- **prompt 模板的 {占位} 跟 ctx 必须对齐**：W3a 期间踩过 `KeyError` 因为 ctx 缺 key；implementer 写完 prompt .md 后跟 `prompts.render(...)` 调用对一遍占位符
- **enforce_human_voice=True 是 W3c 的关键差异**：summarize_text 默认 True（老板要"说人话"摘要）；parse_long_doc 默认 False（结构化解析不要文风干扰）；query_template_chunks 不调 LLM 不涉及

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-omni-agent-uplift-W3c-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 5 个 task 每个 fresh subagent + 二阶 review。预估 4 小时完整跑完。建议同 W3b 节奏：T1 跑 quality reviewer 建基线，T2/T3 自审 diff，T4/T5 chore inline。

**2. Inline Execution** — 在当前 session 跑，batch + checkpoint，老板可中途审。预估 3 小时（少 subagent context 切换开销）。

**Which approach?**
