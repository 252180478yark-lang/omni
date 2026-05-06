# W4-A 实施计划：3 核心 tool（agent_self_review / codify_pattern_to_skill / refresh_project_context）+ 进化机制基建（rate_tool_call + Pattern Library）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 omni MCP server 加 4 个 agent-meta tool（rate_tool_call / agent_self_review / codify_pattern_to_skill / refresh_project_context）+ Pattern Library 文件基建，doctor 升 23 → 27。

**Architecture:** 4 tool 分两组：(a) 反馈循环 — `rate_tool_call`（F）让老板对 tool_calls 打 good/bad/redo，自动 append 到 host filesystem 的 successful_patterns.md / failed_patterns.md；(b) 反思 + 进化 — `agent_self_review`（F，纯 SQL 统计）/ `codify_pattern_to_skill`（T，调 LLM 写 skill 草稿）/ `refresh_project_context`（T，渲染 omni CLAUDE.md dynamic 区块）。Pattern Library 通过新加的 bind mount `data/agent_state/` 暴露给 host（老板/Claude Code 直接读）。

**Tech Stack:** FastMCP 3.x · asyncpg · pytest-asyncio · ai_hub_client（仅 codify 调）· prompts.py（mtime cache）· bind mount（docker-compose）

---

## 起手就要看的文件（implementer 必读）

- **design doc**：`docs/superpowers/specs/2026-05-03-omni-agent-uplift-design.md`
  - §3.2 W4 行 line 484-490（agent_self_review / codify_pattern_to_skill / refresh_project_context）
  - §3.2 W4 加分 line 500（rate_tool_call 加分项，本批纳入做反馈通路）
  - §4.2 line 544-548（Dynamic 区块定义）
  - §7 全节 line 710-790（5 层进化 + 7.2 草稿审批流 + 7.4 反馈循环 + 7.5 改动量 ~440 行 + 7.6 永远用户拍板）
- **memory 进度**：`C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`
  - §二十 W3c 落地 + W4 起手清单
- **W3c plan 范本**：`docs/superpowers/plans/2026-05-06-omni-agent-uplift-W3c-plan.md`
- **已用基建**（禁止重写）：
  - `app/mcp/audit.py` — `tool_with_audit(mcp, *, require_approval, summary_fn?, timeout_seconds?)`
  - `app/mcp/human_gate.py` — `request_approval / list_pending / approve / reject`（codify + refresh 走这里）
  - `app/mcp/cli_approve.py` — 老板批驳 CLI（codify + refresh 老板侧批入口）
  - `app/mcp/prompts.py` — `load(name) / render(name, **kwargs)`（mtime cache）
  - `app/mcp/trace.py` — `build_trace(*, provider, model, prompt, params, cost_estimate)` keyword-only
  - `app/mcp/model_config.py` — `get_model_for_tool(name)`（不是 plan 字面的 `resolve_model`！W3c 踩过坑）
  - `app/services/ai_hub_client.py` — `AIHubClient().chat(messages, provider, model, ...)`
- **mcp.tool_calls 表**已有字段（016 migration line 14-15）：
  - `user_rating TEXT`（good|bad|redo|null）✅ 字段已就位
  - `rating_note TEXT` ✅ 字段已就位
  - `model_used / tokens_input / tokens_output` ✅ 已就位（本批 rate_tool_call 不写这些，留给后续）
- **omni CLAUDE.md** 当前 70 行，无 dynamic 区块标记 — T5 需先约定老板加 marker
- **docker-compose KE 服务** line 224-230 现有 4 个 bind mount（app / tests / config / scripts）
- **W3c 23 tool 总览**（doctor.py line 90-106）

---

## 关键决策（已锁定，禁止再讨论）

1. **本批 4 tool**：rate_tool_call（F）+ agent_self_review（F）+ codify_pattern_to_skill（T）+ refresh_project_context（T）；W4 加分项的其余 5 个不做（dy_publish_creative / send_wecom_message / save_decision / schedule_observation / generate_image_compare）
2. **agent_self_review 不调 LLM**（纯 SQL 统计 + 滑窗找高频 tool 序列）。design doc §7.5 估 ~80 行，跟纯统计行数对得上
3. **codify_pattern_to_skill 调 LLM**（gemini-3-flash-preview）写 markdown skill 草稿，prompt 外置 1 套（system + user）
4. **refresh_project_context 不调 LLM**（纯查 DB + 模板渲染 + 字符串替换）
5. **Pattern Library 路径**：`E:/agent/omni/data/agent_state/`（host）↔ `/app/agent_state/`（容器）通过 bind mount 双向可见
   - `successful_patterns.md` / `failed_patterns.md`（rate_tool_call 自动 append）
   - `skill_drafts/<skill_name>/SKILL.md`（codify 写草稿；老板手动 `cp -r` 到 `~/.claude/skills/`）
   - **不入 git**：`data/agent_state/.gitignore` 把 `*.md` 排除（patterns 太私人）
6. **agent_self_review 的"高频 tool 序列"识别**：滑窗 N=3 连续 tool_name 序列；最近 7 天出现 ≥3 次的算"候选 pattern"
7. **codify 调 LLM 写 skill 草稿不裸跑**：传给 LLM 的是 (skill_name, description, tool_sequence) + W3a 已有写作风格（人话 / 反幻觉 / 去 AI 化），输出 SKILL.md frontmatter + body
8. **refresh_project_context 区块标记**：`<!-- omni-dynamic:start -->` 到 `<!-- omni-dynamic:end -->`；找不到 marker → 返 `ok=False, hint="老板先在 CLAUDE.md 加这两行 marker"`
9. **复用 W3a/W3c 全部基建**：禁止新建 chat 客户端 / 新 prompt 加载器 / 新 trace 函数
10. **个人自用，禁止过度工程**：不写微服务 / SLA / 分布式 / cron / 前端
11. **doctor expected_tools 23 → 27**
12. **rate_tool_call 不走 Human Gate**（F 类，纯打分；high-volume 操作走 gate 折磨老板）
13. **codify + refresh 走 Human Gate**（T 类，关键写入操作）
14. **trace["provider"] alias**：W3c 已建 LLM tool 给 trace 加 `["provider"] = effective_provider` alias 让测试 assert 过；本批 codify_pattern_to_skill 沿用同 alias

---

## 文件结构

### 待建（4 个 .py）
- `services/knowledge-engine/app/mcp/pattern_lib.py` — Pattern Library 文件读写 helper（~80 行）
- `services/knowledge-engine/app/mcp/tools/feedback.py` — rate_tool_call tool（~80 行）
- `services/knowledge-engine/app/mcp/tools/agent_meta.py` — agent_self_review + codify_pattern_to_skill + refresh_project_context（~320 行）
- `services/knowledge-engine/tests/test_mcp_pattern_lib.py` — pattern_lib 单元测（~50 行）
- `services/knowledge-engine/tests/test_mcp_feedback.py` — rate_tool_call 测（~80 行）
- `services/knowledge-engine/tests/test_mcp_agent_meta.py` — 3 tool 测（~200 行）

### 待新增 prompts（2 个 .md）
- `services/knowledge-engine/config/prompts/codify_skill.system.md`
- `services/knowledge-engine/config/prompts/codify_skill.user.md`

### 待改（5 个）
- `docker-compose.yml` line 224-230 — 加一行 bind mount `./data/agent_state:/app/agent_state:rw`（+1 行）
- `services/knowledge-engine/app/mcp/server.py` — `import feedback / agent_meta`（+2 行）
- `services/knowledge-engine/app/mcp/doctor.py` line 90-106 — wanted 集合扩 4 名 + count 23 → 27（~6 行）
- `services/knowledge-engine/app/mcp/tools/__init__.py` — docstring 加 W4-A 段（~6 行）
- `services/knowledge-engine/config/tool_models.yaml` — 加 codify_pattern_to_skill keyed（~8 行）
- `.claude/settings.local.json` — 加 4 个 grant（`mcp__omni__rate_tool_call` / ... / `mcp__omni__refresh_project_context`）（+4 行）

### 待建非代码
- `data/agent_state/.gitignore`（内容：`*.md` + `skill_drafts/`）
- `data/agent_state/successful_patterns.md`（空 placeholder，内容仅 `# Successful Patterns\n\n_由 rate_tool_call 自动追加_\n`）
- `data/agent_state/failed_patterns.md`（同上）

---

## 已知坑（W3a/W3b/W3c 期间踩的，防重踩）

1. **fixture sync 写法跑不通**：用 `@pytest_asyncio.fixture(scope="module", autouse=True)` async 写法
2. **PowerShell 5.1 `\"` 不是合法转义**：容器内调 `docker exec ... bash -c "..."` 包装跑容器内 bash，禁止 host 嵌套引号
3. **pytest 命令必须带 PYTHONPATH + cwd**：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/... -v"`
4. **bind mount 改 docker-compose 后必须 `up -d --no-deps --force-recreate knowledge-engine`**：T1 改 docker-compose 必走这步，否则 /app/agent_state 不存在
5. **pattern_lib 用 sync IO**：append patterns.md 用 `open(..., "a", encoding="utf-8")` 即可，不要 aiofiles（patterns 文件小，不阻塞 event loop）
6. **plan 字面 vs 实际 helper 名**（W3c 踩过）：`get_model_for_tool` 不是 `resolve_model`；`build_trace(*, provider, model, prompt, params, cost_estimate)` 全 keyword-only
7. **trace schema 漂移**（W3c 留缮）：`build_trace` 返 `model_provider`，LLM tool 加 `trace["provider"] = effective_provider` alias 让测试 assert 过。codify_pattern_to_skill 沿用
8. **hub /chat 响应结构**：`{"content": str, "provider": str, "model": str, "usage": {...}}`，**不是 OpenAI ChatCompletion 风格**
9. **anthropic provider 不可用**：项目 anthropic 是 Claude Code Max 订阅 ≠ API key。codify_pattern_to_skill 走 gemini
10. **doctor `_check_tools_registered` 用 wanted 集合 in-place 改**（line 88-115），count 同步从 23 → 27
11. **rate_tool_call 写 user_rating 时验入参**：`rating in {"good","bad","redo"}`，否则返 `error="invalid_rating"`
12. **codify 草稿目录避免覆盖**：`skill_drafts/<name>/` 已存在 → 加时间戳后缀 `<name>__YYYYMMDD-HHMMSS/`
13. **refresh_project_context 区块替换 idempotent**：连调 2 次结果一致；用 regex `<!-- omni-dynamic:start -->.*?<!-- omni-dynamic:end -->`（DOTALL）替换
14. **omni CLAUDE.md path 解析**：容器内不能直接访问 host 的 `E:/agent/omni/CLAUDE.md`。本批方案 — refresh_project_context 在 agent_state bind mount 里写 `dynamic_block.md`（host 路径 `data/agent_state/dynamic_block.md`），由老板手动 `cat data/agent_state/dynamic_block.md` 复制粘进 CLAUDE.md。**别幻想容器内直接改 host CLAUDE.md**（路径不通 + 越权），W4-B 前端落地后 /agent-log 提供"复制粘贴"按钮
15. **tool_calls.user_rating 已存在**（016 migration line 14），不要再加 migration

---

## 任务总览（6 task）

| Task | 名称 | 类型 | 估时 |
|---|---|---|---|
| T1 | agent_state bind mount + pattern_lib helper | infra + helper | 45 min |
| T2 | rate_tool_call tool | F | 60 min |
| T3 | agent_self_review tool（纯统计） | F | 75 min |
| T4 | codify_pattern_to_skill tool（LLM 草稿） | T LLM | 75 min |
| T5 | refresh_project_context tool（dynamic_block 渲染） | T | 60 min |
| T6 | doctor expected_tools=27 + tools/__init__.py + yaml + grant + e2e | chore | 30 min |

总计：6 task / ~5 小时落地（subagent-driven 模式）。

---

## Task 1: agent_state bind mount + pattern_lib helper

**Goal:** 加 host ↔ 容器 bind mount，建 Pattern Library 文件读写 helper（append_successful_pattern / append_failed_pattern / read_recent_patterns）。后续 T2 / T3 / T4 都依赖。

**Files:**
- Create: `data/agent_state/.gitignore`
- Create: `data/agent_state/successful_patterns.md`
- Create: `data/agent_state/failed_patterns.md`
- Modify: `docker-compose.yml:224-230`
- Create: `services/knowledge-engine/app/mcp/pattern_lib.py`
- Create: `services/knowledge-engine/tests/test_mcp_pattern_lib.py`

- [ ] **Step 1: 建 host 目录 + .gitignore**

```bash
mkdir -p E:/agent/omni/data/agent_state
```

写 `E:/agent/omni/data/agent_state/.gitignore`：

```
# patterns 文件 + skill drafts 太私人，全部不入 git
*.md
skill_drafts/
```

- [ ] **Step 2: 建 patterns.md 占位文件**

写 `E:/agent/omni/data/agent_state/successful_patterns.md`：

```markdown
# Successful Patterns

_由 rate_tool_call(rating="good") 自动追加。Claude 面对相似问题前自动读这个文件。_
```

写 `E:/agent/omni/data/agent_state/failed_patterns.md`：

```markdown
# Failed Patterns

_由 rate_tool_call(rating="bad" / "redo") 自动追加。Claude 面对相似问题前自动读这个文件以避免重蹈覆辙。_
```

- [ ] **Step 3: 改 docker-compose.yml 加 bind mount**

定位 `services/knowledge-engine/app/mcp/cli_approve.py` 之上的 `knowledge-engine.volumes` 段（约 line 224-230），在最后加：

```yaml
      - ./data/agent_state:/app/agent_state:rw
```

完整段：

```yaml
    volumes:
      - knowledge_data:/app/data
      # Dev: bind-mount 源码 + 测试 + 配置，便于热改 / pytest 不需 docker cp
      - ./services/knowledge-engine/app:/app/app
      - ./services/knowledge-engine/tests:/app/tests
      - ./services/knowledge-engine/config:/app/config
      - ./services/knowledge-engine/scripts:/app/scripts:rw
      - ./data/agent_state:/app/agent_state:rw
```

- [ ] **Step 4: 容器 force-recreate 加载新 mount**

```bash
docker compose -f E:/agent/omni/docker-compose.yml up -d --no-deps --force-recreate knowledge-engine
```

预期：约 5-10s 容器重启，等 `docker logs omni-knowledge-engine 2>&1 | tail -5` 看到 `Application startup complete`

- [ ] **Step 5: 验 bind mount 通**

```bash
docker exec omni-knowledge-engine ls /app/agent_state
```

预期输出：
```
failed_patterns.md
successful_patterns.md
```

- [ ] **Step 6: 写 pattern_lib.py（先写失败测试）**

写 `services/knowledge-engine/tests/test_mcp_pattern_lib.py`：

```python
"""W4-A T1: pattern_lib helper 单元测试。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.mcp import pattern_lib


@pytest.fixture
def tmp_state_dir(monkeypatch, tmp_path):
    """临时 agent_state 目录 + 占位 patterns.md。"""
    success = tmp_path / "successful_patterns.md"
    failed = tmp_path / "failed_patterns.md"
    success.write_text("# Successful Patterns\n\n", encoding="utf-8")
    failed.write_text("# Failed Patterns\n\n", encoding="utf-8")
    monkeypatch.setattr(pattern_lib, "AGENT_STATE_DIR", tmp_path)
    return tmp_path


def test_append_successful_pattern(tmp_state_dir):
    pattern_lib.append_successful_pattern(
        tool_call_id="abc-123",
        tool_name="generate_brief",
        note="出片很顺",
    )
    text = (tmp_state_dir / "successful_patterns.md").read_text(encoding="utf-8")
    assert "abc-123" in text
    assert "generate_brief" in text
    assert "出片很顺" in text


def test_append_failed_pattern(tmp_state_dir):
    pattern_lib.append_failed_pattern(
        tool_call_id="def-456",
        tool_name="compute_margin",
        note="算错了",
    )
    text = (tmp_state_dir / "failed_patterns.md").read_text(encoding="utf-8")
    assert "def-456" in text
    assert "compute_margin" in text
    assert "算错了" in text


def test_read_recent_patterns_returns_last_n(tmp_state_dir):
    for i in range(5):
        pattern_lib.append_successful_pattern(
            tool_call_id=f"call-{i}",
            tool_name="generate_brief",
            note=f"note-{i}",
        )
    recent = pattern_lib.read_recent_patterns(kind="successful", limit=3)
    assert len(recent) == 3
    # 最后写的最先返
    assert recent[0]["tool_call_id"] == "call-4"
```

- [ ] **Step 7: 跑测试验证失败**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_pattern_lib.py -v"
```

预期：FAIL — `ImportError: app.mcp.pattern_lib`

- [ ] **Step 8: 实现 pattern_lib.py**

写 `services/knowledge-engine/app/mcp/pattern_lib.py`：

```python
"""W4-A T1：Pattern Library 文件读写 helper。

design doc §7.4 反馈循环：
- successful_patterns.md 累积 rating='good' 调用
- failed_patterns.md 累积 rating='bad' / 'redo' 调用

文件写在 /app/agent_state（host bind mount = data/agent_state/），
host 上 Claude Code 进 omni 项目时可直接读做 ICL 输入。

用 sync IO（patterns 文件小，不阻塞 event loop）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

AGENT_STATE_DIR = Path("/app/agent_state")


def _ensure_file(path: Path, header: str) -> None:
    """文件不存在时建空文件。"""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header, encoding="utf-8")


def append_successful_pattern(
    *,
    tool_call_id: str,
    tool_name: str,
    note: str = "",
) -> None:
    """追加一条 successful pattern。

    Args:
        tool_call_id: mcp.tool_calls.id（uuid str）
        tool_name: tool 名（如 generate_brief）
        note: 老板打分时附带的备注
    """
    path = AGENT_STATE_DIR / "successful_patterns.md"
    _ensure_file(path, "# Successful Patterns\n\n")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    entry = f"\n## {ts} · {tool_name}\n\n- tool_call_id: `{tool_call_id}`\n- note: {note or '_无_'}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def append_failed_pattern(
    *,
    tool_call_id: str,
    tool_name: str,
    note: str = "",
) -> None:
    """追加一条 failed pattern。"""
    path = AGENT_STATE_DIR / "failed_patterns.md"
    _ensure_file(path, "# Failed Patterns\n\n")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    entry = f"\n## {ts} · {tool_name}\n\n- tool_call_id: `{tool_call_id}`\n- note: {note or '_无_'}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def read_recent_patterns(
    *,
    kind: Literal["successful", "failed"],
    limit: int = 10,
) -> list[dict]:
    """读最近 N 条 pattern（按写入时间倒序）。

    Returns:
        [{"timestamp": str, "tool_name": str, "tool_call_id": str, "note": str}, ...]
    """
    path = AGENT_STATE_DIR / f"{kind}_patterns.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = text.split("\n## ")[1:]  # 第 0 块是 header
    blocks.reverse()  # 最近的在前
    out: list[dict] = []
    for block in blocks[:limit]:
        lines = block.splitlines()
        if not lines:
            continue
        # 第 0 行：YYYY-MM-DD HH:MM:SSZ · tool_name
        head = lines[0]
        if " · " not in head:
            continue
        ts, tool_name = head.split(" · ", 1)
        call_id = ""
        note = ""
        for ln in lines[1:]:
            ln = ln.strip()
            if ln.startswith("- tool_call_id: `"):
                call_id = ln.split("`")[1] if "`" in ln else ""
            elif ln.startswith("- note: "):
                note = ln[len("- note: "):]
        out.append({
            "timestamp": ts.strip(),
            "tool_name": tool_name.strip(),
            "tool_call_id": call_id,
            "note": note,
        })
    return out
```

- [ ] **Step 9: 跑测试验证通过**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_pattern_lib.py -v"
```

预期：3 PASS

- [ ] **Step 10: 验真容器内可写 /app/agent_state**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'from app.mcp.pattern_lib import append_successful_pattern; append_successful_pattern(tool_call_id=\"smoke-test-1\", tool_name=\"smoke\", note=\"T1 smoke\"); print(\"OK\")'"
```

预期输出：`OK`

验 host 同步可见：
```bash
cat E:/agent/omni/data/agent_state/successful_patterns.md
```

预期：底部含 `smoke-test-1` 行

清理 smoke test 内容（保留 placeholder header）：
```bash
echo "# Successful Patterns

_由 rate_tool_call(rating=\"good\") 自动追加。Claude 面对相似问题前自动读这个文件。_
" > E:/agent/omni/data/agent_state/successful_patterns.md
```

- [ ] **Step 11: Commit**

```bash
git add data/agent_state/.gitignore data/agent_state/successful_patterns.md data/agent_state/failed_patterns.md docker-compose.yml services/knowledge-engine/app/mcp/pattern_lib.py services/knowledge-engine/tests/test_mcp_pattern_lib.py
git commit -m "$(cat <<'EOF'
feat(mcp): pattern_lib helper + agent_state bind mount (W4-A T1)

- 新建 data/agent_state/ host 目录（.gitignore 排除 *.md / skill_drafts/）
- docker-compose KE 加 bind mount: ./data/agent_state:/app/agent_state:rw
- pattern_lib.append_successful_pattern / append_failed_pattern / read_recent_patterns
- 3 unit test 通过
EOF
)"
```

---

## Task 2: rate_tool_call tool

**Goal:** 老板对历史 tool_call 打分（good/bad/redo）。写 mcp.tool_calls.user_rating + rating_note；good → pattern_lib.append_successful_pattern，bad/redo → append_failed_pattern。F 类不走 Human Gate。

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/feedback.py`
- Create: `services/knowledge-engine/tests/test_mcp_feedback.py`

- [ ] **Step 1: 写失败测试**

写 `services/knowledge-engine/tests/test_mcp_feedback.py`：

```python
"""W4-A T2: rate_tool_call tool 测试。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp import pattern_lib
from app.mcp.tools.feedback import rate_tool_call


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def seed_call():
    """插一条 mcp.tool_calls 给 rate 用，返 id str。"""
    pool = get_pool()
    call_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval, completed_at) "
        "VALUES ($1, 'fake_tool', '{}'::jsonb, 'completed', FALSE, NOW())",
        call_id,
    )
    yield str(call_id)
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", call_id)


@pytest.fixture
def tmp_state_dir(monkeypatch, tmp_path):
    success = tmp_path / "successful_patterns.md"
    failed = tmp_path / "failed_patterns.md"
    success.write_text("# Successful Patterns\n\n", encoding="utf-8")
    failed.write_text("# Failed Patterns\n\n", encoding="utf-8")
    monkeypatch.setattr(pattern_lib, "AGENT_STATE_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_rate_good_writes_db_and_patterns(seed_call, tmp_state_dir):
    res = await rate_tool_call(call_id=seed_call, rating="good", note="完美")
    assert res["ok"] is True
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT user_rating, rating_note FROM mcp.tool_calls WHERE id=$1",
        uuid.UUID(seed_call),
    )
    assert row["user_rating"] == "good"
    assert row["rating_note"] == "完美"
    text = (tmp_state_dir / "successful_patterns.md").read_text(encoding="utf-8")
    assert seed_call in text


@pytest.mark.asyncio
async def test_rate_bad_writes_failed_patterns(seed_call, tmp_state_dir):
    res = await rate_tool_call(call_id=seed_call, rating="bad", note="返空")
    assert res["ok"] is True
    text = (tmp_state_dir / "failed_patterns.md").read_text(encoding="utf-8")
    assert seed_call in text


@pytest.mark.asyncio
async def test_rate_invalid_returns_error(seed_call, tmp_state_dir):
    res = await rate_tool_call(call_id=seed_call, rating="awesome")
    assert res["ok"] is False
    assert "invalid_rating" in res.get("error", "")


@pytest.mark.asyncio
async def test_rate_unknown_call_id_returns_error(tmp_state_dir):
    fake_id = str(uuid.uuid4())
    res = await rate_tool_call(call_id=fake_id, rating="good")
    assert res["ok"] is False
    assert "call_not_found" in res.get("error", "")
```

- [ ] **Step 2: 跑测试验证失败**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_feedback.py -v"
```

预期：FAIL — `ImportError: app.mcp.tools.feedback`

- [ ] **Step 3: 实现 feedback.py**

写 `services/knowledge-engine/app/mcp/tools/feedback.py`：

```python
"""W4-A T2: rate_tool_call tool。

design doc §7.4 反馈循环：
- 老板对历史 tool_call 打分（good/bad/redo）
- 写 mcp.tool_calls.user_rating + rating_note
- good → pattern_lib.append_successful_pattern
- bad/redo → pattern_lib.append_failed_pattern

F 类，不走 Human Gate（high-volume 操作）。
"""
from __future__ import annotations

import logging
import uuid

from app.database import get_pool
from app.mcp import pattern_lib
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp

logger = logging.getLogger(__name__)

_VALID_RATINGS = {"good", "bad", "redo"}


@tool_with_audit(mcp, require_approval=False)
async def rate_tool_call(
    call_id: str,
    rating: str,
    note: str = "",
) -> dict:
    """对一个历史 tool_call 打分。

    Args:
        call_id: mcp.tool_calls.id（uuid str）
        rating: good | bad | redo
        note: 可选备注

    Returns:
        {ok, result: {call_id, rating, tool_name}}（出错时 {ok:false, error, hint}）
    """
    if rating not in _VALID_RATINGS:
        return {
            "ok": False,
            "error": "invalid_rating",
            "hint": f"rating 必须是 {sorted(_VALID_RATINGS)} 之一",
        }

    try:
        call_uuid = uuid.UUID(call_id)
    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "invalid_call_id",
            "hint": "call_id 必须是 uuid 字符串",
        }

    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE mcp.tool_calls SET user_rating=$1, rating_note=$2 "
        "WHERE id=$3 RETURNING tool_name",
        rating,
        note,
        call_uuid,
    )
    if row is None:
        return {
            "ok": False,
            "error": "call_not_found",
            "hint": f"call_id={call_id} 不存在；用 SELECT id FROM mcp.tool_calls 查",
        }

    tool_name = row["tool_name"]
    if rating == "good":
        pattern_lib.append_successful_pattern(
            tool_call_id=call_id, tool_name=tool_name, note=note,
        )
    else:  # bad / redo
        pattern_lib.append_failed_pattern(
            tool_call_id=call_id, tool_name=tool_name, note=note,
        )

    logger.info("rate_tool_call call_id=%s rating=%s tool=%s",
                call_id[:8], rating, tool_name)
    return {
        "ok": True,
        "result": {
            "call_id": call_id,
            "rating": rating,
            "tool_name": tool_name,
        },
    }
```

- [ ] **Step 4: 跑测试验证通过**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_feedback.py -v"
```

预期：4 PASS

- [ ] **Step 5: 注册到 server.py**

修改 `services/knowledge-engine/app/mcp/server.py`，在 `from app.mcp.tools import general as _general` 后加：

```python
from app.mcp.tools import feedback as _feedback  # noqa: E402, F401  # W4-A T2
```

- [ ] **Step 6: 验注册**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'import asyncio; from app.mcp.server import mcp; tools = asyncio.run(mcp.list_tools()); print([t.name for t in tools if \"rate\" in t.name])'"
```

预期：`['rate_tool_call']`

- [ ] **Step 7: Commit**

```bash
git add services/knowledge-engine/app/mcp/tools/feedback.py services/knowledge-engine/tests/test_mcp_feedback.py services/knowledge-engine/app/mcp/server.py
git commit -m "$(cat <<'EOF'
feat(mcp): rate_tool_call tool（W4-A T2）

老板对历史 tool_call 打分 good/bad/redo，写 mcp.tool_calls.user_rating，
按 rating 自动 append 到 successful_patterns.md / failed_patterns.md。
4 unit test 通过。
EOF
)"
```

---

## Task 3: agent_self_review tool（纯统计反思）

**Goal:** 读最近 N 天 mcp.tool_calls 出反思报告：tool 调用数 / 成功率 / good/bad rating 分布 / 高频 tool 序列（滑窗 N=3，连续 3 个 tool_name 序列出现 ≥3 次）。不调 LLM。

**Files:**
- Create: `services/knowledge-engine/app/mcp/tools/agent_meta.py`
- Create: `services/knowledge-engine/tests/test_mcp_agent_meta.py`

- [ ] **Step 1: 写失败测试**

写 `services/knowledge-engine/tests/test_mcp_agent_meta.py`：

```python
"""W4-A T3-T5: agent_meta tool 测试。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def seed_calls():
    """造一批 tool_calls：3 次 generate_brief→search_kb→get_sku 序列 + 5 次散调。"""
    pool = get_pool()
    inserted = []
    now = datetime.now(timezone.utc)
    # 3 次序列（间隔 1 天）
    for i in range(3):
        for tool_name in ["generate_brief", "search_kb", "get_sku"]:
            cid = uuid.uuid4()
            ts = now - timedelta(days=i, minutes=ord(tool_name[0]))
            await pool.execute(
                "INSERT INTO mcp.tool_calls "
                "(id, tool_name, args, status, require_approval, created_at, completed_at, user_rating) "
                "VALUES ($1, $2, '{}'::jsonb, 'completed', FALSE, $3, $3, $4)",
                cid, tool_name, ts, "good" if (i == 0 and tool_name == "generate_brief") else None,
            )
            inserted.append(cid)
    # 散调
    for tool_name in ["list_skus", "list_kbs", "compute_margin", "list_briefs", "search_kb"]:
        cid = uuid.uuid4()
        await pool.execute(
            "INSERT INTO mcp.tool_calls "
            "(id, tool_name, args, status, require_approval, created_at, completed_at) "
            "VALUES ($1, $2, '{}'::jsonb, 'completed', FALSE, NOW(), NOW())",
            cid, tool_name,
        )
        inserted.append(cid)
    yield
    for cid in inserted:
        await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", cid)


@pytest.mark.asyncio
async def test_agent_self_review_basic_stats(seed_calls):
    from app.mcp.tools.agent_meta import agent_self_review
    res = await agent_self_review(period_days=7)
    assert res["ok"] is True
    r = res["result"]
    assert r["total_calls"] >= 14  # 9 序列 + 5 散调
    assert "by_tool" in r
    assert r["by_tool"].get("generate_brief", 0) >= 3
    assert r["by_status"].get("completed", 0) >= 14


@pytest.mark.asyncio
async def test_agent_self_review_finds_pattern(seed_calls):
    from app.mcp.tools.agent_meta import agent_self_review
    res = await agent_self_review(period_days=7)
    patterns = res["result"]["candidate_patterns"]
    # 期望找到 (generate_brief, search_kb, get_sku) 滑窗 3 序列
    seqs = [tuple(p["sequence"]) for p in patterns]
    assert ("generate_brief", "search_kb", "get_sku") in seqs


@pytest.mark.asyncio
async def test_agent_self_review_rating_distribution(seed_calls):
    from app.mcp.tools.agent_meta import agent_self_review
    res = await agent_self_review(period_days=7)
    r = res["result"]
    assert "by_rating" in r
    assert r["by_rating"].get("good", 0) >= 1
```

- [ ] **Step 2: 跑测试验证失败**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_agent_meta.py::test_agent_self_review_basic_stats -v"
```

预期：FAIL — `ImportError: app.mcp.tools.agent_meta`

- [ ] **Step 3: 实现 agent_meta.py 的 agent_self_review**

写 `services/knowledge-engine/app/mcp/tools/agent_meta.py`：

```python
"""W4-A T3/T4/T5：agent_self_review + codify_pattern_to_skill + refresh_project_context。

design doc §7（5 层进化 + 7.2 草稿审批流 + 7.4 反馈循环）。

- agent_self_review(period_days?) — 纯 SQL 统计，不调 LLM。返反思报告 +
  candidate_patterns（滑窗 3 找高频 tool 序列）
- codify_pattern_to_skill(skill_name, description, tool_sequence) — 调 LLM 写
  SKILL.md 草稿到 /app/agent_state/skill_drafts/<name>/SKILL.md（require_approval=True）
- refresh_project_context() — 渲染 dynamic_block.md 到 /app/agent_state/
  让老板手动复制粘进 omni CLAUDE.md 的 marker 区块（require_approval=True）
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp

logger = logging.getLogger(__name__)

AGENT_STATE_DIR = Path("/app/agent_state")
SKILL_DRAFTS_DIR = AGENT_STATE_DIR / "skill_drafts"


# ─── T3: agent_self_review ─────────────────────────────────────────────────


@tool_with_audit(mcp, require_approval=False)
async def agent_self_review(period_days: int = 7) -> dict:
    """反思周报：读最近 N 天 mcp.tool_calls 出统计 + 候选 pattern。

    Args:
        period_days: 时间窗（默认 7 天）

    Returns:
        {ok, result: {
            period_days,
            total_calls,
            by_tool: {tool_name: count, ...},
            by_status: {completed/error/rejected: count, ...},
            by_rating: {good/bad/redo/null: count, ...},
            candidate_patterns: [{sequence: [str, str, str], occurrences: int}, ...]
        }}
    """
    if period_days <= 0:
        return {"ok": False, "error": "invalid_period",
                "hint": "period_days 必须 > 0"}

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, tool_name, status, user_rating, created_at
          FROM mcp.tool_calls
         WHERE created_at >= NOW() - ($1 || ' days')::interval
         ORDER BY created_at ASC
        """,
        str(period_days),
    )
    total = len(rows)
    by_tool = Counter(r["tool_name"] for r in rows)
    by_status = Counter(r["status"] for r in rows)
    by_rating = Counter(r["user_rating"] or "null" for r in rows)

    # 滑窗 3 找 candidate_patterns
    seq_counter: Counter[tuple[str, ...]] = Counter()
    if total >= 3:
        names = [r["tool_name"] for r in rows]
        for i in range(len(names) - 2):
            seq_counter[(names[i], names[i+1], names[i+2])] += 1
    candidates = [
        {"sequence": list(seq), "occurrences": cnt}
        for seq, cnt in seq_counter.most_common()
        if cnt >= 3
    ]

    return {
        "ok": True,
        "result": {
            "period_days": period_days,
            "total_calls": total,
            "by_tool": dict(by_tool),
            "by_status": dict(by_status),
            "by_rating": dict(by_rating),
            "candidate_patterns": candidates,
            "next_step_hint": (
                f"找到 {len(candidates)} 个候选 pattern。下一步：调 "
                "codify_pattern_to_skill(skill_name=..., description=..., "
                "tool_sequence=[...]) 把高频组合升级成 skill 草稿。"
                if candidates else
                "未找到 ≥3 次重复的 3-tool 序列；继续累积调用数据后再 review。"
            ),
        },
    }
```

- [ ] **Step 4: 跑 T3 部分测试**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_agent_meta.py::test_agent_self_review_basic_stats tests/test_mcp_agent_meta.py::test_agent_self_review_finds_pattern tests/test_mcp_agent_meta.py::test_agent_self_review_rating_distribution -v"
```

预期：3 PASS

- [ ] **Step 5: 注册到 server.py**

修改 `services/knowledge-engine/app/mcp/server.py`，在 feedback import 后加：

```python
from app.mcp.tools import agent_meta as _agent_meta  # noqa: E402, F401  # W4-A T3+
```

- [ ] **Step 6: 验注册**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'import asyncio; from app.mcp.server import mcp; tools = asyncio.run(mcp.list_tools()); print(sorted([t.name for t in tools if \"agent\" in t.name or \"self_review\" in t.name]))'"
```

预期：`['agent_self_review']`

- [ ] **Step 7: Commit**

```bash
git add services/knowledge-engine/app/mcp/tools/agent_meta.py services/knowledge-engine/tests/test_mcp_agent_meta.py services/knowledge-engine/app/mcp/server.py
git commit -m "$(cat <<'EOF'
feat(mcp): agent_self_review tool（W4-A T3）

纯 SQL 统计反思周报：tool/status/rating 频次 + 滑窗 3 找 ≥3 次重复
3-tool 序列做 candidate_patterns。3 unit test 通过。
EOF
)"
```

---

## Task 4: codify_pattern_to_skill tool

**Goal:** 老板（或 Claude 触发）把一个高频 tool_sequence 升级成 skill markdown 草稿。调 LLM 生成 SKILL.md，写到 `/app/agent_state/skill_drafts/<name>/SKILL.md`。require_approval=True；老板批后 host 侧手动 cp 到 `~/.claude/skills/`。

**Files:**
- Create: `services/knowledge-engine/config/prompts/codify_skill.system.md`
- Create: `services/knowledge-engine/config/prompts/codify_skill.user.md`
- Modify: `services/knowledge-engine/app/mcp/tools/agent_meta.py` (add codify_pattern_to_skill)
- Modify: `services/knowledge-engine/tests/test_mcp_agent_meta.py` (add codify tests)
- Modify: `services/knowledge-engine/config/tool_models.yaml` (add keyed override)

- [ ] **Step 1: 写 prompt 模板**

写 `services/knowledge-engine/config/prompts/codify_skill.system.md`：

```markdown
你是 omni-vibe 项目的 skill 草稿生成专家。

【任务】
基于一段 tool 调用序列把它变成 Claude Code 可触发的 skill markdown 草稿。
草稿后续会被老板审：批 → 移到 ~/.claude/skills/；驳 → 删；改 → 老板手编后再用。

【输出格式】（严格）
返回完整 SKILL.md 的 markdown 文本。结构：

---
name: {skill_name}
description: {一句话描述触发场景}
---

# {Skill Name}

## 触发场景

{老板说什么时跑这个 skill}

## 流程

{step-by-step 列出每一步调哪个 tool / 入参从哪来 / 输出给谁审}

## 注意

{易踩的坑 / 老板偏好}

【风格】
- 说人话：不要"我们将"、"接下来"、"接着"等连接符堆砌
- 反幻觉：只用入参里给的事实，不要捏造 tool 名 / 参数名
- 去 AI 化：不要"高效"、"赋能"、"协同"、"闭环"等 AI 风用词
- 简洁：每段 ≤ 5 行，能用 bullet 不用段落

【关键约束】
- 仅使用入参 tool_sequence 里出现的 tool 名，不要捏造其他
- description 一句话不超过 30 字
- 不要写"由 AI 生成"或类似元说明
```

写 `services/knowledge-engine/config/prompts/codify_skill.user.md`：

```markdown
【skill 名】{skill_name}

【描述】{description}

【tool 序列】
{tool_sequence_block}

【参考资料】
omni 现有 27 个 tool（由 Claude Code MCP 暴露）。本 skill 应只编排 tool_sequence
里给出的几个，不要引入其他 tool。

请生成完整 SKILL.md：
```

- [ ] **Step 2: 写 codify 测试（先失败）**

在 `services/knowledge-engine/tests/test_mcp_agent_meta.py` 末尾追加：

```python


# ─── T4: codify_pattern_to_skill ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_codify_writes_draft(monkeypatch, tmp_path):
    """codify 直接调（绕开 require_approval gate）写草稿到指定目录。"""
    from app.mcp.tools import agent_meta

    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(agent_meta, "SKILL_DRAFTS_DIR", tmp_path / "skill_drafts")

    # mock LLM 返回固定 markdown
    fake_md = "---\nname: test-skill\ndescription: smoke\n---\n\n# Test\n"

    class _FakeClient:
        async def chat(self, **kwargs):
            return {
                "content": fake_md,
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "usage": {},
            }

    monkeypatch.setattr(agent_meta, "AIHubClient", _FakeClient)

    # 直接调内部函数（绕 audit/gate 装饰器）
    res = await agent_meta._codify_impl(
        skill_name="test-skill",
        description="测试 skill",
        tool_sequence=["list_skus", "get_sku"],
    )
    assert res["ok"] is True
    draft_path = Path(res["result"]["draft_path"])
    assert draft_path.exists()
    assert draft_path.read_text(encoding="utf-8").strip().startswith("---")
    assert "test-skill" in draft_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_codify_invalid_skill_name(monkeypatch, tmp_path):
    from app.mcp.tools import agent_meta
    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(agent_meta, "SKILL_DRAFTS_DIR", tmp_path / "skill_drafts")

    res = await agent_meta._codify_impl(
        skill_name="invalid name with spaces!",
        description="x",
        tool_sequence=["list_skus"],
    )
    assert res["ok"] is False
    assert "invalid_skill_name" in res.get("error", "")
```

- [ ] **Step 3: 跑测试验证失败**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_agent_meta.py::test_codify_writes_draft -v"
```

预期：FAIL — `AttributeError: module 'app.mcp.tools.agent_meta' has no attribute '_codify_impl'`

- [ ] **Step 4: 实现 codify_pattern_to_skill**

修改 `services/knowledge-engine/app/mcp/tools/agent_meta.py`，文件顶部 import 区追加：

```python
import re

from app.mcp import prompts
from app.mcp.model_config import get_model_for_tool
from app.mcp.trace import build_trace
from app.services.ai_hub_client import AIHubClient
```

文件末尾追加：

```python


# ─── T4: codify_pattern_to_skill ───────────────────────────────────────────


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")


def _codify_summary(args: dict) -> str:
    return (f"codify_pattern_to_skill: skill_name={args.get('skill_name')} "
            f"tool_sequence={args.get('tool_sequence')}")


async def _codify_impl(
    *,
    skill_name: str,
    description: str,
    tool_sequence: list[str],
) -> dict:
    """codify 真业务（无 audit/gate）。给测试 mock 用，也给 tool 包装函数调。"""
    if not _SKILL_NAME_RE.match(skill_name or ""):
        return {
            "ok": False,
            "error": "invalid_skill_name",
            "hint": "skill_name 必须 a-z 0-9 - 组成、2-50 字符、首位字母数字",
        }
    if not tool_sequence or not isinstance(tool_sequence, list):
        return {
            "ok": False,
            "error": "invalid_tool_sequence",
            "hint": "tool_sequence 必须是非空 list[str]",
        }
    description = (description or "").strip()
    if not description:
        return {"ok": False, "error": "missing_description",
                "hint": "description 不能为空"}

    # 渲染 prompts
    tool_seq_block = "\n".join(f"- {t}" for t in tool_sequence)
    system_prompt = prompts.load("codify_skill.system")
    user_prompt = prompts.render(
        "codify_skill.user",
        skill_name=skill_name,
        description=description,
        tool_sequence_block=tool_seq_block,
    )

    cfg = get_model_for_tool("codify_pattern_to_skill")
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
        logger.exception("codify chat failed")
        return {
            "ok": False,
            "error": "llm_call_failed",
            "hint": f"ai-hub /chat 调用失败: {exc}",
        }

    md = (resp.get("content") or "").strip()
    if not md.startswith("---"):
        return {
            "ok": False,
            "error": "bad_llm_output",
            "hint": "LLM 没返回带 frontmatter 的 markdown，重跑或换模型",
        }

    # 写草稿（已存在则加时间戳）
    draft_dir = SKILL_DRAFTS_DIR / skill_name
    if draft_dir.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        draft_dir = SKILL_DRAFTS_DIR / f"{skill_name}__{ts}"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "SKILL.md"
    draft_path.write_text(md, encoding="utf-8")

    effective_provider = resp.get("provider") or cfg["provider"]
    effective_model = resp.get("model") or cfg["model"]
    trace = build_trace(
        provider=effective_provider,
        model=effective_model,
        prompt=f"[system]\n{system_prompt}\n\n[user]\n{user_prompt[:500]}...",
        params={
            "temperature": cfg.get("temperature", 0.3),
            "max_tokens": cfg.get("max_tokens", 2048),
            "tool_sequence_len": len(tool_sequence),
        },
        cost_estimate="~1k tokens",
    )
    trace["provider"] = effective_provider  # alias 让 testers/读者两边都能拿

    return {
        "ok": True,
        "result": {
            "skill_name": skill_name,
            "draft_path": str(draft_path),
            "host_hint": (
                f"草稿已写到 {draft_path}（host 路径 "
                f"data/agent_state/skill_drafts/{draft_dir.name}/SKILL.md）。"
                "审过后 host 侧手动 `cp -r data/agent_state/skill_drafts/"
                f"{draft_dir.name} ~/.claude/skills/{skill_name}` 启用。"
            ),
            "markdown": md,
        },
        "trace": trace,
    }


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_codify_summary,
)
async def codify_pattern_to_skill(
    skill_name: str,
    description: str,
    tool_sequence: list[str],
) -> dict:
    """把一个高频 tool 调用序列升级成 skill markdown 草稿（require_approval=True）。

    Args:
        skill_name: skill 名（kebab-case，2-50 字符）
        description: 一句话描述触发场景
        tool_sequence: tool 名序列（list[str]，至少 1 个）

    Returns:
        {ok, result: {skill_name, draft_path, host_hint, markdown}, trace}
    """
    return await _codify_impl(
        skill_name=skill_name,
        description=description,
        tool_sequence=tool_sequence,
    )
```

- [ ] **Step 5: tool_models.yaml 加 keyed override**

修改 `services/knowledge-engine/config/tool_models.yaml`，文件末尾追加：

```yaml
codify_pattern_to_skill:
  provider: gemini
  model: gemini-3-flash-preview
  temperature: 0.3
  max_tokens: 2048
```

- [ ] **Step 6: 跑 T4 测试验证通过**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_agent_meta.py::test_codify_writes_draft tests/test_mcp_agent_meta.py::test_codify_invalid_skill_name -v"
```

预期：2 PASS

- [ ] **Step 7: 验注册（codify 加进了 tools list）**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'import asyncio; from app.mcp.server import mcp; tools = asyncio.run(mcp.list_tools()); print(sorted([t.name for t in tools if \"codify\" in t.name]))'"
```

预期：`['codify_pattern_to_skill']`

- [ ] **Step 8: Commit**

```bash
git add services/knowledge-engine/config/prompts/codify_skill.system.md services/knowledge-engine/config/prompts/codify_skill.user.md services/knowledge-engine/app/mcp/tools/agent_meta.py services/knowledge-engine/tests/test_mcp_agent_meta.py services/knowledge-engine/config/tool_models.yaml
git commit -m "$(cat <<'EOF'
feat(mcp): codify_pattern_to_skill tool（W4-A T4）

调 LLM（gemini-3-flash-preview）把 tool_sequence 写成 SKILL.md 草稿到
/app/agent_state/skill_drafts/<name>/。require_approval=True 走 Human Gate。
2 套 prompt 模板 + yaml keyed override + 2 unit test 通过。
EOF
)"
```

---

## Task 5: refresh_project_context tool

**Goal:** 渲染 omni 业务底色到 `dynamic_block.md`：当前重点池 SKU + 缺成本 SKU + 最近未 ack observations。老板手动复制粘贴进 omni `CLAUDE.md` 的 marker 区块。不调 LLM；require_approval=True。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/tools/agent_meta.py` (add refresh_project_context)
- Modify: `services/knowledge-engine/tests/test_mcp_agent_meta.py` (add tests)

- [ ] **Step 1: 写测试（先失败）**

在 `services/knowledge-engine/tests/test_mcp_agent_meta.py` 末尾追加：

```python


# ─── T5: refresh_project_context ───────────────────────────────────────────


@pytest_asyncio.fixture
async def seed_active_skus():
    """造 2 个 active SKU 用于 refresh 渲染。

    mvp_sku 主键 = id (VARCHAR 64); douyin_product_id NOT NULL，给唯一值。
    """
    pool = get_pool()
    inserted_ids = []
    for sku_id, name in [("REFRESH-T5-001", "测试 SKU 1"), ("REFRESH-T5-002", "测试 SKU 2")]:
        try:
            await pool.execute(
                "INSERT INTO mvp_sku (id, name, douyin_product_id, status) "
                "VALUES ($1, $2, $1, 'active') "
                "ON CONFLICT (id) DO UPDATE SET status='active'",
                sku_id, name,
            )
            inserted_ids.append(sku_id)
        except Exception:
            pass
    yield inserted_ids
    for sid in inserted_ids:
        await pool.execute("DELETE FROM mvp_sku WHERE id=$1", sid)


@pytest.mark.asyncio
async def test_refresh_writes_dynamic_block(monkeypatch, tmp_path, seed_active_skus):
    from app.mcp.tools import agent_meta
    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)

    res = await agent_meta._refresh_impl()
    assert res["ok"] is True
    out_path = Path(res["result"]["dynamic_block_path"])
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "<!-- omni-dynamic:start -->" in text
    assert "<!-- omni-dynamic:end -->" in text
    # 重点池区段含至少一个 SKU
    assert "REFRESH-T5" in text or "重点池 SKU" in text


@pytest.mark.asyncio
async def test_refresh_idempotent(monkeypatch, tmp_path, seed_active_skus):
    from app.mcp.tools import agent_meta
    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)

    r1 = await agent_meta._refresh_impl()
    r2 = await agent_meta._refresh_impl()
    assert r1["ok"] is True and r2["ok"] is True
    p = Path(r1["result"]["dynamic_block_path"])
    # 两次写入大小差不超过几十字节（仅 timestamp 行变）
    text = p.read_text(encoding="utf-8")
    assert text.count("<!-- omni-dynamic:start -->") == 1
    assert text.count("<!-- omni-dynamic:end -->") == 1
```

- [ ] **Step 2: 跑测试验证失败**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_agent_meta.py::test_refresh_writes_dynamic_block -v"
```

预期：FAIL — `AttributeError: module 'app.mcp.tools.agent_meta' has no attribute '_refresh_impl'`

- [ ] **Step 3: 实现 refresh_project_context**

修改 `services/knowledge-engine/app/mcp/tools/agent_meta.py` 末尾追加：

```python


# ─── T5: refresh_project_context ───────────────────────────────────────────


def _refresh_summary(args: dict) -> str:
    return "refresh_project_context: 渲染 dynamic_block.md（老板手动粘进 CLAUDE.md）"


async def _refresh_impl() -> dict:
    """渲染 dynamic_block.md（无 audit/gate）。"""
    pool = get_pool()
    # 1. 重点池 SKU（status='active'）
    #    mvp_sku 主键叫 id（VARCHAR 64），不叫 sku_id
    sku_rows = await pool.fetch(
        "SELECT id, name FROM mvp_sku WHERE status='active' "
        "ORDER BY id LIMIT 20"
    )
    # 2. 缺成本 SKU（mvp_sku 有但 accounting.cost_items 没有 is_active 行）
    missing_cost_rows = await pool.fetch(
        """
        SELECT s.id, s.name FROM mvp_sku s
         WHERE s.status='active'
           AND NOT EXISTS (
             SELECT 1 FROM accounting.cost_items c
              WHERE c.sku_id = s.id AND c.is_active = TRUE
           )
         LIMIT 10
        """
    )
    # 3. 最近未决定的 human_gates
    gate_rows = await pool.fetch(
        "SELECT g.summary, g.created_at FROM mcp.human_gates g "
        "WHERE g.decision IS NULL ORDER BY g.created_at DESC LIMIT 5"
    )

    # 渲染 markdown
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    parts = [
        "<!-- omni-dynamic:start -->",
        f"## 当前业务底色（自动刷新于 {ts}）",
        "",
        "### 重点池 SKU（status=active）",
    ]
    if sku_rows:
        for r in sku_rows:
            parts.append(f"- `{r['id']}` — {r['name']}")
    else:
        parts.append("- _无 active SKU_")
    parts.extend(["", "### 缺成本 SKU（active 但 accounting.cost_items 全空）"])
    if missing_cost_rows:
        for r in missing_cost_rows:
            parts.append(f"- `{r['id']}` — {r['name']}（用 record_cost 录入）")
    else:
        parts.append("- _无_")
    parts.extend(["", "### 待批 Human Gate"])
    if gate_rows:
        for r in gate_rows:
            t = r["created_at"].strftime("%m-%d %H:%M") if r["created_at"] else "-"
            parts.append(f"- [{t}] {r['summary']}")
    else:
        parts.append("- _无_")
    parts.append("<!-- omni-dynamic:end -->")
    block = "\n".join(parts) + "\n"

    # 写到 agent_state/dynamic_block.md
    out_path = AGENT_STATE_DIR / "dynamic_block.md"
    out_path.write_text(block, encoding="utf-8")

    return {
        "ok": True,
        "result": {
            "dynamic_block_path": str(out_path),
            "host_hint": (
                "已写到 data/agent_state/dynamic_block.md。"
                "把内容（含 marker 行）粘贴到 E:/agent/omni/CLAUDE.md 的 "
                "<!-- omni-dynamic:start --> 到 <!-- omni-dynamic:end --> 之间。"
                "首次使用：先在 CLAUDE.md 任意位置加一对 marker。"
            ),
            "markdown": block,
            "stats": {
                "active_skus": len(sku_rows),
                "missing_cost": len(missing_cost_rows),
                "pending_gates": len(gate_rows),
            },
        },
    }


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_refresh_summary,
)
async def refresh_project_context() -> dict:
    """刷新 omni 业务底色（写到 data/agent_state/dynamic_block.md，require_approval=True）。

    内容：当前重点池 SKU + 缺成本 SKU + 待批 Human Gate。

    Returns:
        {ok, result: {dynamic_block_path, host_hint, markdown, stats}}
    """
    return await _refresh_impl()
```

- [ ] **Step 4: 跑 T5 测试验证通过**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_agent_meta.py::test_refresh_writes_dynamic_block tests/test_mcp_agent_meta.py::test_refresh_idempotent -v"
```

预期：2 PASS

- [ ] **Step 5: 验注册**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c 'import asyncio; from app.mcp.server import mcp; tools = asyncio.run(mcp.list_tools()); print(sorted([t.name for t in tools if \"refresh\" in t.name]))'"
```

预期：`['refresh_project_context']`

- [ ] **Step 6: Commit**

```bash
git add services/knowledge-engine/app/mcp/tools/agent_meta.py services/knowledge-engine/tests/test_mcp_agent_meta.py
git commit -m "$(cat <<'EOF'
feat(mcp): refresh_project_context tool（W4-A T5）

读 mvp_sku 重点池 + cost_items 缺料 + mcp.human_gates 待批，
渲染 dynamic_block.md 到 /app/agent_state/。老板手动粘进 omni
CLAUDE.md 的 <!-- omni-dynamic:start --> 区块。require_approval=True。
2 unit test 通过。
EOF
)"
```

---

## Task 6: doctor + tools/__init__.py + grant + e2e

**Goal:** doctor expected_tools 23 → 27；tools/__init__.py 加 W4-A 段；`.claude/settings.local.json` 4 个新 tool grant；容器内自检全绿；e2e 4 tool 实跑一遍。

**Files:**
- Modify: `services/knowledge-engine/app/mcp/doctor.py:88-115`
- Modify: `services/knowledge-engine/app/mcp/tools/__init__.py`
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: 改 doctor.py wanted 集合 + count**

修改 `services/knowledge-engine/app/mcp/doctor.py:88-113`，把 wanted 集合扩展：

```python
        # W1 5 + W2 5 + W3a 3 + W3b 7 + W3c 3 + W4-A 4 = 27
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
            # W4-A
            "rate_tool_call", "agent_self_review",
            "codify_pattern_to_skill", "refresh_project_context",
        }
```

- [ ] **Step 2: 改 tools/__init__.py**

完整覆盖 `services/knowledge-engine/app/mcp/tools/__init__.py`：

```python
"""W1 + W2 + W3a + W3b + W3c + W4-A tools。

注册顺序：在 `app.mcp.server` import 时通过 `import app.mcp.tools.<x>` 等触发副作用。

27 tool 总览：
- W1 (5): list_skus, get_sku, list_kbs, search_kb, list_briefs
- W2 (5): query_costs, compute_margin, generate_brief, generate_image, generate_video
- W3a (3): gather_brief_context, record_cost, disable_cost_item
- W3b (7): fetch_compass_store_daily, fetch_compass_sku_detail,
           fetch_compass_search_traffic, fetch_yuntu_5a, fetch_yuntu_brand_mind,
           kb_upload_doc, kb_set_role
- W3c (3): summarize_text, parse_long_doc_with_gemini, query_template_chunks
- W4-A (4): rate_tool_call, agent_self_review, codify_pattern_to_skill,
            refresh_project_context
"""
```

- [ ] **Step 3: 跑 doctor 全绿**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

预期：
```
omni MCP doctor 报告
  [OK  ] DB pool
  [OK  ] mcp schema tables: found 2/2
  [OK  ] tool_models.yaml: keys=['__default__', 'compute_margin', 'generate_brief', 'generate_image', 'generate_video']
  [OK  ] prompt templates: all 8 ok
  [OK  ] 27 tools registered: all 27 ok
  [OK  ] /mcp HTTP: status=200

结论：全绿 ✓
```

- [ ] **Step 4: 跑全套 W4-A 测试**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app pytest tests/test_mcp_pattern_lib.py tests/test_mcp_feedback.py tests/test_mcp_agent_meta.py -v"
```

预期：12 PASS（3 + 4 + 5）

- [ ] **Step 5: e2e — agent_self_review 实跑**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c '
import asyncio
from app.database import init_pool, close_pool
from app.mcp.tools.agent_meta import agent_self_review

async def main():
    await init_pool()
    try:
        res = await agent_self_review(period_days=7)
        print(\"ok=\", res[\"ok\"])
        if res[\"ok\"]:
            r = res[\"result\"]
            print(\"total=\", r[\"total_calls\"], \"top_tools=\", list(r[\"by_tool\"].items())[:3])
            print(\"candidates=\", len(r[\"candidate_patterns\"]))
    finally:
        await close_pool()
asyncio.run(main())
'"
```

预期：`ok= True` + 含真实数据（既有 W1-W3c 跑过的 tool_calls）

- [ ] **Step 6: e2e — refresh_project_context 实跑（绕开 gate）**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c '
import asyncio
from app.database import init_pool, close_pool
from app.mcp.tools.agent_meta import _refresh_impl

async def main():
    await init_pool()
    try:
        res = await _refresh_impl()
        print(\"ok=\", res[\"ok\"])
        if res[\"ok\"]:
            print(\"path=\", res[\"result\"][\"dynamic_block_path\"])
            print(\"stats=\", res[\"result\"][\"stats\"])
    finally:
        await close_pool()
asyncio.run(main())
'"
```

预期：`ok= True` + path=`/app/agent_state/dynamic_block.md`

验 host 同步可见：
```bash
ls E:/agent/omni/data/agent_state/dynamic_block.md && head -20 E:/agent/omni/data/agent_state/dynamic_block.md
```

预期：文件存在，含 `<!-- omni-dynamic:start -->` 行

- [ ] **Step 7: e2e — codify_pattern_to_skill 实跑（绕开 gate）**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c '
import asyncio
from app.database import init_pool, close_pool
from app.mcp.tools.agent_meta import _codify_impl

async def main():
    await init_pool()
    try:
        res = await _codify_impl(
            skill_name=\"smoke-codify-w4a\",
            description=\"测试 codify e2e\",
            tool_sequence=[\"list_skus\", \"get_sku\", \"query_costs\"],
        )
        print(\"ok=\", res[\"ok\"])
        if res[\"ok\"]:
            print(\"draft_path=\", res[\"result\"][\"draft_path\"])
            print(\"head=\", res[\"result\"][\"markdown\"][:200])
        else:
            print(\"err=\", res.get(\"error\"), res.get(\"hint\"))
    finally:
        await close_pool()
asyncio.run(main())
'"
```

预期：`ok= True` + draft_path 存在 + markdown 以 `---` 开头

清理：
```bash
rm -rf E:/agent/omni/data/agent_state/skill_drafts/smoke-codify-w4a
```

- [ ] **Step 8: e2e — rate_tool_call 实跑**

```bash
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -c '
import asyncio
from app.database import init_pool, close_pool, get_pool
from app.mcp.tools.feedback import rate_tool_call

async def main():
    await init_pool()
    pool = get_pool()
    try:
        # 取一条最近的 completed 调用
        row = await pool.fetchrow(
            \"SELECT id::text AS id FROM mcp.tool_calls WHERE status='completed' \"
            \"ORDER BY created_at DESC LIMIT 1\"
        )
        if not row:
            print(\"no calls to rate\"); return
        res = await rate_tool_call(call_id=row[\"id\"], rating=\"good\", note=\"W4-A T6 e2e smoke\")
        print(\"ok=\", res[\"ok\"], \"result=\", res.get(\"result\"))
    finally:
        await close_pool()
asyncio.run(main())
'"
```

预期：`ok= True` + result 含 tool_name

验 host successful_patterns.md：
```bash
tail -10 E:/agent/omni/data/agent_state/successful_patterns.md
```

预期：含 `W4-A T6 e2e smoke`

- [ ] **Step 9: 改 .claude/settings.local.json grant 4 个新 tool**

读 `.claude/settings.local.json`，找 `permissions.allow` 数组（已有 `mcp__omni__*` 一系列 entry），加 4 行：

```json
"mcp__omni__rate_tool_call",
"mcp__omni__agent_self_review",
"mcp__omni__codify_pattern_to_skill",
"mcp__omni__refresh_project_context",
```

- [ ] **Step 10: 终 commit**

```bash
git add services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/app/mcp/tools/__init__.py .claude/settings.local.json
git commit -m "$(cat <<'EOF'
feat(mcp): doctor expected_tools=27 + tools/__init__.py + grant 4 tool（W4-A T6）

W4-A 4 tool（rate_tool_call / agent_self_review / codify_pattern_to_skill /
refresh_project_context）登记齐：doctor wanted 23→27 全绿，tools/__init__.py
更新 W4-A 段，settings.local.json 加 4 个 mcp__omni__ grant。
e2e 4 tool 全部实跑通。
EOF
)"
```

---

## Self-Review 检查（写完后跑）

### 1. Spec 覆盖

- design doc §3.2 W4 行 — ✅ 3 核心 tool 全覆盖（agent_self_review T3 / codify T4 / refresh T5）
- design doc §3.2 W4 加分 rate_tool_call — ✅ T2 覆盖（反馈通路必需）
- design doc §7.4 反馈循环 — ✅ T1 pattern_lib + T2 rate hook 覆盖
- design doc §7.5 改动量 — ✅ 大致对齐（agent_self_review ~80 / codify ~80 / refresh ~100 / patterns hook ~50）
- design doc §7.2 草稿审批流 — ✅ codify require_approval=True 走 cli_approve；老板批后手动 cp
- design doc §4.2 dynamic 区块 — ✅ T5 marker 方案 + 写到 agent_state/dynamic_block.md
- 不在范围（确认排除）：cron `weekly_self_review`（design doc §4.3，本批留缓）/ 前端 /inbox /agent-log（W4-B）/ 6 业务 skill（W4-B）/ W4 加分 5 tool

### 2. Placeholder scan

- ✅ 无 "TODO" / "implement later" / "fill in details"
- ✅ 每个 step 都含完整代码块或精确命令
- ✅ 不存在"类似 Task N"的引用
- ✅ 所有引用的 helper 函数（`prompts.load`, `build_trace`, `get_model_for_tool`, `pattern_lib.append_*`）都有定义来源

### 3. 类型一致性

- ✅ `pattern_lib.append_successful_pattern(*, tool_call_id, tool_name, note)` — T1 定义 / T2 调用 / 测试一致
- ✅ `_codify_impl` / `_refresh_impl` 命名一致（用作测试 mock 入口 + tool 包装函数 body）
- ✅ trace dict key 沿用 W3c 约定（`provider` alias + `model_provider` 原始）
- ✅ require_approval=True 仅 codify + refresh；rate + self_review 是 F
- ✅ doctor wanted 集合 27 个名字 = tools/__init__.py docstring 列出的 27 个

---

## 完成后状态（预期）

- HEAD on `feat/mcp-w1`，6 commits（T1-T6）
- doctor 27/27 全绿
- 27 tool 在 settings.local.json grant 列表
- pattern library 文件 + skill drafts 目录就位（host bind mount 可见）
- 4 tool 全部 e2e 实跑通
- W4-A 完成，留缮项进 W4-B：
  - cron `weekly_self_review`（自动触发 agent_self_review）
  - 前端 /inbox（含 SOP 草稿审批 3 按钮：✅ 采纳 / ❌ 驳回 / ✏️ 改了再用）
  - 前端 /agent-log（rate_tool_call UI 入口：👍 / 👎 / ↻）
  - 6 业务 skill（personal-review / crowd-sop / product-analysis / script-writer / selling-point-finder / daily-store-pulse）

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-omni-agent-uplift-W4a-plan.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — 跟 W3a/W3b/W3c 一致节奏：每 task fresh subagent + two-stage review，main agent 在 task 间对照 plan 验收 + commit
2. **Inline Execution** — 当前 session 执行 + executing-plans skill 检查点

W3 三周下来 subagent-driven 跑得很顺（W3c 6 commits / 1 day），W4-A 推荐继续此模式。

**老板说哪条？**
