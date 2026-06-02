# Omni Agent 化升级 W3a（prompt 外置 + sku SOP + cost 数据 + Human Gate 真启用）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 W2 e2e 暴露的 4 个伤口一次修了——(1) 所有 LLM tool 的 prompt 从 Python 硬编码搬到 `config/prompts/*.md`（编辑 .md 文件 + KE 容器 restart 即生效，不改代码）；(2) sku 全链路 SOP 升级带 KB grounding（generate_brief 不再裸 LLM，先 search_kb 拿 3 类上下文塞 extra_context）；(3) 加 `record_cost` / `disable_cost_item` 两个写入 tool，让老板对话录成本（accounting.cost_items 才有用）；(4) Human Gate W1 stub 演变成真实现（写 mcp.human_gates → CLI poll 批/驳 → DB 等），配合 cost 写入和 W3b 后续 T 类 tool。

**Architecture:** 不写 `run_sku_orch` / 不上前端 `/inbox` / 不做分布式 / 不引入 jinja2（用 `str.format(**ctx)`，YAGNI）。SOP 升级靠改 `CLAUDE.md`（编排靠 Claude 主大脑对话）+ 加一个辅助 tool `gather_brief_context`；Gate 走"写表 + CLI 批/驳 + DB poll 等"的极简形态（个人自用，不要前端，CLI = `python -m app.mcp.cli_approve list/approve/reject/tail`）。沿用 W1/W2 的 `@tool_with_audit` + `ai_hub_client` + `tool_models.yaml` 框架，**不改 W2 已落地 5 LLM tool 的接口和返回 schema**。新增 3 个 tool：`record_cost` / `disable_cost_item` / `gather_brief_context`（doctor expected_tools 升 13）。

**Tech Stack:** Python 3.11+ (现有), FastMCP 3.2.x (现有), asyncpg (现有), PyYAML (现有), str.format 模板（不引 jinja2）, PostgreSQL 16 + `accounting.cost_items` (migration 015 已上) + `mcp.tool_calls` / `mcp.human_gates` (migration 016 已上), `gemini-3-flash-preview` (chat default)。Windows 11 + PowerShell 5.1。knowledge-engine 容器 8002（已 bind-mount `app/` `tests/` `config/`，本 plan 加 `scripts/` bind 一并）。

---

## 前置条件（开 T0 前必满足）

1. **W1 + A2 + W2 已落地**：
   - `feat/mcp-w1` 分支 HEAD `850fa0f` 或更新
   - `docker ps` 显示 `omni-postgres` / `omni-redis` / `omni-ai-provider-hub` / `omni-knowledge-engine` 4 个 Up
   - `docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"` 输出 5 项全 `OK`，含 `10 tools registered: all 10 ok`
   - `accounting.cost_items` 表存在（migration 015）；当前可空（W2 e2e 已确认空表，T13 时手工录）
   - `mcp.tool_calls` / `mcp.human_gates` 表存在（migration 016）

2. **必读上下文**：
   - 设计文档 `E:\agent\omni\docs\superpowers\specs\2026-05-03-omni-agent-uplift-design.md` §5 Human Gate 详设 + §6 trace + §7 review-after iterate
   - 进度跟踪 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md` §十三 W2 e2e 实测结论（4 伤口来源）
   - W2 plan 模式 `E:\agent\omni\docs\superpowers\plans\2026-05-04-omni-agent-uplift-W2-plan.md` （TDD + step + commit 节奏）
   - 项目根 `E:\agent\omni\CLAUDE.md`（sku 出片标准链路 + 老板响应词约定，本 plan T11 升级）
   - feedback memory：
     - `feedback_writing_style.md` — 说人话 + 反幻觉 + 去 AI 化（5 注入点）
     - `feedback_personal_use_no_overengineering.md` — 拒绝灰度/分布式/SLA
     - `feedback_collaboration_style.md` — 先框架后内容 + 2-3 选 1
   - W2 期间踩的坑见 status memory §"W2 期间踩的坑 + 解法"（fixture sync / pytest 命令 / Decimal / provider_config.json 等）

3. **uncommitted yaml 改动收编**：
   - `services/knowledge-engine/config/tool_models.yaml` 改了 `generate_image: openai/gpt-image-2 → gemini/gemini-3.1-flash-image-preview`（W2 e2e OpenAI 403 hotfix）
   - `.claude/settings.local.json` W2 e2e 期间累积的 grant
   - `.e2e-out/` W2 落盘的 base64 图片（应入 `.gitignore`）
   - 本 plan T1 第一个 commit 时把 yaml 改动一起带上（commit message 明确 hotfix 来源）；`.e2e-out/` 在 T0 step 加进 `.gitignore`

4. **范围说明（写给后续 implementer 看）**：
   - W3a **不**实现 design doc §3.2 W3 行的 13 tool（scout / 通用 LLM / 录音 / KB 管理）—— 那批留 W3b/W3c
   - W3a 加的 3 个新 tool（`record_cost` / `disable_cost_item` / `gather_brief_context`）**不在原 design doc**，是 W2 e2e 反馈后增量
   - 老板叫停 e2e 的核心点："brief 不能裸 LLM 出，需要 SOP + KB grounding" → M2 编排层修缮
   - prompt 外置（M1）是硬需求基建，W3b/W3c 所有新 LLM tool 自动走这套，不重构

---

## 文件结构（W3a 全量）

### 新增（17 个）

| 路径 | 行数估 | 责任 |
|---|---|---|
| `services/knowledge-engine/app/mcp/prompts.py` | ~110 | prompt 模板 loader/render（cache + invalidate；str.format 替换占位） |
| `services/knowledge-engine/app/mcp/cli_approve.py` | ~150 | omni-mcp-approve CLI（list/approve/reject/tail human_gates） |
| `services/knowledge-engine/app/mcp/tools/cost_admin.py` | ~140 | `record_cost` + `disable_cost_item`（require_approval=True） |
| `services/knowledge-engine/app/mcp/tools/sop.py` | ~100 | `gather_brief_context`（search_kb 3 类拼 extra_context） |
| `services/knowledge-engine/scripts/import_costs.py` | ~80 | CSV 批量导入 cost_items（绕 Gate，老板自触发） |
| `services/knowledge-engine/scripts/cost_template.csv` | ~10 | 导入 csv 模板示例 |
| `services/knowledge-engine/config/prompts/anti_ai_voice.md` | ~30 | 通用反 AI 化模板（替代 prompt_constraints.py 字面量） |
| `services/knowledge-engine/config/prompts/generate_brief.system.md` | ~30 | generate_brief system 部分 |
| `services/knowledge-engine/config/prompts/generate_brief.user.md` | ~25 | generate_brief user 模板（占位 `{sku_md}` `{channel_profile}` `{kb_context}` `{extra_context}`） |
| `services/knowledge-engine/config/prompts/compute_margin.system.md` | ~25 | compute_margin system |
| `services/knowledge-engine/config/prompts/compute_margin.user.md` | ~10 | compute_margin user 模板（占位 `{breakdown_json}`） |
| `services/knowledge-engine/config/prompts/channel_profiles/douyin.md` | ~15 | 抖音渠道画像 |
| `services/knowledge-engine/config/prompts/channel_profiles/tmall.md` | ~10 | 天猫 |
| `services/knowledge-engine/config/prompts/channel_profiles/jd.md` | ~10 | 京东 |
| `services/knowledge-engine/tests/test_mcp_prompts.py` | ~120 | prompts.py loader/render/reload 单测 |
| `services/knowledge-engine/tests/test_mcp_human_gate.py` | ~180 | gate 真实现集成测（批/驳/超时） |
| `services/knowledge-engine/tests/test_mcp_cost_admin.py` | ~140 | record_cost/disable_cost_item 集成测（mock gate） |
| `services/knowledge-engine/tests/test_mcp_sop_orchestration.py` | ~100 | gather_brief_context 集成测（mock search_kb） |

### 修改（10 个）

| 路径 | 改动 |
|---|---|
| `services/knowledge-engine/app/mcp/human_gate.py` | stub → 真实现：写 `mcp.human_gates` + DB poll 等批/驳 + 超时 |
| `services/knowledge-engine/app/mcp/audit.py` | Gate 真启用后 `summary_fn` 默认值优雅；W1 NotImplementedError 兜底分支删除（gate 真实现不再抛） |
| `services/knowledge-engine/app/mcp/prompt_constraints.py` | 改成从 `prompts.load("anti_ai_voice")` 加载，保 `ANTI_AI_HUMAN_VOICE` 名兼容 ai_hub_client import |
| `services/knowledge-engine/app/mcp/tools/accounting.py` | `compute_margin` 走 `prompts.render(...)` 替代硬编码 sys/user msg |
| `services/knowledge-engine/app/mcp/tools/media.py` | `generate_brief` 走 `prompts.render(...)`；user 模板加 `{kb_context}`；`_channel_profile` 切到 `prompts.load_channel_profile` |
| `services/knowledge-engine/app/mcp/server.py` | import 注册 `cost_admin` + `sop` 两个新 tool 模块 |
| `services/knowledge-engine/app/mcp/doctor.py` | `expected_tools` 升 13；加新 check：`config/prompts/` 关键文件存在性 |
| `services/knowledge-engine/config/tool_models.yaml` | 每 LLM tool 加 `prompts.system` / `prompts.user` 路径字段；新加 `record_cost`/`disable_cost_item` 占位（不调 LLM 但保结构一致） |
| `services/knowledge-engine/docker-compose.yml` 或 `E:\agent\omni\docker-compose.yml` | knowledge-engine bind mount 加 `./services/knowledge-engine/scripts:/app/scripts:rw`（导入脚本走容器内跑） |
| `E:\agent\omni\CLAUDE.md` | sku 全链路 SOP 升级带 KB grounding（step 3 加 gather_brief_context）；老板响应词加 cost 录入；调试三件套加 omni-mcp-approve |

### 项目级（2 个）

| 路径 | 改动 |
|---|---|
| `E:\agent\omni\.claude\settings.local.json` | 累 grant：`mcp__omni__record_cost` / `mcp__omni__disable_cost_item` / `mcp__omni__gather_brief_context` |
| `E:\agent\omni\.gitignore` | 加 `.e2e-out/`（W2 e2e 落盘 base64 图片；不应入 git） |

---

## 任务

### 任务 0：Sanity check + 前置阻塞排除 + uncommitted hotfix 收编

**目的**：W3a 起手前确认 W2 落地状态，把 yaml hotfix 和 .gitignore 一起进 W3a 第一个 commit，干净起步。

**Files:**
- Modify: `E:\agent\omni\.gitignore`（加 `.e2e-out/`）
- Modify: `services/knowledge-engine/config/tool_models.yaml`（W2 e2e 留下的改动收编，本 task 仅落 commit，T3 还会改）

- [ ] **Step 1：容器健康检查**

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}" | Select-String "omni-"
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected:
```
omni-ai-provider-hub    Up ...
omni-knowledge-engine   Up ...
omni-redis              Up ... (healthy)
omni-postgres           Up ... (healthy)
```

doctor 5 项全 OK，`10 tools registered: all 10 ok`。

如有 FAIL：先排错（见 status memory §A2 已知坑），不要盲推进 W3a。

- [ ] **Step 2：检查 git 状态 + 当前 HEAD**

```powershell
git status --short
git log --oneline -5
```

预期看到：
- `M services/knowledge-engine/config/tool_models.yaml`（W2 e2e hotfix）
- `M .claude/settings.local.json`（W2 e2e grant 累积）
- `?? .e2e-out/`
- HEAD 在 `850fa0f` 或更新

- [ ] **Step 3：补 .gitignore**

打开 `E:\agent\omni\.gitignore`（如不存在则建），末尾加：
```
# W2 e2e 落盘（base64 图片）
.e2e-out/
```

- [ ] **Step 4：commit 收编**

```powershell
git add .gitignore services/knowledge-engine/config/tool_models.yaml .claude/settings.local.json
git commit -m "chore(e2e): collect W2 hotfix yaml + e2e-out gitignore (W3a T0)"
```

注：tool_models.yaml 在 T3 还会改（加 prompts 字段）；本次只先把 W2 hotfix 落定，避免后续 git status 吵杂。

- [ ] **Step 5：复验环境**

```powershell
git status --short
```

Expected: 空（无 dirty）。

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected: 仍 5 项全 OK。

---

### 任务 1：prompts.py 模板加载基建（M1 第一步）

**目的**：建一个统一的 prompt 模板加载/渲染模块。所有 LLM tool 后续走它，不再硬编码字符串。

设计要点：
- 模板放 `config/prompts/<name>.md`，扩展 `.md` 让 IDE markdown 高亮
- `prompts.load(name)` 返回原文字符串（带 cache，自带变更检测：mtime 比对）
- `prompts.render(name, **ctx)` = `load(name).format(**ctx)`，用 Python `str.format` 占位（`{key}`）
- 不引 jinja2（个人用，YAGNI；如果以后真要循环/条件再说）
- 模板未找到的占位抛 `KeyError`（暴露 caller bug，不做静默兜底）
- `prompts.invalidate()` 强清缓存（容器内热重载靠 mtime 自动；CLI 测试用）

**Files:**
- Create: `services/knowledge-engine/app/mcp/prompts.py`
- Create: `services/knowledge-engine/config/prompts/anti_ai_voice.md`
- Create: `services/knowledge-engine/tests/test_mcp_prompts.py`

- [ ] **Step 1：写 prompts loader 测试（先红）**

`services/knowledge-engine/tests/test_mcp_prompts.py`:
```python
"""W3a T1：prompts loader/render/reload 单测。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.mcp import prompts as P


def test_load_existing_template():
    """anti_ai_voice.md 应该能加载。"""
    text = P.load("anti_ai_voice")
    assert "说人话" in text
    assert "反幻觉" in text
    assert "去 AI 化" in text


def test_load_unknown_raises():
    with pytest.raises(FileNotFoundError):
        P.load("__not_exist__")


def test_render_substitutes_placeholders(tmp_path, monkeypatch):
    """render 用 str.format 替换占位。"""
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    (p_dir / "_smoke.md").write_text("Hello {name}, channel={channel}", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    out = P.render("_smoke", name="Bob", channel="douyin")
    assert out == "Hello Bob, channel=douyin"


def test_render_missing_key_raises_keyerror(tmp_path, monkeypatch):
    """模板里有 {x} 但 ctx 没给 → KeyError（暴露 bug，不静默）。"""
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    (p_dir / "_smoke2.md").write_text("a={a} b={b}", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    with pytest.raises(KeyError):
        P.render("_smoke2", a=1)


def test_load_subdirectory(tmp_path, monkeypatch):
    """支持子目录形式名（channel_profiles/douyin）。"""
    p_dir = tmp_path / "prompts"
    sub = p_dir / "channel_profiles"
    sub.mkdir(parents=True)
    (sub / "douyin.md").write_text("抖音电商画像", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    out = P.load("channel_profiles/douyin")
    assert out == "抖音电商画像"


def test_mtime_invalidates_cache(tmp_path, monkeypatch):
    """改 .md 后 load 自动重读（mtime 检测）。"""
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    f = p_dir / "_smoke3.md"
    f.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    assert P.load("_smoke3") == "v1"
    # 改文件 + 推 mtime（确保跨时钟分辨率）
    time.sleep(0.05)
    f.write_text("v2", encoding="utf-8")
    # 显式推 mtime（部分 FS 分辨率秒级）
    import os as _os
    _os.utime(f, None)

    assert P.load("_smoke3") == "v2"


def test_invalidate_clears_cache(tmp_path, monkeypatch):
    p_dir = tmp_path / "prompts"
    p_dir.mkdir()
    f = p_dir / "_smoke4.md"
    f.write_text("a", encoding="utf-8")
    monkeypatch.setattr(P, "_PROMPTS_DIR", p_dir)
    P.invalidate()

    assert P.load("_smoke4") == "a"
    f.write_text("b", encoding="utf-8")
    P.invalidate()
    assert P.load("_smoke4") == "b"
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_prompts.py -v"
```

Expected: `ImportError: cannot import name 'prompts' from 'app.mcp'` 或 `ModuleNotFoundError`.

- [ ] **Step 3：实现 prompts.py**

`services/knowledge-engine/app/mcp/prompts.py`:
```python
"""W3a T1：prompt 模板加载 + 渲染（design doc §10 prompt 外置）。

设计：
- 模板放 `config/prompts/<name>.md`（支持子目录如 channel_profiles/douyin）
- `load(name)`：读 .md 原文（带 mtime cache，文件改了自动重读）
- `render(name, **ctx)`：load + str.format 占位替换
- `invalidate()`：清缓存（CLI/测试用）

不用 jinja2（YAGNI，个人用，没有循环/条件需求）；
str.format 的 {placeholder} 不存在 ctx 时抛 KeyError（暴露 caller bug）。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 模板根目录（services/knowledge-engine/config/prompts/）
_PROMPTS_DIR: Path = (
    Path(__file__).resolve().parents[2] / "config" / "prompts"
)

# 缓存：name → (mtime, content)
_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _path_for(name: str) -> Path:
    """name 形如 'generate_brief.system' 或 'channel_profiles/douyin' → 文件路径"""
    return _PROMPTS_DIR / f"{name}.md"


def load(name: str) -> str:
    """加载模板原文。带 mtime cache：文件改了自动重读。

    Args:
        name: 模板名，相对 config/prompts/，不含 .md 后缀。
              支持子目录形式如 'channel_profiles/douyin'。

    Returns:
        模板原文（utf-8）。

    Raises:
        FileNotFoundError: 模板文件不存在。
    """
    p = _path_for(name)
    if not p.exists():
        raise FileNotFoundError(f"prompt template not found: {p}")

    mtime = p.stat().st_mtime
    with _lock:
        cached = _cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        text = p.read_text(encoding="utf-8")
        _cache[name] = (mtime, text)
        return text


def render(name: str, **ctx: Any) -> str:
    """加载模板 + str.format 替换占位。

    Args:
        name: 模板名（同 load）
        **ctx: 占位变量。模板里 {key} 必须在 ctx 里有，否则 KeyError。

    Returns:
        渲染后字符串。

    Raises:
        FileNotFoundError: 模板不存在。
        KeyError: 模板有占位 ctx 没给。
    """
    template = load(name)
    return template.format(**ctx)


def invalidate(name: str | None = None) -> None:
    """清缓存。name=None 清全部；指定名清单条。"""
    with _lock:
        if name is None:
            _cache.clear()
        else:
            _cache.pop(name, None)


def list_templates() -> list[str]:
    """列出 config/prompts/ 下所有 .md 模板（递归）。doctor 用。"""
    if not _PROMPTS_DIR.exists():
        return []
    return sorted(
        str(p.relative_to(_PROMPTS_DIR).with_suffix(""))
            .replace("\\", "/")
        for p in _PROMPTS_DIR.rglob("*.md")
    )
```

- [ ] **Step 4：建 anti_ai_voice.md（先放最小内容让 test_load_existing_template 通过；T5 收尾再完整化）**

`services/knowledge-engine/config/prompts/anti_ai_voice.md`:
```markdown
【写作风格强制约束 — 不遵守视为输出错误】

说人话：
- 日常对话语气，像跟朋友说话
- 短句，1-2 句说清就停
- 关键信息顶到前面，不铺垫
- 用具体数字 / 例子 / 时间，不用抽象描述
- 用"咱""你""我"，不用"用户""贵公司"
- 不写"综上""值得注意""不难发现"等套话
- 不机械堆"首先/其次/最后"（除非用户明确要分点）
- 不用"诉求""赋能""抓手""底层逻辑""链路"等黑话

反幻觉：
- 只用提供的资料里有的信息
- 资料里没有 → 直接说"这块没找到"或"我没数据"
- 数字、价格、人名、时间 → 必须有出处
- 事实和推测分开：推测前加"我猜""可能""估计"
- 不夸大（禁用"惊人""巨大成功""革命性"，除非引用原话）

去 AI 化（这些一律删除）：
- "作为 AI / 作为助手 / 作为大模型"
- "我理解您的需求 / 我可以帮您"
- "以下是.../让我为您..."
- "希望对您有帮助 / 如有疑问随时问我"
- 无意义 emoji（除非用户明确要用）
- 无意义 markdown 标题堆叠
- 客套结尾（"以上就是..."、"祝您..."、"加油！"）
```

- [ ] **Step 5：跑测试**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_prompts.py -v"
```

Expected: 7/7 PASS。

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/prompts.py `
        services/knowledge-engine/config/prompts/anti_ai_voice.md `
        services/knowledge-engine/tests/test_mcp_prompts.py
git commit -m "feat(mcp): prompts.py loader/render with mtime cache (W3a T1)"
```

---

### 任务 2：channel_profiles 外置 + media.py 接入（M1 第二步）

**目的**：把 `media.py:_CHANNEL_PROFILES` 字典硬编码搬到 `config/prompts/channel_profiles/<channel>.md`。改一个渠道画像不用改代码。

**Files:**
- Create: `services/knowledge-engine/config/prompts/channel_profiles/douyin.md`
- Create: `services/knowledge-engine/config/prompts/channel_profiles/tmall.md`
- Create: `services/knowledge-engine/config/prompts/channel_profiles/jd.md`
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`（替换 `_CHANNEL_PROFILES` + `_channel_profile`）

- [ ] **Step 1：建 3 个 channel_profile .md**

`services/knowledge-engine/config/prompts/channel_profiles/douyin.md`:
```markdown
抖音电商：竖版 9:16，前 3 秒强钩子，价格锚点 + 痛点切入；忌过长 brief（≤300 字）。
内容打法以"短平快"为主：
- 一开场就给冲突或反差（"你绝对没用过这种酱油，但你绝对吃过它做的饭"）
- 中间穿插使用场景 + 一个具体痛点
- 结尾给个动作钩子（"低于 X 元闭眼冲"），不写"立即购买"这种官方话术
```

`services/knowledge-engine/config/prompts/channel_profiles/tmall.md`:
```markdown
天猫店铺：详情页长图文为主，强调品质 + 资质 + 用户证言。
- 2-4 段，每段含一个具体购买理由
- 资质 / 工厂 / 工艺细节可以多写
- 弱化"优惠"，强化"凭什么值这个价"
```

`services/knowledge-engine/config/prompts/channel_profiles/jd.md`:
```markdown
京东自营：物流 + 售后承诺为主。
- 强调正品保障 / 快速配送 / 7 天无理由
- 文案语气偏理性，少夸张词
- 写明使用场景（家庭厨房 / 餐饮店 / 礼盒）
```

- [ ] **Step 2：改 media.py 的 `_channel_profile` 函数走 prompts.load**

打开 `services/knowledge-engine/app/mcp/tools/media.py`，找到（约 21-29 行）：
```python
_CHANNEL_PROFILES = {
    "douyin": "抖音电商：竖版 9:16，前 3 秒强钩子，价格锚点 + 痛点切入；忌过长 brief（≤300 字）",
    "tmall": "天猫店铺：详情页长图文，强调品质 + 资质 + 用户证言；2-4 段，每段含一个购买理由",
    "jd": "京东自营：物流 + 售后承诺为主；强调正品 / 配送 / 服务",
}


def _channel_profile(channel: str) -> str:
    return _CHANNEL_PROFILES.get(channel, f"渠道 {channel}（未配 profile，按通用电商写）")
```

替换为：
```python
from app.mcp import prompts


def _channel_profile(channel: str) -> str:
    """从 config/prompts/channel_profiles/<channel>.md 加载渠道画像。

    未配 profile 文件时返回 fallback 文案（不报错，让 brief 仍能出）。
    """
    try:
        return prompts.load(f"channel_profiles/{channel}").strip()
    except FileNotFoundError:
        return f"渠道 {channel}（未配 profile，按通用电商写）"
```

注：删掉 `_CHANNEL_PROFILES` 常量；保 `_channel_profile` 函数名（其他代码可能引用，实际只在 generate_brief 内部用，但保签名安全）。

- [ ] **Step 3：手测一次（容器 restart 拉新代码 + .md）**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine python -c "
from app.mcp.tools.media import _channel_profile
print('--- douyin ---')
print(_channel_profile('douyin'))
print('--- unknown ---')
print(_channel_profile('xiaohongshu'))
"
```

Expected:
- `--- douyin ---` 后显示 douyin.md 内容（抖音电商：竖版 9:16...）
- `--- unknown ---` 后显示 fallback `渠道 xiaohongshu（未配 profile，按通用电商写）`

- [ ] **Step 4：跑全部 mcp 测试看不破坏**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_prompts.py tests/test_mcp_media.py -v"
```

Expected: 全 PASS（test_mcp_media.py 是 W2 落地的；本次改动不该破坏）。

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/config/prompts/channel_profiles/ `
        services/knowledge-engine/app/mcp/tools/media.py
git commit -m "feat(mcp): externalize channel_profiles to .md (W3a T2)"
```

---

### 任务 3：generate_brief prompt 外置 + tool_models.yaml prompts 路径（M1 第三步）

**目的**：把 `media.py:generate_brief` 的 `sys_msg` / `user_msg` 字符串外置到 `.md` 模板；扩 `tool_models.yaml` 用 `prompts.system` / `prompts.user` 字段管路径；user 模板预留 `{kb_context}` 占位（M2 用）。

**Files:**
- Create: `services/knowledge-engine/config/prompts/generate_brief.system.md`
- Create: `services/knowledge-engine/config/prompts/generate_brief.user.md`
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`（generate_brief 走 prompts.render）
- Modify: `services/knowledge-engine/config/tool_models.yaml`（每 LLM tool 加 prompts.system/user 路径）

- [ ] **Step 1：建 generate_brief 两份模板**

`services/knowledge-engine/config/prompts/generate_brief.system.md`:
```markdown
你是调味品工厂老板的渠道运营。给一只 SKU 写一份渠道 brief。

brief 用 markdown 格式，必须含这些段落（每段一个二级标题）：
- 核心卖点（3 条，每条一句话，要具体不要套话）
- 目标人群（2-3 句话画像，要具象——年龄/家庭结构/消费场景）
- 主场景（1-2 个，写清"什么人在什么时候用什么菜场合下用"）
- 文案钩子（3 句备选，每句独立，10-25 字以内）
- 拍摄分镜建议（3 个分镜，每个 1 句话描述画面 + 1 句解释意图）

风格要求：
- 说人话，不用"亲""家人们""宝子们""家人们冲"等抖音广告腔
- 不写"综上""值得一提""作为 AI"等套话
- 卖点 / 钩子要敢点具体数字（具体到原料百分比、用了几年、哪个产地、检测过几项指标——只用资料里给的真实数字，没有就不编）
- 如果 KB 上下文里有同品类爆款拆解 / 历史用户反馈，**优先沿用爆款已验证的钩子结构**（但不抄文案）
```

`services/knowledge-engine/config/prompts/generate_brief.user.md`:
```markdown
## SKU
{sku_md}

## 渠道
{channel_profile}

## KB 上下文（同品类爆款 / 渠道 runbook / 历史 brief）
{kb_context}

## 额外要求
{extra_context}
```

- [ ] **Step 2：扩 tool_models.yaml 加 prompts 路径**

打开 `services/knowledge-engine/config/tool_models.yaml`，把 generate_brief 段改成：
```yaml
generate_brief:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.5   # 文案要发挥
  prompts:
    system: generate_brief.system
    user: generate_brief.user
```

compute_margin 段同步加（T4 用，先占位）：
```yaml
compute_margin:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.1   # 解读类，要稳
  prompts:
    system: compute_margin.system
    user: compute_margin.user
```

`generate_image` / `generate_video` **不加** prompts 字段（这俩不是 chat 类，prompt 是用户传入；模型描述 prompt 由 hub 端处理）。

- [ ] **Step 3：改 generate_brief 走 prompts.render**

打开 `services/knowledge-engine/app/mcp/tools/media.py`，找到 `generate_brief` 函数（约 32-157 行）。

把构造 `sys_msg` / `user_msg` 的部分（约 77-90 行）：
```python
    sys_msg = (
        "你是调味品工厂老板的渠道运营。给一只 SKU 写一份渠道 brief。"
        "brief 用 markdown 格式，含：核心卖点（3 条）/ 目标人群 / "
        "主场景 / 文案钩子（1 句）/ 拍摄分镜建议（3 个分镜的 1 句话描述）。"
        "说人话，不要废话，不要"亲""家人们"等套话。"
    )
    user_msg = (
        f"## SKU\n{sku_md}\n"
        f"## 渠道\n{_channel_profile(channel)}\n"
    )
    if extra_context:
        user_msg += f"\n## 额外要求\n{extra_context}\n"

    final_prompt = sys_msg + "\n\n" + user_msg
```

替换为：
```python
    sys_msg = prompts.render("generate_brief.system")
    user_msg = prompts.render(
        "generate_brief.user",
        sku_md=sku_md,
        channel_profile=_channel_profile(channel),
        kb_context=kb_context.strip() if kb_context else "（未提供 KB 上下文）",
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg
```

并在 `generate_brief` 函数签名加 `kb_context` 参数（M2 后续用，本 task 先建好接口）：
```python
@tool_with_audit(mcp, require_approval=False)
async def generate_brief(
    sku_id: str,
    channel: str,
    extra_context: str | None = None,
    kb_context: str | None = None,
) -> dict:
    """出渠道 brief（markdown）。基于 sku metadata + 渠道 profile + 可选 KB 上下文 + 可选 extra_context。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin / tmall / jd / ...）
        extra_context: 额外提示（如"主推健康"/"对标 X 品牌"）
        kb_context: 已检索好的 KB 上下文（建议由 gather_brief_context tool 出）

    Returns:
        {ok, result: {brief_md}, trace, next_step_hint(generate_image)}
    """
```

确保文件顶部（约 9-19 行）的 import 含 `prompts`：
```python
from app.mcp import prompts
```

- [ ] **Step 4：手测一次**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine python -c "
from app.mcp import prompts
out = prompts.render('generate_brief.user',
    sku_md='- 名称: TEST', channel_profile='douyin profile',
    kb_context='kb test', extra_context='extra test')
print(out)
"
```

Expected:
```
## SKU
- 名称: TEST

## 渠道
douyin profile

## KB 上下文（同品类爆款 / 渠道 runbook / 历史 brief）
kb test

## 额外要求
extra test
```

- [ ] **Step 5：跑 W2 现有 generate_brief 测试**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_media.py -v"
```

Expected: 全 PASS。如有 fail：检查测试是否对 final_prompt 内容做了硬断言（W2 测试可能 mock LLM 的同时检查 sys_msg 字面字符串），按新模板调整断言。

**注**：W2 写的 `test_mcp_media.py` 里 `test_generate_brief_*` 用例可能含 `assert "渠道运营" in trace["final_prompt"]` 这类断言，新 system 模板里"渠道运营"还在，应不破坏。如有更细的字面断言（如 `assert sys_msg.startswith("你是")`）可放宽到 `assert "渠道运营" in resp["trace"]["final_prompt"]`。本步骤运行后看具体哪些断言挂了，按需调整。

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/config/prompts/generate_brief.system.md `
        services/knowledge-engine/config/prompts/generate_brief.user.md `
        services/knowledge-engine/config/tool_models.yaml `
        services/knowledge-engine/app/mcp/tools/media.py `
        services/knowledge-engine/tests/test_mcp_media.py
git commit -m "feat(mcp): externalize generate_brief prompt + add kb_context arg (W3a T3)"
```

---

### 任务 4：compute_margin prompt 外置（M1 第四步）

**目的**：同 T3，把 `accounting.py:compute_margin` 内的 `sys_msg` / `user_msg` 搬到 `.md` 模板。

**Files:**
- Create: `services/knowledge-engine/config/prompts/compute_margin.system.md`
- Create: `services/knowledge-engine/config/prompts/compute_margin.user.md`
- Modify: `services/knowledge-engine/app/mcp/tools/accounting.py`（compute_margin 走 prompts.render）

- [ ] **Step 1：建 compute_margin 两份模板**

`services/knowledge-engine/config/prompts/compute_margin.system.md`:
```markdown
你是调味品工厂老板的财务助理。下面给你一组已算好的成本/利润数字（精确，不要重算）。

用 2-3 句话写解读：
1. 净利率落在什么档位（健康 / 边缘 / 亏本）
2. 成本结构里最大的占比是什么
3. 如果想提净利 5 个点，最现实的杠杆点是什么

说人话，不要废话，不要复述数字（数字老板已经看到了，你只解读）。
```

`services/knowledge-engine/config/prompts/compute_margin.user.md`:
```markdown
数据：
{breakdown_json}
```

- [ ] **Step 2：改 compute_margin 走 prompts.render**

打开 `services/knowledge-engine/app/mcp/tools/accounting.py`，找到 `compute_margin` 函数中构造 `sys_msg` / `user_msg` 的部分（约 161-169 行）：
```python
        sys_msg = (
            "你是调味品工厂老板的财务助理。下面给你一组已算好的成本/利润数字"
            "（精确,不要重算）。用 2-3 句话写解读：(a) 净利率落在什么档位"
            "（健康/边缘/亏本）；(b) 成本结构里最大的占比是什么；"
            "(c) 如果想提净利 5 个点,最现实的杠杆点是什么。"
            "说人话,不要废话,不要复述数字。"
        )
        user_msg = "数据:\n" + json.dumps(breakdown, ensure_ascii=False, indent=2)
        final_prompt = sys_msg + "\n\n" + user_msg
```

替换为：
```python
        sys_msg = prompts.render("compute_margin.system")
        user_msg = prompts.render(
            "compute_margin.user",
            breakdown_json=json.dumps(breakdown, ensure_ascii=False, indent=2),
        )
        final_prompt = sys_msg + "\n\n" + user_msg
```

文件顶部（约 5-12 行）import 段加：
```python
from app.mcp import prompts
```

- [ ] **Step 3：手测一次**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine python -c "
from app.mcp import prompts
print('=== system ===')
print(prompts.load('compute_margin.system'))
print('=== user (rendered) ===')
print(prompts.render('compute_margin.user', breakdown_json='{...}'))
"
```

Expected: system 显示完整文本；user 显示 `数据:\n{...}`。

- [ ] **Step 4：跑 compute_margin 测试看不破坏**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_accounting.py -v"
```

Expected: 全 PASS。同 T3 Step 5 注：如有字面断言挂了，放宽到关键词包含。

- [ ] **Step 5：commit**

```powershell
git add services/knowledge-engine/config/prompts/compute_margin.system.md `
        services/knowledge-engine/config/prompts/compute_margin.user.md `
        services/knowledge-engine/app/mcp/tools/accounting.py `
        services/knowledge-engine/tests/test_mcp_accounting.py
git commit -m "feat(mcp): externalize compute_margin prompt (W3a T4)"
```

---

### 任务 5：prompt_constraints.py 切 .md 加载（M1 收尾）

**目的**：`prompt_constraints.py` 当前是写死的 `ANTI_AI_HUMAN_VOICE = """..."""` 字面量。改成从 `prompts.load("anti_ai_voice")` 加载，保 `ANTI_AI_HUMAN_VOICE` 名（`ai_hub_client.py` 还在 import 这个名）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/prompt_constraints.py`

- [ ] **Step 1：写一个测试断言两点：(a) ANTI_AI_HUMAN_VOICE 仍存在；(b) 内容来自 .md（改 .md 后变更）**

`services/knowledge-engine/tests/test_mcp_prompts.py` 末尾追加：
```python
def test_anti_ai_voice_loaded_from_md():
    """prompt_constraints.ANTI_AI_HUMAN_VOICE 应从 .md 文件加载（不是字面量）。"""
    from app.mcp import prompt_constraints

    # 内容应该完整含三段标题
    assert "说人话" in prompt_constraints.ANTI_AI_HUMAN_VOICE
    assert "反幻觉" in prompt_constraints.ANTI_AI_HUMAN_VOICE
    assert "去 AI 化" in prompt_constraints.ANTI_AI_HUMAN_VOICE
    # 与直接 prompts.load 加载结果一致
    assert prompt_constraints.ANTI_AI_HUMAN_VOICE == P.load("anti_ai_voice")
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_prompts.py::test_anti_ai_voice_loaded_from_md -v"
```

Expected: PASS（如果 anti_ai_voice.md T1 已建对内容） 或 FAIL（如果 prompt_constraints 字面量与 .md 内容不一致）。

如果 PASS：直接进 Step 3 改实现仍要做（让源头是 .md 不是字面量）。

如果 FAIL（不一致）：先看哪边为准；以 anti_ai_voice.md 为准（T1 建的是完整版）。

- [ ] **Step 3：改 prompt_constraints.py 从 .md 加载**

打开 `services/knowledge-engine/app/mcp/prompt_constraints.py`，整个文件替换为：
```python
"""全局写作风格强制约束（design doc §2.8 / feedback_writing_style.md）。

W3a 起：内容外置到 `config/prompts/anti_ai_voice.md`，本模块只导出 `ANTI_AI_HUMAN_VOICE`
名做后向兼容（ai_hub_client 等模块还在 import 这个名）。改文案直接编辑 .md，
KE 容器 restart 即生效（prompts.load 自带 mtime 缓存）。
"""
from __future__ import annotations

from app.mcp import prompts as _prompts


# 模块级常量：每次 import 时加载一次。
# 改 anti_ai_voice.md 后需 restart KE 容器或在调用方主动 invalidate。
# 实际上 ai_hub_client.chat 每次都走 import，prompts.load 内部 mtime 缓存
# 自动反映 .md 变更，所以热改文案不需要 restart 容器，但 ANTI_AI_HUMAN_VOICE
# 这个模块级名是首次 import 的快照——为保证热改生效，改成 property-like
# 模式：暴露一个 callable，但保留旧名兼容。
def _get_anti_ai_voice() -> str:
    return _prompts.load("anti_ai_voice")


# 后向兼容：旧代码 import ANTI_AI_HUMAN_VOICE 当字符串用。
# 这里改成 module-level __getattr__ 实现"按需加载，自带热更新"。
def __getattr__(name: str) -> str:
    if name == "ANTI_AI_HUMAN_VOICE":
        return _get_anti_ai_voice()
    raise AttributeError(f"module 'app.mcp.prompt_constraints' has no attribute {name!r}")
```

**关键设计**：
- 用 module-level `__getattr__`（PEP 562），让 `from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE` 每次重新加载（命中 prompts.load 的 mtime cache）
- 不缓存到 module top-level 常量，避免热改 .md 后旧 import 仍是旧文案

- [ ] **Step 4：测试该模式可用**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine python -c "
from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
print('len:', len(ANTI_AI_HUMAN_VOICE))
print('contains shuorenhua:', '说人话' in ANTI_AI_HUMAN_VOICE)
"
```

Expected: `len: > 400`（anti_ai_voice.md 大致 600+ 字符）；`contains 说人话: True`。

- [ ] **Step 5：跑 ai_hub_client 联动测试**

`ai_hub_client.chat(enforce_human_voice=True)` 内部 import 这个名，跑 W2 已写的测试看是否 OK：

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_prompts.py tests/test_mcp_media.py tests/test_mcp_accounting.py -v"
```

Expected: 全 PASS。

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/prompt_constraints.py `
        services/knowledge-engine/tests/test_mcp_prompts.py
git commit -m "feat(mcp): prompt_constraints loads anti_ai_voice from .md (W3a T5)"
```

---

### 任务 6：human_gate.py 真实现（M4 第一步）

**目的**：`human_gate.py` 当前是 stub（调到时抛 NotImplementedError）。本 task 实现真 gate：写 `mcp.human_gates` 表 → DB poll 等 `decision is not null` → 返回决策；超时算 rejected。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/human_gate.py`（stub → 真实现）
- Create: `services/knowledge-engine/tests/test_mcp_human_gate.py`

- [ ] **Step 1：写 gate 集成测试（先红）**

`services/knowledge-engine/tests/test_mcp_human_gate.py`:
```python
"""W3a T6：human_gate 真实现集成测（hits dev DB）。"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from app.database import get_pool, init_pool, close_pool
from app.mcp import human_gate


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


async def _create_pending_tool_call(pool) -> str:
    tc_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval) "
        "VALUES ($1, '_smoke_gate_test', '{}'::jsonb, 'pending', TRUE)",
        uuid.UUID(tc_id),
    )
    return tc_id


async def _set_decision(pool, tool_call_id: str, decision: str, note: str = "") -> None:
    """模拟外部进程（CLI / /inbox）批/驳的写入。"""
    await pool.execute(
        "UPDATE mcp.human_gates SET decision=$1, decision_note=$2, decided_at=NOW() "
        "WHERE tool_call_id=$3",
        decision, note, uuid.UUID(tool_call_id),
    )


@pytest.mark.asyncio
async def test_smoke_gate_approved():
    """approved 路径：写 gate → 外部批 → request_approval 返 approved。"""
    pool = get_pool()
    tc_id = await _create_pending_tool_call(pool)

    async def _approve_after_short_delay():
        await asyncio.sleep(0.3)
        await _set_decision(pool, tc_id, "approved", "看起来 OK")

    approve_task = asyncio.create_task(_approve_after_short_delay())

    decision = await human_gate.request_approval(
        tool_call_id=tc_id,
        summary="_smoke gate test approved",
        timeout_seconds=5,
        poll_interval_seconds=0.1,
    )
    await approve_task

    assert decision["decision"] == "approved"
    assert decision["decision_note"] == "看起来 OK"

    await pool.execute("DELETE FROM mcp.human_gates WHERE tool_call_id=$1", uuid.UUID(tc_id))
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", uuid.UUID(tc_id))


@pytest.mark.asyncio
async def test_smoke_gate_rejected():
    pool = get_pool()
    tc_id = await _create_pending_tool_call(pool)

    async def _reject_after_short_delay():
        await asyncio.sleep(0.3)
        await _set_decision(pool, tc_id, "rejected", "不行")

    reject_task = asyncio.create_task(_reject_after_short_delay())

    decision = await human_gate.request_approval(
        tool_call_id=tc_id,
        summary="_smoke gate test rejected",
        timeout_seconds=5,
        poll_interval_seconds=0.1,
    )
    await reject_task

    assert decision["decision"] == "rejected"
    assert decision["decision_note"] == "不行"

    await pool.execute("DELETE FROM mcp.human_gates WHERE tool_call_id=$1", uuid.UUID(tc_id))
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", uuid.UUID(tc_id))


@pytest.mark.asyncio
async def test_smoke_gate_timeout():
    """timeout 内无人批 → 返 rejected (timeout 当 reject 处理)。"""
    pool = get_pool()
    tc_id = await _create_pending_tool_call(pool)

    decision = await human_gate.request_approval(
        tool_call_id=tc_id,
        summary="_smoke gate test timeout",
        timeout_seconds=1,
        poll_interval_seconds=0.1,
    )
    assert decision["decision"] == "rejected"
    assert "timeout" in (decision.get("decision_note") or "").lower()

    # 验证 DB 也写了 timeout 标记
    row = await pool.fetchrow(
        "SELECT decision, decision_note FROM mcp.human_gates WHERE tool_call_id=$1",
        uuid.UUID(tc_id),
    )
    assert row is not None
    assert row["decision"] == "rejected"

    await pool.execute("DELETE FROM mcp.human_gates WHERE tool_call_id=$1", uuid.UUID(tc_id))
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", uuid.UUID(tc_id))
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_human_gate.py -v"
```

Expected: 3 个 case 都 FAIL，原因：`NotImplementedError: Human Gate 在 W1 未实现。`

- [ ] **Step 3：实现 human_gate.py**

整个文件替换为：
```python
"""W3a T6：Human Gate 真实现（design doc §5）。

行为：
1. `request_approval` 写一行 mcp.human_gates（decision=NULL）
2. 起 DB poll 循环，等 `decision IS NOT NULL`
3. 超时（默认 timeout_seconds 秒）→ 写 decision=rejected,note=timeout，返 rejected
4. 调用方（audit.py wrapper）拿到 decision 决定继续/中止

不做：前端 /inbox（W3a 起步走 CLI 批），多用户隔离（个人自用）

CLI 配套：`python -m app.mcp.cli_approve list/approve/reject/tail`（T7 落地）
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TypedDict

from app.database import get_pool

logger = logging.getLogger(__name__)


class GateDecision(TypedDict):
    decision: str          # "approved" | "rejected"
    decision_note: str | None


async def request_approval(
    *,
    tool_call_id: str,
    summary: str,
    timeout_seconds: int = 3600,
    poll_interval_seconds: float = 2.0,
) -> GateDecision:
    """写 human_gates → 等批/驳/超时 → 返决策。

    Args:
        tool_call_id: 关联的 mcp.tool_calls.id（uuid str）
        summary: 给人看的摘要（CLI list / 未来 /inbox 卡片显示）
        timeout_seconds: 超时（默认 3600 = 1h）；超时算 rejected
        poll_interval_seconds: DB poll 间隔（默认 2 秒；测试用 0.1）

    Returns:
        {"decision": "approved" | "rejected", "decision_note": str | None}
    """
    pool = get_pool()
    gate_id = uuid.uuid4()

    # 1. 写 gate（pending = decision IS NULL）
    await pool.execute(
        "INSERT INTO mcp.human_gates (id, tool_call_id, summary, timeout_seconds, decision) "
        "VALUES ($1, $2, $3, $4, NULL)",
        gate_id, uuid.UUID(tool_call_id), summary, int(timeout_seconds),
    )
    logger.info("human gate created id=%s tool_call_id=%s timeout=%ds",
                gate_id, tool_call_id, timeout_seconds)

    # 2. poll 等决定
    elapsed = 0.0
    while elapsed < timeout_seconds:
        row = await pool.fetchrow(
            "SELECT decision, decision_note FROM mcp.human_gates WHERE id=$1",
            gate_id,
        )
        if row and row["decision"] is not None:
            logger.info("human gate decided id=%s decision=%s", gate_id, row["decision"])
            return {
                "decision": row["decision"],
                "decision_note": row["decision_note"],
            }
        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds

    # 3. 超时 → 标 rejected,note=timeout（让 CLI list 看到结果，不留孤儿）
    await pool.execute(
        "UPDATE mcp.human_gates SET decision='rejected', "
        "decision_note=COALESCE(decision_note,'') || '[timeout]', decided_at=NOW() "
        "WHERE id=$1 AND decision IS NULL",
        gate_id,
    )
    logger.warning("human gate timeout id=%s after %ds", gate_id, timeout_seconds)
    return {"decision": "rejected", "decision_note": "timeout"}


async def list_pending() -> list[dict]:
    """列出未决定的 gate（CLI 用）。"""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT g.id, g.tool_call_id, g.summary, g.timeout_seconds, g.created_at,
               t.tool_name, t.args
          FROM mcp.human_gates g
          JOIN mcp.tool_calls t ON t.id = g.tool_call_id
         WHERE g.decision IS NULL
         ORDER BY g.created_at ASC
        """
    )
    return [dict(r) for r in rows]


async def approve(gate_id: str, note: str = "") -> bool:
    """批一条 gate。返回是否成功（False = gate 不存在或已决定）。"""
    pool = get_pool()
    rec = await pool.fetchrow(
        "UPDATE mcp.human_gates SET decision='approved', decision_note=$1, decided_at=NOW() "
        "WHERE id=$2 AND decision IS NULL RETURNING id",
        note, uuid.UUID(gate_id),
    )
    return rec is not None


async def reject(gate_id: str, note: str = "") -> bool:
    pool = get_pool()
    rec = await pool.fetchrow(
        "UPDATE mcp.human_gates SET decision='rejected', decision_note=$1, decided_at=NOW() "
        "WHERE id=$2 AND decision IS NULL RETURNING id",
        note, uuid.UUID(gate_id),
    )
    return rec is not None
```

- [ ] **Step 4：跑测试**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_human_gate.py -v"
```

Expected: 3/3 PASS。

注：超时 test 用 timeout_seconds=1 + poll 0.1，理论上 1.0-1.2 秒内返。如 CI 慢偶发 fail，把 timeout_seconds 调到 2，poll 0.2。

- [ ] **Step 5：audit.py 删 W1 stub 兜底分支**

打开 `services/knowledge-engine/app/mcp/audit.py`，找到（约 78-100 行）：
```python
            if require_approval:
                try:
                    summary = summary_fn(args_dict) if summary_fn else f"{tool_name}({args_dict})"
                    decision = await human_gate.request_approval(
                        tool_call_id=tool_call_id,
                        summary=summary,
                        timeout_seconds=timeout_seconds or 3600,
                    )
                    if decision["decision"] != "approved":
                        await _finalize_error(pool, tool_call_id, "rejected_by_user", start)
                        return {
                            "ok": False,
                            "error": "rejected_by_user",
                            "note": decision.get("decision_note"),
                        }
                except NotImplementedError as exc:
                    logger.warning("Human Gate stub hit (W1): %s", exc)
                    await _finalize_error(pool, tool_call_id, "human_gate_unavailable", start)
                    return {
                        "ok": False,
                        "error": "human_gate_unavailable",
                        "hint": "Human Gate 在 W1 未启用，所有 W1 tool 必须 require_approval=False",
                    }
```

替换为：
```python
            if require_approval:
                summary = summary_fn(args_dict) if summary_fn else f"{tool_name}({args_dict})"
                decision = await human_gate.request_approval(
                    tool_call_id=tool_call_id,
                    summary=summary,
                    timeout_seconds=timeout_seconds or 3600,
                )
                if decision["decision"] != "approved":
                    await _finalize_error(pool, tool_call_id, "rejected_by_user", start)
                    return {
                        "ok": False,
                        "error": "rejected_by_user",
                        "note": decision.get("decision_note"),
                    }
```

理由：W1 stub 已被真实现替换，NotImplementedError 路径不再需要。

- [ ] **Step 6：跑 audit 测试看不破坏**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_audit.py -v"
```

Expected: 全 PASS。如有用例断言 `human_gate_unavailable`（W1 写的），改为新断言 `rejected_by_user` + 模拟外部 reject 写入。

- [ ] **Step 7：commit**

```powershell
git add services/knowledge-engine/app/mcp/human_gate.py `
        services/knowledge-engine/app/mcp/audit.py `
        services/knowledge-engine/tests/test_mcp_human_gate.py `
        services/knowledge-engine/tests/test_mcp_audit.py
git commit -m "feat(mcp): human_gate real impl with DB poll (W3a T6)"
```

---

### 任务 7：cli_approve CLI（M4 第二步）

**目的**：建一个 CLI 给老板批/驳 pending human_gates。完全不上前端 /inbox（YAGNI，个人自用，CLI 已足够）。

设计：
- `python -m app.mcp.cli_approve list` —— 列所有 pending（id / tool_name / summary / 等待时长）
- `python -m app.mcp.cli_approve approve <gate_id_or_short_id> [--note "..."]`
- `python -m app.mcp.cli_approve reject <gate_id_or_short_id> [--note "..."]`
- `python -m app.mcp.cli_approve tail` —— 持续显示 pending（每 5s 刷新），方便老板挂着等
- short_id：gate_id uuid 前 8 位（不模糊）；list 输出时显示 short_id 让批的时候不用全 uuid

**Files:**
- Create: `services/knowledge-engine/app/mcp/cli_approve.py`

- [ ] **Step 1：实现 cli_approve.py**

`services/knowledge-engine/app/mcp/cli_approve.py`:
```python
"""W3a T7：human_gates CLI 批/驳/列/tail。

用法（容器内）：
    docker exec -it omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.cli_approve <cmd> [args]"

命令：
    list                            列所有 pending gate
    approve <id> [--note "..."]    批一条
    reject  <id> [--note "..."]    驳一条
    tail [--interval 5]             持续显示 pending（Ctrl-C 退出）

<id> 接受完整 uuid 或前 8 位 short_id（如多条 short_id 撞同一前缀，CLI 会列冲突让你补全）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid as _uuid
from datetime import datetime, timezone

from app.database import init_pool, close_pool, get_pool
from app.mcp import human_gate


def _short(gate_id) -> str:
    return str(gate_id)[:8]


def _fmt_age(created_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = now - created_at
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60}s"
    return f"{s // 3600}h{(s % 3600) // 60}m"


async def _resolve_id(short_or_full: str) -> str | None:
    """short_id (8 chars) 或全 uuid → 全 uuid。返回 None 表 not found / ambiguous。"""
    pool = get_pool()
    if len(short_or_full) >= 32:
        # 全 uuid（去掉横杠后 32 位）
        try:
            full = str(_uuid.UUID(short_or_full))
            row = await pool.fetchrow(
                "SELECT id FROM mcp.human_gates WHERE id=$1 AND decision IS NULL",
                _uuid.UUID(full),
            )
            return str(row["id"]) if row else None
        except ValueError:
            return None

    # short_id：扫 pending 找前缀匹配
    rows = await pool.fetch(
        "SELECT id::text AS id_str FROM mcp.human_gates WHERE decision IS NULL"
    )
    matches = [r["id_str"] for r in rows if r["id_str"].startswith(short_or_full)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"[ambiguous] short_id '{short_or_full}' 匹配多条：")
        for m in matches:
            print(f"  {m}")
        return None
    return None


async def cmd_list() -> int:
    pending = await human_gate.list_pending()
    if not pending:
        print("（无待批）")
        return 0
    print(f"{'short':9} {'tool':28} {'age':>8}  summary")
    print("-" * 80)
    for g in pending:
        sid = _short(g["id"])
        tool = (g["tool_name"] or "?")[:28]
        age = _fmt_age(g["created_at"])
        summary = (g["summary"] or "")[:60]
        print(f"{sid:9} {tool:28} {age:>8}  {summary}")
    return 0


async def cmd_approve(short_or_full: str, note: str) -> int:
    full = await _resolve_id(short_or_full)
    if not full:
        print(f"[not found] {short_or_full}", file=sys.stderr)
        return 1
    ok = await human_gate.approve(full, note)
    print(f"approved {full[:8]}" if ok else f"[failed] gate already decided?", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


async def cmd_reject(short_or_full: str, note: str) -> int:
    full = await _resolve_id(short_or_full)
    if not full:
        print(f"[not found] {short_or_full}", file=sys.stderr)
        return 1
    ok = await human_gate.reject(full, note)
    print(f"rejected {full[:8]}" if ok else f"[failed] gate already decided?", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


async def cmd_tail(interval: float) -> int:
    """持续显示 pending（每 interval 秒刷新一次）。"""
    try:
        while True:
            print("\033[2J\033[H", end="")  # clear + home
            print(f"[{datetime.now().strftime('%H:%M:%S')}] omni human gate tail")
            await cmd_list()
            await asyncio.sleep(interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 0


async def _main() -> int:
    ap = argparse.ArgumentParser(prog="cli_approve")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列 pending gates")
    pa = sub.add_parser("approve", help="批一条 gate")
    pa.add_argument("id")
    pa.add_argument("--note", default="")
    pr = sub.add_parser("reject", help="驳一条 gate")
    pr.add_argument("id")
    pr.add_argument("--note", default="")
    pt = sub.add_parser("tail", help="持续显示 pending")
    pt.add_argument("--interval", type=float, default=5.0)

    args = ap.parse_args()
    await init_pool()
    try:
        if args.cmd == "list":
            return await cmd_list()
        if args.cmd == "approve":
            return await cmd_approve(args.id, args.note)
        if args.cmd == "reject":
            return await cmd_reject(args.id, args.note)
        if args.cmd == "tail":
            return await cmd_tail(args.interval)
        return 2
    finally:
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
```

- [ ] **Step 2：手测一次（无 pending 时）**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.cli_approve list"
```

Expected: `（无待批）`

- [ ] **Step 3：手测一次（造一条 pending 测 list/approve）**

```powershell
docker exec omni-knowledge-engine python -c '
import asyncio, uuid
from app.database import init_pool, close_pool, get_pool

async def main():
    await init_pool()
    pool = get_pool()
    tc_id = uuid.uuid4()
    g_id = uuid.uuid4()
    await pool.execute("INSERT INTO mcp.tool_calls(id,tool_name,args,status,require_approval) VALUES($1,$2,$3::jsonb,$4,$5)", tc_id, "_smoke_cli", "{}", "pending", True)
    await pool.execute("INSERT INTO mcp.human_gates(id,tool_call_id,summary,timeout_seconds) VALUES($1,$2,$3,$4)", g_id, tc_id, "_smoke_cli test", 60)
    print("created gate", str(g_id)[:8])
    await close_pool()

asyncio.run(main())
'

# 现在 list 应该看到一条
docker exec omni-knowledge-engine python -m app.mcp.cli_approve list
```

Expected list 输出（举例）:
```
short     tool                          age  summary
--------------------------------------------------------------------------------
abc12345  _smoke_cli                    3s   _smoke_cli test
```

- [ ] **Step 4：批掉它**

```powershell
# 用上面 short id 替换 abc12345
docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <short_id> --note "手测 OK"
```

Expected: `approved <short_id>`

```powershell
# 再 list
docker exec omni-knowledge-engine python -m app.mcp.cli_approve list
```

Expected: `（无待批）`

- [ ] **Step 5：清测试数据**

```powershell
docker exec omni-knowledge-engine python -c "
import asyncio
from app.database import init_pool, close_pool, get_pool

async def main():
    await init_pool()
    pool = get_pool()
    await pool.execute(\"DELETE FROM mcp.human_gates WHERE summary LIKE '_smoke_cli%'\")
    await pool.execute(\"DELETE FROM mcp.tool_calls WHERE tool_name LIKE '_smoke_cli%'\")
    await close_pool()

asyncio.run(main())
"
```

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/cli_approve.py
git commit -m "feat(mcp): cli_approve list/approve/reject/tail (W3a T7)"
```

---

### 任务 8：record_cost / disable_cost_item tool（M3 + Gate 联调）

**目的**：让老板能用对话录入成本数据（accounting.cost_items 表写入）。两个 tool 都 `require_approval=True`，走 Gate（写入是不可逆动作）。

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/cost_admin.py`
- Create: `services/knowledge-engine/tests/test_mcp_cost_admin.py`
- Modify: `services/knowledge-engine/app/mcp/server.py`（注册）

- [ ] **Step 1：写 cost_admin 测试**

`services/knowledge-engine/tests/test_mcp_cost_admin.py`:
```python
"""W3a T8：cost_admin tools 集成测（hits dev DB）。"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from app.database import get_pool, init_pool, close_pool
from app.mcp import human_gate as _hg


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def _approve_immediately(monkeypatch):
    """测试用 monkey patch：让 request_approval 立刻返 approved。"""
    async def _fake_approve(*, tool_call_id, summary, timeout_seconds=3600, poll_interval_seconds=2.0):
        return {"decision": "approved", "decision_note": "auto-approved in test"}
    monkeypatch.setattr(_hg, "request_approval", _fake_approve)
    yield


@pytest_asyncio.fixture
async def _reject_immediately(monkeypatch):
    async def _fake_reject(*, tool_call_id, summary, timeout_seconds=3600, poll_interval_seconds=2.0):
        return {"decision": "rejected", "decision_note": "auto-rejected in test"}
    monkeypatch.setattr(_hg, "request_approval", _fake_reject)
    yield


@pytest.mark.asyncio
async def test_smoke_record_cost_approved_inserts(_approve_immediately):
    """approved → cost_items 多 1 行。"""
    from app.mcp.tools.cost_admin import record_cost

    pool = get_pool()
    item_name = f"_smoke_record_{uuid.uuid4().hex[:8]}"
    resp = await record_cost(
        sku_id=None,
        category="logistics",
        item_name=item_name,
        unit_cost="5.50",
        currency="CNY",
        unit="次",
        quantity_per_unit="1",
        vendor="顺丰",
        valid_from="2026-05-05",
        valid_to=None,
        notes="单元测试",
    )
    assert resp["ok"] is True
    inserted_id = resp["result"]["cost_item_id"]
    assert inserted_id

    row = await pool.fetchrow(
        "SELECT category, item_name, unit_cost, vendor FROM accounting.cost_items WHERE id=$1",
        uuid.UUID(inserted_id),
    )
    assert row["category"] == "logistics"
    assert row["item_name"] == item_name
    assert str(row["unit_cost"]) == "5.5000"
    assert row["vendor"] == "顺丰"

    # 清理
    await pool.execute(
        "DELETE FROM accounting.cost_items WHERE id=$1", uuid.UUID(inserted_id)
    )


@pytest.mark.asyncio
async def test_smoke_record_cost_rejected_does_not_insert(_reject_immediately):
    """rejected → cost_items 没多行。"""
    from app.mcp.tools.cost_admin import record_cost

    pool = get_pool()
    item_name = f"_smoke_record_rej_{uuid.uuid4().hex[:8]}"
    before = await pool.fetchval(
        "SELECT COUNT(*) FROM accounting.cost_items WHERE item_name=$1", item_name
    )
    resp = await record_cost(
        sku_id=None,
        category="logistics",
        item_name=item_name,
        unit_cost="5.5",
    )
    assert resp["ok"] is False
    assert resp["error"] == "rejected_by_user"

    after = await pool.fetchval(
        "SELECT COUNT(*) FROM accounting.cost_items WHERE item_name=$1", item_name
    )
    assert after == before


@pytest.mark.asyncio
async def test_smoke_disable_cost_item_approved(_approve_immediately):
    """disable 走 Gate；approved 后行 is_active=False。"""
    from app.mcp.tools.cost_admin import disable_cost_item

    pool = get_pool()
    # 先插一条
    item_id = uuid.uuid4()
    item_name = f"_smoke_disable_{uuid.uuid4().hex[:8]}"
    await pool.execute(
        "INSERT INTO accounting.cost_items "
        "  (id, sku_id, category, item_name, unit_cost) "
        "VALUES ($1, NULL, 'logistics', $2, 1.0)",
        item_id, item_name,
    )

    resp = await disable_cost_item(cost_item_id=str(item_id), reason="测试")
    assert resp["ok"] is True
    assert resp["result"]["disabled"] is True

    row = await pool.fetchrow(
        "SELECT is_active FROM accounting.cost_items WHERE id=$1", item_id
    )
    assert row["is_active"] is False

    await pool.execute("DELETE FROM accounting.cost_items WHERE id=$1", item_id)


@pytest.mark.asyncio
async def test_smoke_record_cost_invalid_category(_approve_immediately):
    """category 不在 product/logistics/partner_quote 内 → 返 ok=False, 不写入。"""
    from app.mcp.tools.cost_admin import record_cost

    resp = await record_cost(
        sku_id=None,
        category="unknown_category",
        item_name="_smoke_invalid_cat",
        unit_cost="1",
    )
    assert resp["ok"] is False
    assert resp["error"] == "invalid_category"
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_cost_admin.py -v"
```

Expected: `ImportError: cannot import name 'record_cost' from 'app.mcp.tools.cost_admin'` 或 `ModuleNotFoundError`.

- [ ] **Step 3：实现 cost_admin.py**

`services/knowledge-engine/app/mcp/tools/cost_admin.py`:
```python
"""W3a T8：cost_items 写入 tools（require_approval=True）。

W2 落地的 query_costs / compute_margin 是只读；W3a 加这两个 T 类 tool 让老板
用对话录入成本（不再依赖前端表单/SQL 直插）：

- record_cost：插一行 accounting.cost_items
- disable_cost_item：软删（is_active=FALSE）

两个都走 Human Gate（CLI 批），因为是不可逆 / 影响利润计算的动作。
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp


_VALID_CATEGORIES = {"product", "logistics", "partner_quote"}


def _record_cost_summary(args: dict) -> str:
    """Gate 卡片摘要：录入 SKU-X 的 product 类成本「瓶身」¥0.5/件 × 24 件"""
    parts = [
        f"录入 {args.get('category', '?')} 类成本「{args.get('item_name', '?')}」",
        f"¥{args.get('unit_cost', '?')}/{args.get('unit', '件')}",
    ]
    if args.get("sku_id"):
        parts.insert(0, f"SKU={args['sku_id']}")
    if args.get("vendor"):
        parts.append(f"供应商={args['vendor']}")
    return "；".join(parts)


def _disable_cost_summary(args: dict) -> str:
    return f"停用 cost_item {args.get('cost_item_id', '?')[:8]}（{args.get('reason', '无 reason')}）"


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_record_cost_summary,
    timeout_seconds=3600,
)
async def record_cost(
    sku_id: str | None,
    category: str,
    item_name: str,
    unit_cost: str,
    currency: str = "CNY",
    unit: str = "件",
    quantity_per_unit: str = "1",
    vendor: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    notes: str | None = None,
) -> dict:
    """录一行 accounting.cost_items（require_approval=True，CLI 批后才写）。

    Args:
        sku_id: 绑定 SKU id；None = 共享成本（如全 SKU 物流费）
        category: product | logistics | partner_quote
        item_name: 成本项名（如「瓶身」「顺丰华东」）
        unit_cost: 单价（str 输入避 float 误差，如 "0.50"）
        currency: 默认 CNY
        unit: 单位（"件"/"次"/"箱"...）
        quantity_per_unit: 一个 unit 含多少个最小计量单位（如「一箱 24 瓶」= 24）
        vendor: 供应商
        valid_from: 起始日期 ISO（"2026-05-05"），默认今天
        valid_to: 截止日期 ISO；None = 长期有效
        notes: 备注

    Returns:
        {ok, result: {cost_item_id, ...}}
    """
    if category not in _VALID_CATEGORIES:
        return {
            "ok": False,
            "error": "invalid_category",
            "hint": f"category 必须是 {sorted(_VALID_CATEGORIES)} 之一，给的是 {category!r}",
        }

    try:
        unit_cost_dec = Decimal(unit_cost)
        qty_per_unit_dec = Decimal(quantity_per_unit)
    except (InvalidOperation, ValueError) as exc:
        return {
            "ok": False,
            "error": "invalid_decimal",
            "hint": f"unit_cost / quantity_per_unit 必须是数字 str: {exc}",
        }
    if unit_cost_dec < 0:
        return {"ok": False, "error": "invalid_decimal", "hint": "unit_cost 不能为负"}
    if qty_per_unit_dec <= 0:
        return {"ok": False, "error": "invalid_decimal", "hint": "quantity_per_unit 必须 > 0"}

    vf = date.fromisoformat(valid_from) if valid_from else date.today()
    vt = date.fromisoformat(valid_to) if valid_to else None

    pool = get_pool()
    new_id = uuid.uuid4()
    await pool.execute(
        """
        INSERT INTO accounting.cost_items
            (id, sku_id, category, item_name, unit_cost, currency, unit,
             quantity_per_unit, vendor, valid_from, valid_to, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """,
        new_id, sku_id, category, item_name, unit_cost_dec, currency, unit,
        qty_per_unit_dec, vendor, vf, vt, notes,
    )

    return {
        "ok": True,
        "result": {
            "cost_item_id": str(new_id),
            "sku_id": sku_id,
            "category": category,
            "item_name": item_name,
            "unit_cost": str(unit_cost_dec),
            "valid_from": vf.isoformat(),
        },
    }


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_disable_cost_summary,
    timeout_seconds=3600,
)
async def disable_cost_item(cost_item_id: str, reason: str = "") -> dict:
    """软删 cost_item（is_active=FALSE）。原行不删，保留历史。

    Args:
        cost_item_id: cost_items.id（uuid str）
        reason: 停用原因（写入 notes 末尾）
    """
    try:
        cid = uuid.UUID(cost_item_id)
    except ValueError:
        return {"ok": False, "error": "invalid_uuid", "hint": f"cost_item_id 不是合法 uuid: {cost_item_id}"}

    pool = get_pool()
    rec = await pool.fetchrow(
        """
        UPDATE accounting.cost_items
           SET is_active = FALSE,
               notes = COALESCE(notes, '') || $2
         WHERE id = $1 AND is_active = TRUE
         RETURNING id, item_name
        """,
        cid, f"\n[停用 reason: {reason}]" if reason else "\n[停用]",
    )
    if rec is None:
        return {
            "ok": False,
            "error": "cost_item_not_found_or_already_inactive",
            "hint": f"cost_item_id={cost_item_id} 不存在或已 is_active=FALSE",
        }

    return {
        "ok": True,
        "result": {
            "cost_item_id": str(rec["id"]),
            "item_name": rec["item_name"],
            "disabled": True,
        },
    }
```

- [ ] **Step 4：注册到 server.py**

打开 `services/knowledge-engine/app/mcp/server.py`，在 import block 末尾追加：
```python
from app.mcp.tools import cost_admin as _cost_admin  # noqa: E402, F401
```

完整 import 段应类似：
```python
from app.mcp.tools import sku as _sku  # noqa: E402, F401
from app.mcp.tools import kb as _kb    # noqa: E402, F401
from app.mcp.tools import briefs as _briefs  # noqa: E402, F401
from app.mcp.tools import accounting as _accounting  # noqa: E402, F401
from app.mcp.tools import media as _media_tools  # noqa: E402, F401
from app.mcp.tools import cost_admin as _cost_admin  # noqa: E402, F401  # W3a T8
```

- [ ] **Step 5：跑测试**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_cost_admin.py -v"
```

Expected: 4/4 PASS。

- [ ] **Step 6：手测一次（不 mock，走真 gate + CLI 批）**

终端 A（容器内挂 tail）：
```powershell
docker exec -it omni-knowledge-engine python -m app.mcp.cli_approve tail --interval 3
```

终端 B（手动调 record_cost，会卡 1h 等批；只是验证 Gate 触发）：
```powershell
docker exec omni-knowledge-engine python -c '
import asyncio
from app.mcp.tools.cost_admin import record_cost
print(asyncio.run(record_cost(sku_id=None, category="logistics", item_name="_smoke_e2e_sf_east", unit_cost="5.5", vendor="顺丰")))
'
```

终端 A 应在几秒内看到一条 pending 记录（summary：「录入 logistics 类成本「_smoke_e2e_sf_east」¥5.5/件；供应商=顺丰」）。

终端 C（批掉它）：
```powershell
# 用终端 A 看到的 short id
docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <short_id> --note "手测 OK"
```

终端 B 应在 ≤5s 内返 `{'ok': True, 'result': {...}}`，终端 A 看不到 pending 了。

清理：
```powershell
docker exec omni-knowledge-engine python -c '
import asyncio
from app.database import init_pool, close_pool, get_pool
async def main():
    await init_pool()
    await get_pool().execute("DELETE FROM accounting.cost_items WHERE item_name LIKE ''_smoke_%''")
    await close_pool()
asyncio.run(main())
'
```

- [ ] **Step 7：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/cost_admin.py `
        services/knowledge-engine/tests/test_mcp_cost_admin.py `
        services/knowledge-engine/app/mcp/server.py
git commit -m "feat(mcp): record_cost + disable_cost_item with Human Gate (W3a T8)"
```

---

### 任务 9：CSV 批量导入脚本（M3 nice-to-have，绕 Gate）

**目的**：老板有 30 条历史成本要录的话，用 record_cost 一条条批 Gate 太累。建一个 CLI 脚本读 CSV → 直接调内部 SQL（绕 Gate；脚本本身是老板手动触发的，不需要再批）。

**Files:**
- Create: `services/knowledge-engine/scripts/import_costs.py`
- Create: `services/knowledge-engine/scripts/cost_template.csv`
- Modify: `E:\agent\omni\docker-compose.yml`（knowledge-engine 加 `scripts:/app/scripts:rw` bind mount）

- [ ] **Step 1：建 CSV 模板**

`services/knowledge-engine/scripts/cost_template.csv`:
```csv
sku_id,category,item_name,unit_cost,currency,unit,quantity_per_unit,vendor,valid_from,valid_to,notes
,logistics,顺丰华东,5.5,CNY,次,1,顺丰,2026-01-01,,
,logistics,京东专线,3.8,CNY,次,1,京东物流,2026-01-01,,
SKU-367991-0001,product,瓶身,0.45,CNY,件,24,某玻璃厂,2026-01-01,,一箱 24 瓶
SKU-367991-0001,product,瓶盖,0.08,CNY,件,24,,2026-01-01,,
SKU-367991-0001,product,标签,0.05,CNY,件,1,,2026-01-01,,
SKU-367991-0001,product,主料,4.2,CNY,瓶,1,,2026-01-01,,
SKU-367991-0001,product,包装箱,1.8,CNY,箱,24,,2026-01-01,,
SKU-367991-0001,product,人工,0.3,CNY,瓶,1,,2026-01-01,,
```

- [ ] **Step 2：实现 import_costs.py**

`services/knowledge-engine/scripts/import_costs.py`:
```python
"""W3a T9：CSV 批量导入 accounting.cost_items（绕 Gate）。

为啥绕 Gate：老板手动跑这个脚本本身就是"批"动作；
record_cost 一条条批 Gate 累。

用法：
    docker exec -it omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python /app/scripts/import_costs.py /app/scripts/cost_template.csv"
    # 或：dry-run（只 print 不写）
    docker exec ... python /app/scripts/import_costs.py path.csv --dry-run

CSV 列：sku_id, category, item_name, unit_cost, currency, unit,
       quantity_per_unit, vendor, valid_from, valid_to, notes
（sku_id / vendor / valid_to / notes 可空）
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.database import init_pool, close_pool, get_pool


_VALID_CATS = {"product", "logistics", "partner_quote"}


def _parse_row(row: dict, line_no: int) -> dict | None:
    cat = (row.get("category") or "").strip()
    if cat not in _VALID_CATS:
        print(f"[line {line_no}] skip: bad category {cat!r}", file=sys.stderr)
        return None

    item_name = (row.get("item_name") or "").strip()
    if not item_name:
        print(f"[line {line_no}] skip: empty item_name", file=sys.stderr)
        return None

    try:
        unit_cost = Decimal((row.get("unit_cost") or "0").strip())
        qty_per_unit = Decimal((row.get("quantity_per_unit") or "1").strip() or "1")
    except Exception as exc:
        print(f"[line {line_no}] skip: bad number ({exc})", file=sys.stderr)
        return None

    vf_str = (row.get("valid_from") or "").strip()
    vf = date.fromisoformat(vf_str) if vf_str else date.today()
    vt_str = (row.get("valid_to") or "").strip()
    vt = date.fromisoformat(vt_str) if vt_str else None

    return {
        "id": uuid.uuid4(),
        "sku_id": (row.get("sku_id") or "").strip() or None,
        "category": cat,
        "item_name": item_name,
        "unit_cost": unit_cost,
        "currency": (row.get("currency") or "CNY").strip() or "CNY",
        "unit": (row.get("unit") or "件").strip() or "件",
        "quantity_per_unit": qty_per_unit,
        "vendor": (row.get("vendor") or "").strip() or None,
        "valid_from": vf,
        "valid_to": vt,
        "notes": (row.get("notes") or "").strip() or None,
    }


async def _main(csv_path: Path, dry_run: bool) -> int:
    if not csv_path.exists():
        print(f"csv not found: {csv_path}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # 1 是 header
            parsed = _parse_row(row, i)
            if parsed:
                rows.append(parsed)

    print(f"parsed {len(rows)} rows from {csv_path}")
    if dry_run:
        for r in rows:
            print(f"  [dry] {r['category']:14} {r['item_name']:20} ¥{r['unit_cost']}")
        return 0

    await init_pool()
    pool = get_pool()
    inserted = 0
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for r in rows:
                    await conn.execute(
                        """
                        INSERT INTO accounting.cost_items
                          (id, sku_id, category, item_name, unit_cost, currency,
                           unit, quantity_per_unit, vendor, valid_from, valid_to, notes)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        r["id"], r["sku_id"], r["category"], r["item_name"],
                        r["unit_cost"], r["currency"], r["unit"],
                        r["quantity_per_unit"], r["vendor"], r["valid_from"],
                        r["valid_to"], r["notes"],
                    )
                    inserted += 1
    finally:
        await close_pool()

    print(f"inserted {inserted} rows")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="import_costs")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(_main(args.csv, args.dry_run)))
```

- [ ] **Step 3：docker-compose 加 scripts bind mount**

打开 `E:\agent\omni\docker-compose.yml`，找到 knowledge-engine service 的 volumes 段（W1 已加了 `app/` `tests/` `config/` 三条 bind mount），追加：
```yaml
      - ./services/knowledge-engine/scripts:/app/scripts:rw
```

注：W1 chore `c3f8a9a` 加的 bind mount 在 `volumes:` 列表里，找到那段加。

- [ ] **Step 4：restart KE 容器拉新 mount**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" up -d --no-deps --force-recreate knowledge-engine
Start-Sleep -Seconds 8
```

- [ ] **Step 5：dry-run 测试**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python /app/scripts/import_costs.py /app/scripts/cost_template.csv --dry-run"
```

Expected: 看到 8 行 `[dry] ...` 输出。

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/scripts/ docker-compose.yml
git commit -m "feat(mcp): import_costs CSV bulk-import script (W3a T9)"
```

---

### 任务 10：gather_brief_context tool（M2 第一步）

**目的**：建一个辅助 tool，把 search_kb 3 类（authoritative + template + 同 sku 历史 brief）拼成结构化 `kb_context` 字符串，给 generate_brief 当 extra/kb context 用。

设计：
- 不调 LLM（纯检索 + 拼字符串），require_approval=False
- 走 `app.services.rag_chain.retrieve_multi_kb` 检索三组 KB（按 kb_role 筛）
- 拼出 markdown 格式的 `kb_context`，含每条 chunk 的来源标注
- 返 `{ok, result: {kb_context, sources}, next_step_hint(generate_brief, ...)}`

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/sop.py`
- Create: `services/knowledge-engine/tests/test_mcp_sop_orchestration.py`
- Modify: `services/knowledge-engine/app/mcp/server.py`（注册）

- [ ] **Step 1：写 gather_brief_context 测试**

`services/knowledge-engine/tests/test_mcp_sop_orchestration.py`:
```python
"""W3a T10：gather_brief_context tool 集成测（mock search_kb / list_kbs）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools import sop as _sop


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def _mock_kb_search(monkeypatch):
    """让 list_kbs 返 3 个 KB（每 role 一个），search 返固定 chunks。"""
    fake_kbs = [
        {"id": "kb-auth-1", "name": "抖店运营手册", "kb_role": "authoritative"},
        {"id": "kb-tpl-1", "name": "调味品爆款拆解", "kb_role": "template"},
        {"id": "kb-priv-1", "name": "公司产品介绍", "kb_role": "private_doc"},
    ]
    fake_chunks = [
        {"kb_id": "kb-tpl-1", "title": "酱油爆款拆解 #3",
         "content": "钩子结构：先抛痛点 → 给反差 → 报价格", "score": 0.92},
        {"kb_id": "kb-auth-1", "title": "抖店运营 - 钩子规范",
         "content": "前 3 秒必须有具体数字", "score": 0.88},
    ]

    async def fake_list_kbs():
        return fake_kbs

    async def fake_retrieve(query, kb_ids, **kw):
        # 只返从被传入 kb_ids 中的 chunks
        return [c for c in fake_chunks if c["kb_id"] in kb_ids]

    monkeypatch.setattr("app.services.ingestion.list_kbs", fake_list_kbs)
    monkeypatch.setattr("app.services.rag_chain.retrieve_multi_kb", fake_retrieve)
    yield


@pytest.mark.asyncio
async def test_smoke_gather_brief_context_basic(_mock_kb_search):
    resp = await _sop.gather_brief_context(
        sku_id="SKU-TEST-1",
        channel="douyin",
    )
    assert resp["ok"] is True
    ctx = resp["result"]["kb_context"]
    # 有分区标题
    assert "爆款拆解" in ctx or "template" in ctx.lower()
    assert "运营手册" in ctx or "authoritative" in ctx.lower()
    # sources 列表非空
    assert len(resp["result"]["sources"]) >= 2

    # next_step_hint 指向 generate_brief
    assert resp["next_step_hint"]["suggested_tool"] == "generate_brief"
    sa = resp["next_step_hint"]["suggested_args"]
    assert sa["sku_id"] == "SKU-TEST-1"
    assert sa["channel"] == "douyin"
    assert "kb_context" in sa
    assert sa["kb_context"] == ctx


@pytest.mark.asyncio
async def test_smoke_gather_brief_context_no_kb_match(monkeypatch):
    """没匹配到任何 chunk → kb_context 是个友好空提示，仍然 ok=True。"""
    async def fake_list_kbs():
        return []
    async def fake_retrieve(query, kb_ids, **kw):
        return []
    monkeypatch.setattr("app.services.ingestion.list_kbs", fake_list_kbs)
    monkeypatch.setattr("app.services.rag_chain.retrieve_multi_kb", fake_retrieve)

    resp = await _sop.gather_brief_context(sku_id="SKU-X", channel="douyin")
    assert resp["ok"] is True
    assert "无 KB 命中" in resp["result"]["kb_context"] or resp["result"]["kb_context"] == "（KB 检索无命中）"
    assert resp["result"]["sources"] == []
```

- [ ] **Step 2：跑测试看红**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_sop_orchestration.py -v"
```

Expected: `ImportError`.

- [ ] **Step 3：实现 sop.py**

`services/knowledge-engine/app/mcp/tools/sop.py`:
```python
"""W3a T10：sku 全链路 SOP 编排辅助 tool。

`gather_brief_context(sku_id, channel)`：
- 用 sku_id + channel 拼检索 query
- 按 kb_role 检索 3 类 KB：
  - authoritative（渠道运营手册类）
  - template（爆款拆解 / 钩子结构）
  - private_doc（公司产品/历史 brief 类）
- 拼成结构化 kb_context（markdown 子区段 + 引用标注）
- next_step_hint 指 generate_brief，suggested_args 含 kb_context

不调 LLM；require_approval=False（纯检索）。
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step
from app.services import ingestion, rag_chain


_ROLE_LABELS = {
    "authoritative": "【官方/运营手册】",
    "template": "【爆款拆解 / 模板】",
    "private_doc": "【公司产品 / 历史 brief】",
    "methodology": "【方法论】",
    "personal_log": "【个人录音】",
    "general": "【通用】",
}

_ROLES_FOR_BRIEF = ("authoritative", "template", "private_doc")


@tool_with_audit(mcp, require_approval=False)
async def gather_brief_context(
    sku_id: str,
    channel: str,
    top_k_per_role: int = 3,
) -> dict:
    """聚合三类 KB 上下文，给 generate_brief 喂料。

    Args:
        sku_id: SKU id（拼 query 用）
        channel: 渠道（拼 query 用）
        top_k_per_role: 每个 role 最多返几条 chunk（默认 3）

    Returns:
        {
            "ok": True,
            "result": {
                "kb_context": "## ... 拼好的 markdown",
                "sources": [{kb_id, title, score, role}, ...]
            },
            "next_step_hint": {
                "suggested_tool": "generate_brief",
                "suggested_args": {sku_id, channel, kb_context, extra_context: ""},
                "human_text": "用这堆上下文出 brief"
            }
        }
    """
    all_kbs = await ingestion.list_kbs()
    by_role: dict[str, list[str]] = {}
    name_map: dict[str, str] = {}
    for k in all_kbs:
        by_role.setdefault(k.get("kb_role") or "general", []).append(k["id"])
        name_map[k["id"]] = k.get("name", k["id"])

    query = f"{sku_id} {channel} 渠道 brief 钩子 卖点 分镜"

    sections: list[str] = []
    sources: list[dict] = []
    for role in _ROLES_FOR_BRIEF:
        ids = by_role.get(role) or []
        if not ids:
            continue
        try:
            hits = await rag_chain.retrieve_multi_kb(
                query, ids,
                top_k_per_kb=max(2, top_k_per_role // max(1, len(ids))),
                min_per_kb=0,
                score_threshold=0.0,
                total_limit=top_k_per_role,
                kb_name_map=name_map,
            )
        except TypeError:
            # retrieve_multi_kb 签名兼容（不同版本可能少 kw）
            hits = await rag_chain.retrieve_multi_kb(query, ids)
        if not hits:
            continue

        sections.append(f"### {_ROLE_LABELS.get(role, role)}")
        for h in hits[:top_k_per_role]:
            title = h.get("title") or h.get("kb_id") or "?"
            content = (h.get("content") or "").strip()
            sections.append(f"- 来源「{title}」：{content[:400]}")
            sources.append({
                "kb_id": h.get("kb_id"),
                "title": title,
                "score": h.get("score"),
                "role": role,
            })

    if not sections:
        kb_context = "（KB 检索无命中）"
    else:
        kb_context = "\n".join(sections)

    result = {
        "ok": True,
        "result": {"kb_context": kb_context, "sources": sources},
    }
    return attach_next_step(
        result,
        suggested_tool="generate_brief",
        suggested_args={
            "sku_id": sku_id,
            "channel": channel,
            "kb_context": kb_context,
            "extra_context": "",
        },
        human_text=(
            f"基于 {len(sources)} 条 KB 上下文出 brief；"
            f"如要加临时要求，往 extra_context 塞"
        ),
    )
```

- [ ] **Step 4：注册到 server.py**

打开 `services/knowledge-engine/app/mcp/server.py`，import block 末尾追加：
```python
from app.mcp.tools import sop as _sop  # noqa: E402, F401  # W3a T10
```

- [ ] **Step 5：跑测试**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_sop_orchestration.py -v"
```

Expected: 2/2 PASS.

- [ ] **Step 6：commit**

```powershell
git add services/knowledge-engine/app/mcp/tools/sop.py `
        services/knowledge-engine/tests/test_mcp_sop_orchestration.py `
        services/knowledge-engine/app/mcp/server.py
git commit -m "feat(mcp): gather_brief_context tool with KB role-based retrieval (W3a T10)"
```

---

### 任务 11：CLAUDE.md SOP 升级（M2 第二步）

**目的**：把 CLAUDE.md 现有的"5 步裸链路"升级为"带 KB grounding 的 SOP"。step 3 加 `gather_brief_context → generate_brief(..., kb_context=)` 这一对调用；同步加 cost 录入入口、调试三件套加 `omni-mcp-approve`、老板响应词加新场景。

**Files:**
- Modify: `E:\agent\omni\CLAUDE.md`

- [ ] **Step 1：替换 CLAUDE.md（保 W2 框架，增量加 W3a 内容）**

整个文件替换为：
```markdown
# omni-vibe Claude Code 指令

> 这文件是给 Claude Code（agent 主大脑）看的，不是产品文档。

## omni MCP server

omni 暴露 13 个 tool（W1 5 + W2 5 + W3a 3）：
- 查询：`list_skus`, `get_sku`, `list_kbs`, `search_kb`, `list_briefs`, `query_costs`
- 算账：`compute_margin`
- 编排辅助：`gather_brief_context`（W3a 新）
- 生成：`generate_brief`, `generate_image`, `generate_video`
- 写入（require_approval=True）：`record_cost`, `disable_cost_item`（W3a 新）

调用见 `services/knowledge-engine/app/mcp/tools/`。

## sku 出片标准链路（老板说"sku-X 全链路"时按此走）

> W3a 起：第 3 步从"裸 LLM"升级为"先 KB grounding 再 LLM"。

1. 调 `query_costs(sku_id)` 拿成本（如返空，提醒老板要么 `record_cost` 录入，要么 `python /app/scripts/import_costs.py` 批量导入）
2. 调 `compute_margin(sku_id, channel)` 算利润，给老板审；老板满意进 3
3. **brief 出片三步走**：
   3a. 调 `gather_brief_context(sku_id, channel)` 拿 KB 上下文（authoritative + template + private_doc 三类）
   3b. 调 `generate_brief(sku_id, channel, kb_context=<3a 返的>, extra_context=<老板临时要求>)` 出 brief
   3c. 给老板审 brief 的 result + sources（看 KB 引用命中是否合理）；老板满意进 4
4. 调 `generate_image(prompts=[3 个分镜 prompt], face_refs/product_refs)` 出 3 张分镜图，给老板审；老板满意进 5
5. 调 `generate_video(segments=[3 段 prompt + 首尾帧链], face_refs, product_refs)` 出 3 段视频，给老板下载

每步跑完把 result + trace + next_step_hint 都给老板看。**不要一气呵成跑完整套**——每步停下来等老板反馈。

## 老板响应词约定

| 老板说 | 含义 | Claude 应做 |
|---|---|---|
| OK / 继续 / 赞 / 通过 / 进下一步 | 当前 step 满意，进下一步 | 按 next_step_hint.suggested_tool + suggested_args 调下一个 tool |
| 重来 / 改 / 不行 / 重跑 | 当前 step 不满意 | 用同 tool 重调，参数照老板新说法改（如老板说"prompt 加 X"，把 X 加进 extra_context 或改 prompts/*.md） |
| 第 N 张重来 / 第 N 段重做 | 局部重跑 | 只重调那一段（generate_image 单独一个 prompt；generate_video 单独一个 segment） |
| 跳过 X / 不要这步 | 跳一步 | 不调 X，按链路下一步走 |
| 全链路 / 跑通 | 触发标准链路 | 从 step 1 query_costs 起按上面 5 步走，每步停下等老板反馈 |
| 录成本 / 加成本 / 录入物流费 | cost 数据录入 | 调 `record_cost(...)`，老板用 `python -m app.mcp.cli_approve approve <id>` 批 |
| KB 没命中 / KB 引用不对 | 3a 返回的上下文不好 | 看 sources 哪个 kb_role 弱，提示老板"补 X 类 KB" 或换 query 重调 gather_brief_context |
| 改 prompt / 改 brief 系统提示 | 改 prompt 不改代码 | 编辑 `services/knowledge-engine/config/prompts/<tool>.{system,user}.md`，KE 容器无需 restart（mtime 自检） |

## prompt 调整三通道（W3a 新）

老板"随时能调，越用越准"。三种通道并存：
1. **大改**：直接改 `config/prompts/<tool>.{system,user}.md`（永久生效）
2. **一次性**：`extra_context` 参数注入（`generate_brief(..., extra_context="这次主推健康")`，下次自动遗忘）
3. **结构化补料**：`kb_context` 参数（gather_brief_context 出，或老板手拼）

## 已知约束

- 不调 `run_sku_orch` —— 没这个 tool，编排靠对话
- LLM tool 必返 `trace` 字段，老板要看 final_prompt 才能调 prompt 重跑
- video 多段并发跑（asyncio.gather），typically 30-60s 每段；并发后总时间 ≈ 单段
- W2 5 个 LLM tool 不走 Human Gate；W3a 加的 `record_cost` / `disable_cost_item` 走 Gate（CLI 批）

## 调试三件套

- **容器内自检**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"` —— 应输出 13 项全 OK 的 tool 列表
- **审计表**：`docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT tool_name, status, duration_ms FROM mcp.tool_calls ORDER BY created_at DESC LIMIT 20"`
- **ai-provider-hub 状态**：`curl http://localhost:8001/api/v1/ai/providers`
- **Human Gate 批/驳**（W3a）：
  - 列待批：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve list`
  - 批：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve <short_id> --note "OK"`
  - 驳：`docker exec omni-knowledge-engine python -m app.mcp.cli_approve reject <short_id> --note "原因"`
  - 持续看：`docker exec -it omni-knowledge-engine python -m app.mcp.cli_approve tail`（Ctrl-C 退）
- **prompt 模板列表**：`docker exec omni-knowledge-engine python -c 'from app.mcp import prompts; [print(t) for t in prompts.list_templates()]'`
- **CSV 导入 cost_items**：`docker exec omni-knowledge-engine python /app/scripts/import_costs.py /app/scripts/cost_template.csv`（先 `--dry-run` 预演）
```

- [ ] **Step 2：测一下 doctor 描述匹配**

```powershell
docker exec omni-knowledge-engine python -m app.mcp.doctor
```

如果当前还是显示 `10 tools registered`：T12 会升 13；本 step 不阻塞。

- [ ] **Step 3：commit**

```powershell
git add CLAUDE.md
git commit -m "docs(claude.md): SOP with KB grounding + cli_approve in toolbox (W3a T11)"
```

---

### 任务 12：doctor.py 升 13 + prompt 文件存在性检查

**目的**：W3a 加 3 tool 后 doctor `expected_tools` 要升 13；同时加一个新 check：`config/prompts/` 关键文件存在性（避免老板手抖删模板而 generate_brief 跑炸）。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/doctor.py`

- [ ] **Step 1：改 doctor 升 13 + 加 prompt 文件 check**

打开 `services/knowledge-engine/app/mcp/doctor.py`，找到 `_check_tools_registered` 函数（约 84-105 行）：
```python
async def _check_tools_registered(report: DoctorReport) -> None:
    """FastMCP 3.x: mcp.list_tools() 是 async coroutine，必须 await。"""
    try:
        from app.mcp.server import mcp
        tools = await mcp.list_tools()
        # W1 5 + W2 5 = 10
        wanted = {
            # W1
            "list_skus", "get_sku", "search_kb", "list_kbs", "list_briefs",
            # W2
            "query_costs", "compute_margin",
            "generate_brief", "generate_image", "generate_video",
        }
```

把 `wanted` 集合扩成：
```python
        # W1 5 + W2 5 + W3a 3 = 13
        wanted = {
            # W1
            "list_skus", "get_sku", "search_kb", "list_kbs", "list_briefs",
            # W2
            "query_costs", "compute_margin",
            "generate_brief", "generate_image", "generate_video",
            # W3a
            "record_cost", "disable_cost_item", "gather_brief_context",
        }
```

在 `_check_mcp_http` 之前（约 108 行前）插入新 check：
```python
def _check_prompts(report: DoctorReport) -> None:
    """W3a：检 config/prompts/ 关键模板都在。"""
    try:
        from app.mcp import prompts as _p
        existing = set(_p.list_templates())
        wanted = {
            "anti_ai_voice",
            "generate_brief.system", "generate_brief.user",
            "compute_margin.system", "compute_margin.user",
            "channel_profiles/douyin",
            "channel_profiles/tmall",
            "channel_profiles/jd",
        }
        missing = wanted - existing
        report.checks.append(CheckResult(
            "prompt templates",
            not missing,
            f"missing={sorted(missing)}" if missing else f"all {len(wanted)} ok",
        ))
    except Exception as exc:
        report.checks.append(CheckResult("prompt templates", False, str(exc)))
```

在 `run` 函数里（约 131-139 行）调用顺序中加一行：
```python
async def run(*, skip_http: bool = False) -> DoctorReport:
    report = DoctorReport()
    await _check_db_pool(report)
    await _check_mcp_schema(report)
    _check_yaml(report)
    _check_prompts(report)         # W3a 新加
    await _check_tools_registered(report)
    if not skip_http:
        await _check_mcp_http(report)
    return report
```

- [ ] **Step 2：跑 doctor**

```powershell
docker compose -f "E:\agent\omni\docker-compose.yml" restart knowledge-engine
Start-Sleep -Seconds 6
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected:
```
omni MCP doctor 报告
  [OK  ] DB pool
  [OK  ] mcp schema tables: found 2/2
  [OK  ] tool_models.yaml: keys=[...]
  [OK  ] prompt templates: all 8 ok
  [OK  ] 13 tools registered: all 13 ok
  [OK  ] /mcp HTTP: status=200

结论：全绿 ✓
```

- [ ] **Step 3：commit**

```powershell
git add services/knowledge-engine/app/mcp/doctor.py
git commit -m "feat(mcp): doctor expected_tools=13 + prompt files check (W3a T12)"
```

---

### 任务 13：W3a e2e 验收（cost 录入 → margin → KB grounded brief）

**目的**：把 W3a 4 模块串起来跑一次老板侧 e2e。验收用 SKU-367991-0002（W2 e2e 同款），先用 CSV 导入几条成本，再串 query_costs → compute_margin → gather_brief_context → generate_brief 看 KB grounding 后 brief 质量。

**Files:**（仅 `.claude/settings.local.json` 累 grant；不写新代码）
- Modify: `E:\agent\omni\.claude\settings.local.json`（运行时累 grant）

- [ ] **Step 1：导入测试成本数据**

打开 `services/knowledge-engine/scripts/cost_template.csv`，把 `SKU-367991-0001` 全部替换为 W2 e2e 用的 sku id（如 `SKU-367991-0002`），保存。

```powershell
# dry-run 看一下
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python /app/scripts/import_costs.py /app/scripts/cost_template.csv --dry-run"
# 真导入
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python /app/scripts/import_costs.py /app/scripts/cost_template.csv"
```

Expected: `inserted 8 rows`（2 logistics + 6 product）。

- [ ] **Step 2：query_costs 验证非空**

在 Claude Code 主对话里说："查 SKU-367991-0002 的成本"。Claude 调 `query_costs(sku_id="SKU-367991-0002")`，应返 8 条（2 logistics + 6 product，含共享物流）。

如果 Claude Code 第一次见 `mcp__omni__query_costs`，会弹 grant 提示，按 "accept this session" 或 "always allow"。grant 入 `.claude/settings.local.json`。

- [ ] **Step 3：compute_margin 跑（这次有数据）**

老板说："算 SKU-367991-0002 在抖音渠道的利润"。Claude 调 `compute_margin(sku_id="SKU-367991-0002", channel="douyin")`。

期望 result 有 `breakdown` + `interpretation`（gemini 解读）。trace 里看 `final_prompt` 应来自 `compute_margin.system.md` + `compute_margin.user.md` 的拼接（不再是 Python 字面量字符串）。

老板审："OK 看着对" / "重算"。如老板说重算就调 `compute_margin(..., sale_price="X")` 或 `channel_fee_rate="0.X"`。

- [ ] **Step 4：gather_brief_context（第一次跑，看 KB 有没有命中）**

老板说："gather brief 上下文"或"准备出 brief"。Claude 调 `gather_brief_context(sku_id="SKU-367991-0002", channel="douyin")`。

期望返：`kb_context`（markdown 三段：authoritative / template / private_doc 命中的 chunks）+ `sources` 列表 + `next_step_hint(generate_brief, kb_context=...)`。

如果 sources 空：说明老板的 KB 还没建相应 role；W3a e2e 这一步可"接受 KB 检索无命中"——下一步 generate_brief 会用空 kb_context（模板里有 fallback "（未提供 KB 上下文）"）跑，对比 W2 e2e 看变化。

- [ ] **Step 5：generate_brief（带 kb_context）**

老板说："出 brief"。Claude 应按 next_step_hint 调 `generate_brief(sku_id="SKU-367991-0002", channel="douyin", kb_context=<step 4 返的>, extra_context="")`。

对比 W2 e2e：
- 如果 KB 有命中，brief 应能看到 KB 上下文影响（例如引用爆款拆解的钩子结构）
- trace 里 final_prompt 应含完整 sys + user（user 含 KB 上下文段）

老板审："OK，质量比 W2 e2e 好" / "kb_context 没用上 / 内容空" → 反馈记到 W3a 收尾说明里

- [ ] **Step 6：record_cost 走真 Gate 一次（验证 Gate + CLI 联动）**

老板说："录一条新成本：SKU-367991-0002 的纸盒，¥0.6/件"。Claude 调 `record_cost(sku_id="SKU-367991-0002", category="product", item_name="纸盒", unit_cost="0.6")`。

工具会卡住等批。老板开第二个终端：
```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.cli_approve list"
```

应看到一条 pending（summary 含「录入 product 类成本「纸盒」¥0.6/件」）。

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.cli_approve approve <short_id> --note 'OK'"
```

返 Claude Code 那边，record_cost 应在 ≤5s 内返成功。`query_costs` 再跑应能看到这条新行。

- [ ] **Step 7：清测试数据**

```powershell
docker exec omni-knowledge-engine python -c '
import asyncio
from app.database import init_pool, close_pool, get_pool
async def main():
    await init_pool()
    pool = get_pool()
    await pool.execute("DELETE FROM accounting.cost_items WHERE sku_id LIKE ''SKU-367991-%'' OR (sku_id IS NULL AND vendor IN (''顺丰'',''京东物流''))")
    n = await pool.fetchval("SELECT COUNT(*) FROM accounting.cost_items")
    print("remaining rows:", n)
    await close_pool()
asyncio.run(main())
'
```

或保留数据，下次 e2e 还能用（按老板偏好决定）。

- [ ] **Step 8：commit settings.local.json + 更新 status memory**

```powershell
git add .claude/settings.local.json
git commit -m "chore(claude): W3a e2e accumulated grants (W3a T13)"
```

更新 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`：
- §二 当前阶段：把 `[ ] W3 落地：...` 中 W3a 范围标 `[x]`
- §十二 最后更新：加一段 "2026-05-XX — W3a 落地完毕（13 commits / N task）"
- §十三 加 W3a e2e 实测结论（KB 是否命中 / brief 质量对比 W2 / Gate CLI 实测可用）

---

## Self-Review Checklist（implementer 起 T1 前 + W3a 完工后各跑一遍）

### 1. Spec coverage（每一项必有 task 实现）

| Spec 项 | 来源 | 实现 task |
|---|---|---|
| prompt 外置（M1 基建） | §十三 第 7 项 | T1, T2, T3, T4, T5 |
| sku 全链路 SOP（M2） | §十三 老板叫停核心点 | T10 (gather_brief_context) + T3 (generate_brief 加 kb_context) + T11 (CLAUDE.md) |
| cost 数据采集（M3） | §十三 第 3 项 | T8 (record_cost / disable_cost_item) + T9 (CSV 批量) |
| Human Gate 真启用（M4） | §十三 第 2 项 | T6 (human_gate.py) + T7 (cli_approve CLI) |
| 写作风格强制约束沿用 | feedback_writing_style.md | anti_ai_voice.md (T1) + ai_hub_client enforce_human_voice 不变（W2 已建） |
| trace 字段不破坏 | W2 design | media.py / accounting.py 改了 sys_msg/user_msg 来源但仍走 build_trace；T3/T4 测试断言 |
| next_step_hint 不破坏 | W2 design | gather_brief_context T10 加新 next_step_hint 指 generate_brief；其他不动 |

### 2. Placeholder scan

搜索全 plan，禁止出现：`TBD`, `TODO`, `implement later`, `fill in details`, `add appropriate error handling`, `Similar to Task N`, `Write tests for the above`（无具体测试代码的）。已检查：T0-T13 每个 step 都给了具体代码或具体命令。

### 3. Type / 接口一致性

| 接口/类型 | 定义在 | 引用 task |
|---|---|---|
| `prompts.load(name) -> str` / `render(name, **ctx) -> str` / `invalidate()` / `list_templates() -> list[str]` | T1 prompts.py | T2/T3/T4/T5/T11/T12 |
| `human_gate.request_approval(*, tool_call_id, summary, timeout_seconds, poll_interval_seconds) -> GateDecision` | T6 human_gate.py | audit.py (T6 step 5) / cost_admin.py (T8) |
| `human_gate.list_pending() -> list[dict]` / `approve(gate_id, note) -> bool` / `reject(gate_id, note) -> bool` | T6 | T7 cli_approve.py |
| `record_cost(sku_id, category, item_name, unit_cost, currency, unit, quantity_per_unit, vendor, valid_from, valid_to, notes) -> dict` | T8 | T13 e2e |
| `disable_cost_item(cost_item_id, reason) -> dict` | T8 | T13 e2e |
| `gather_brief_context(sku_id, channel, top_k_per_role) -> dict` | T10 | T11 CLAUDE.md / T13 e2e |
| `generate_brief(sku_id, channel, extra_context, kb_context)` | T3 修改 | T10 next_step_hint + T13 e2e |

接口名贯穿：`gather_brief_context` 不是 `prepare_brief_context` 也不是 `gather_kb_context`，统一一个名。

### 4. 测试 vs 实现一致性

每个 task 的测试 step 1 在实现 step 之前；测试用例覆盖正常 + 边界（错 category / 找不到 / KB 无命中 / 超时 / approved / rejected）。

---

## W3a 验收（全部 task 完成后）

✅ `docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"` 输出：
- `13 tools registered: all 13 ok`
- `prompt templates: all 8 ok`
- 6 项全 OK（DB pool / mcp schema / yaml / prompts / tools / /mcp HTTP）

✅ 老板侧 e2e（T13）跑通：
- import_costs.py 装数据
- query_costs 返非空
- compute_margin 用新 prompt 出解读（trace 验证 prompt 来自 .md）
- gather_brief_context 返 kb_context（即使 KB 无命中也 ok=True）
- generate_brief 接 kb_context 出 brief（trace 验证 final_prompt 含 KB 段）
- record_cost 走真 Gate + cli_approve 批通

✅ 4 个 hotfix 通道齐活：
- 改 brief 系统提示：编辑 `config/prompts/generate_brief.system.md`，restart KE → 立即生效
- 一次性额外要求：`generate_brief(..., extra_context="...")`
- 临时补 KB：`generate_brief(..., kb_context="...")`（手拼）
- 永久换模型/温度：编辑 `config/tool_models.yaml`，restart KE

✅ git log 干净：~13 commits on `feat/mcp-w1`，每 task 一 commit + T0/T13 各一 chore commit

✅ memory `project_omni_agent_uplift_status.md` 已更新：W3a 范围标 [x]；§十三 加 W3a 实测结论

---

## 已知潜在坑（implementer 要预防）

1. **prompt_constraints `__getattr__` 路径**：T5 改的方案要求 PEP 562（Python 3.7+ 已支持）。如果 import 链上有人直接 `import app.mcp.prompt_constraints; print(prompt_constraints.ANTI_AI_HUMAN_VOICE)` 仍工作；但 `from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE`（首次 import 即捕获快照）也工作（`__getattr__` 模块级被调）。如果 `ai_hub_client.chat` 用 `from ... import ANTI_AI_HUMAN_VOICE`（实测是的），是首次调用时取，每个进程生命周期取一次。修 .md 后老 import 拿不到新内容——这点需要 KE 容器 restart 才生效。如果要"改 .md 不重启"，把 `ai_hub_client.chat` 内的 import 改成 `from app.mcp import prompt_constraints as _pc`，运行时 `_pc.ANTI_AI_HUMAN_VOICE` 触发 `__getattr__`（ai_hub_client 现状已是 `from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE`，T5 step 5 跑测试时验证一下；实测如热改不生效，把 ai_hub_client 那行改成 module-attr 访问）。

2. **W2 测试断言对硬编码 prompt**：T3/T4 改完 sys_msg 来源后，W2 写的 `test_mcp_media.py` / `test_mcp_accounting.py` 内可能有 `assert "调味品" in trace["final_prompt"]` 这类断言。这种关键词断言基本不会破（"调味品"在新模板里也有），但如果碰到字面句首匹配 `assert sys_msg.startswith("你是调味品工厂老板的渠道运营。给一只 SKU")`，会因新模板换行/标点不同而 fail。**处理原则**：放宽到关键词包含，不做句首匹配。

3. **gate poll 假死**：T6 `request_approval` 是 DB poll loop。如果 KE 进程被 kill / 容器被 stop，loop 会被打断 → 留 mcp.tool_calls 里 status=pending 的孤儿。W2 T1 已经实装"启动期孤儿清理"（`mark_orphans`），3 分钟阈值（这里改成 60 分钟以容忍长 gate）；但 mcp.human_gates 没对应清理。**处理**：T6 step 4 跑测试时如发现，可在 `mark_orphans` 加一段同步 update human_gates；本 plan 不强制实现（个人用，不影响功能）。

4. **import_costs.py 字符 BOM**：CSV 用 `utf-8-sig` 编码读（Excel 导出的 csv 带 BOM）。T9 step 2 的代码已用 `encoding="utf-8-sig"`。如老板在 Windows Excel 打开 cost_template.csv 编辑后保存，再 import 应该不会撞编码问题。

5. **bind mount 重启**：T9 step 3 加 scripts bind mount 后必须 `--force-recreate` knowledge-engine 容器（不是 restart），不然新 mount 不生效。

6. **gather_brief_context 测试 mock 路径**：T10 step 1 mock 的是 `app.services.ingestion.list_kbs` 和 `app.services.rag_chain.retrieve_multi_kb`。如这些函数后续改名/重构，本测试要同步改。Test 内的 mock signature 要匹配真函数（W1 search_kb 实际调用模式见 `tools/kb.py`）。

7. **doctor `_check_prompts` 的 list_templates**：T12 调 `prompts.list_templates()` 用 `Path.rglob("*.md")`。如果 `config/prompts/` 下有人放无关 .md 文件（如 README.md），list 会返它，但 wanted 集合不含它，不会 false negative；wanted set 比对方式正确。

8. **CLAUDE.md 长度**：T11 改完后 CLAUDE.md ~110 行。Claude Code 会全文加载 CLAUDE.md 到每次 conversation；不要加冗余说明。

---

## Plan 完工后 status memory 更新模板

更新 `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`：

§二 当前阶段，把
```
- [ ] **W3 落地：专家模型 + 跨服务 + 录音管理（13 个 tool）+ Human Gate 真启用 + sku 全链路 SOP（KB grounding）** ← **下次 /clear 后从这里续**
```
改成
```
- [x] **W3a 落地（2026-05-XX commit `xxxxxxx` on `feat/mcp-w1`，13 tools，doctor 6/6 全绿）** —— 详见 §十四
- [ ] W3b 落地：scout 5 + KB 管理 2 tool（design doc §3.2 W3 行）
- [ ] W3c 落地：录音 / 通用 LLM 6 tool（design doc §3.2 W3 行）
- [ ] W4 落地：前端 + 6 业务 skill + 进化机制
```

§十二 最后更新加：
```
2026-05-XX — W3a 落地完毕（plan + 13 实施 commits on `feat/mcp-w1`）。4 模块全过：(1) prompt 外置（5 .md 模板 + prompts.py loader）；(2) sku SOP 升级（gather_brief_context + CLAUDE.md 三步走 brief）；(3) cost 录入（record_cost / disable_cost_item / import_costs.py）；(4) Human Gate 真启用（human_gate.py + cli_approve CLI）。doctor 6 项全绿（13 tools + 8 prompt templates）。下一步：W3b 实施 scout 5 tool（fetch_compass_* + fetch_yuntu_*）+ kb_upload_doc / kb_set_role 2 tool。
```

加 §十四 W3a 实测结论（按 e2e step 6 真实结果填）。

---

## Plan 完工 → 起执行

老板执行选项：

**1. Subagent-Driven（推荐）** —— 我 dispatch 一个 fresh subagent 跑每 task，你看 commit + diff 再批下一 task。W2 是这模式跑的，14 commits / 1 day（紧凑）。

**2. Inline 执行** —— 在当前 session 跑 task by task，每 2-3 task 你 review 一次。

**3. 你自己跑** —— plan 已写完，你照着 step by step 走，不需要我介入。

**推荐 Subagent-Driven**（W2 已验证模式）。
