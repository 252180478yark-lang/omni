# Omni Agent 化升级设计 (X 方案)

> **文档版本**: v1.0  
> **日期**: 2026-05-03  
> **状态**: brainstorming 完成，待用户审批后进入 implementation plan  
> **适用读者**: 项目作者本人（自用）/ 后续 implementation plan 编写者

---

## 🔄 重启 / /clear 后如何继续

**用户**：在 Claude Code 终端进 `E:\agent\omni` 目录，说一句：
- 「继续 omni agent 化」
- 或「进 W1」/「进 W2」/「进 W3」/「进 W4」（按当前阶段）
- 或「审 spec」（如果还没批 spec）

**Claude（我）**会自动：
1. 读 `~/.claude/projects/E--agent-omni/memory/project_omni_agent_uplift_status.md` 定位当前阶段
2. 读本文档对应 §节 拿细节
3. 按下一未完成项推进（审 spec / writing-plans / 落 W*）

**进度跟踪文件**（每完成一项自动更新）：
`~/.claude/projects/E--agent-omni/memory/project_omni_agent_uplift_status.md`

---

## 概要

把现状的"RAG 工作流应用"升级成"个人智能体工作台"，方式是采用 **X 方案**：

> Claude Code（Max 订阅）作为 agent 大脑 + omni 暴露 MCP server 提供 tool + 多 provider 作为专家模型

放弃了"在 omni 内部自写 agent loop"的 Y 方案，因为：

1. 用户已订 Claude Max（agent 主决策成本 = $0）
2. Claude Code 自带 agent loop / memory / human gate / skills，重写一份是浪费
3. 个人自用，不需要"网页 chat 入口给所有人访问"的能力
4. omni 的强项是 RAG / 业务数据 / SKU 编排——这些以 tool 形式暴露最自然

### 关键约束（来自用户拍板）

| 约束 | 来源 |
|---|---|
| omni 是个人自用，不上线、不多人 | feedback_personal_use_no_overengineering.md |
| 主决策模型固定 Claude（Max 覆盖），tool 模型用户后续 yaml 自行调 | feedback_model_selection.md |
| 不爱用 DeepSeek，起步默认全 Sonnet | 同上 |
| 4 项能力全要：自主对话路由 + 自主流程驱动 + 主动观察 + 跨会话记忆 | 用户澄清问答 |
| 时间窗：3-4 周大重构 OK | 用户澄清问答 |
| Human Gate 高度保守：4 类签字（Brief/平台动作/数字/任何"多一步"动作）| 用户澄清问答 |
| 偏好 Claude(Sonnet+Opus) / OpenAI(gpt-image-2) / Seedance(2.0) / Gemini(长文) / Ollama(隐私) | feedback_model_selection.md |
| **全局写作风格**：所有生成内容必须"说人话 + 反幻觉 + 去 AI 化"，5 个注入点强制 | feedback_writing_style.md |

### 4 项能力如何被覆盖

| 能力 | X 方案下的实现 |
|---|---|
| 自主对话路由 | Claude Code 主对话 + omni MCP tool 注册中心 |
| 自主流程驱动 | Claude Opus 自带 plan 能力 + 6 个业务 skill SOP |
| 主动观察 | omni cron worker（DeepSeek 替换为 Sonnet）+ headless `claude -p` 触发深度复盘 |
| 跨会话记忆 | Claude Code 自带 `~/.claude/projects/.../memory/` + omni Postgres 业务事实 |

### 月成本预估

| 项 | 成本 |
|---|---|
| Agent 主决策（Claude Opus/Sonnet） | $0（Max 订阅覆盖）|
| Tool 内部 LLM 调用（默认 Sonnet）| $40-100 |
| 生图（gpt-image-2）/ 生视频（Seedance 2.0）| 按使用量 |
| 总（不含图/视频生成）| **~$40-100/月** |

---

## §1 整体架构

### 1.1 总架构图

```
☁️ Anthropic 云：Claude Opus 4.7  ($0 额外，Max 订阅覆盖)
                    ▲
                    │ HTTPS
┌───────────────────┴──────────────────────────────────────────┐
│ 💻 Claude Code (CLI / IDE)                                   │
│   • agent loop / human gate UI / 跨会话记忆                  │
│   • skills (~/.claude/skills/, 56+ 已装 + 新增 6 业务)      │
│   • memory (~/.claude/projects/.../memory/, 自动累积)        │
└───────────────────┬──────────────────────────────────────────┘
                    │ MCP 协议（HTTP/SSE）
┌───────────────────▼──────────────────────────────────────────┐
│ 🆕 omni MCP server   (寄宿 knowledge-engine 8002 内)          │
│   app/mcp/server.py        FastMCP 入口                      │
│   app/mcp/audit.py         @tool_with_audit 装饰器           │
│   app/mcp/human_gate.py    require_approval 拦截 + 等批      │
│   app/mcp/model_config.py  yaml 加载 + override 支持         │
│   app/mcp/tools/           按域分文件                        │
│     ├─ kb.py            search_kb / list_kbs / kb_*         │
│     ├─ accounting.py    query_costs / compute_margin        │
│     ├─ sku.py           list_skus / get_sku / run_sku_orch  │
│     ├─ scout.py         fetch_compass_* / fetch_yuntu_*    │
│     ├─ briefs.py        list_briefs / generate_brief        │
│     ├─ recordings.py    list_recordings / insights          │
│     └─ media.py         generate_image / generate_video    │
└───────────────────┬──────────────────────────────────────────┘
                    │ Python import (同进程) | HTTP (跨服务)
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ omni 现有 8 个微服务（不动）                                  │
│  knowledge-engine (8002) ← MCP server 寄宿在这                │
│    services/ 28 个文件 (rag_chain / sku_orch / briefs ...)    │
│  ai-provider-hub (8001) ← tool 内部按需调专家模型             │
│    deepseek / gemini / seedance / seedream / kling / ollama / │
│    openai / anthropic                                          │
│  scout-agent (8009) ← tool 通过 HTTP 调                       │
│  其他 5 个 ← 第 1 期不暴露 tool，现状保留                     │
└──────────────────────────────────────────────────────────────┘
                    │
┌───────────────────▼──────────────────────────────────────────┐
│ 💾 Postgres (infra-core, 不变)                                │
│   现有 schema 全保留                                          │
│   🆕 mcp.tool_calls       审计：每次调用记一行                │
│   🆕 mcp.human_gates      待你批的 require_approval=True      │
│   🆕 mcp.observations     主动巡检与反思的输出                │
│   🆕 cost_items           阶段二要做                          │
└──────────────────────────────────────────────────────────────┘

🌐 Frontend (Next.js 3000, 全保留 + 加 2 个新页)
  /knowledge  /sku/[id]  /scout  /cost  /decisions  /products
  /workspace  /chat (备用 RAG 入口)
  🆕 /inbox        Human Gate 待办（手机批） + 观察通知
  🆕 /agent-log    agent 行动日志（看 Claude Code 干了啥）
```

### 1.2 关键架构决策

| 决策 | 选择 | 为什么 |
|---|---|---|
| 是否新建 `agent-runtime` 服务 | **不新建**，作为 knowledge-engine 内子模块 | 个人用，单进程合并、调试简单 |
| MCP 库 | **FastMCP** (`pip install fastmcp`) | Pythonic、与 FastAPI 风格一致、原生 streamable HTTP |
| MCP 传输 | **HTTP/SSE**（不用 stdio）| 跨进程稳定，未来手机/远程也方便 |
| Tool 颗粒度 | 细颗粒（30 个左右第一期）| LLM 自由组合比"大而全"易调试 |
| 跨服务 tool（如 fetch_compass）| scout-agent 加 internal HTTP endpoint，server.py 调 | 不强迫 scout-agent 也跑 MCP server |
| 前端 `/chat` | 保留作 RAG 备用入口（用 Sonnet）| 手机/外面打开能用 |
| Agent runtime | **0 改动**——Claude Code 自带 | X 方案的核心赢面 |

### 1.3 智能系统的分层

| 角色 | 在哪 | 类比 |
|---|---|---|
| Claude Opus 4.7 模型 | Anthropic 云 | 大脑**皮层**（推理）|
| Claude Code（loop + memory + skills）| 你电脑 ~/.claude/ | 大脑**前额叶**（决策、记忆、规划）|
| omni 系统（tool + 数据）| 你电脑 E:\agent\omni | **身体**（手脚、眼睛、内脏数据库）|

### 1.4 业务事实 vs 合作偏好的存储分工

| 类型 | 例子 | 住哪 | 谁管 |
|---|---|---|---|
| **业务事实** | "X 产品成本 38 元"、SKU/decisions 日志 | omni Postgres | omni 自己 |
| **合作偏好** | "老板偏好先框架后内容"、"自用，不上线"| `~/.claude/projects/.../memory/`| Claude Code 自动 |
| **当前对话上下文** | "刚才说的 X SKU"、"上一步算出 38 元成本"| Claude Code 会话内 | Claude Code 自动 |

---

## §2 MCP Server 实现 + Tool 协议规范

### 2.1 目录结构

```
services/knowledge-engine/app/mcp/
├── __init__.py
├── server.py                # FastMCP 实例 + 挂载到 main app
├── audit.py                 # @tool_with_audit 装饰器
├── human_gate.py            # 等批/驳/超时机制
├── model_config.py          # tool_models.yaml 加载
├── doctor.py                # 健康检查 CLI
├── types.py                 # ToolSuccess / ToolError TypedDict
└── tools/
    ├── __init__.py
    ├── kb.py                # search_kb, list_kbs, kb_upload_doc, kb_set_role
    ├── accounting.py        # query_costs, compute_margin
    ├── sku.py               # list_skus, get_sku, run_sku_orch, get_sku_orch_status
    ├── scout.py             # fetch_compass_* / fetch_yuntu_* (跨服务 HTTP)
    ├── briefs.py            # list_briefs, generate_brief
    ├── recordings.py        # list_recordings, get_recording, generate_recording_insights
    ├── media.py             # generate_image, generate_video
    ├── templates.py         # query_template_chunks
    └── meta.py              # agent_self_review, codify_pattern_to_skill, refresh_project_context
```

```
services/knowledge-engine/config/
└── tool_models.yaml         # tool → model 映射，运行时单点切换
```

### 2.2 tool_with_audit 装饰器

提供两个职责：
1. **审计**：每次 tool 调用前后写 `mcp.tool_calls` 一行
2. **Human Gate**：require_approval=True 时拦下、写 `mcp.human_gates`、推 /inbox、等批/驳

接口设计：
```python
def tool_with_audit(
    mcp: FastMCP,
    *,
    require_approval: bool = False,
    summary_fn: Callable[[dict], str] | None = None,
    timeout_seconds: int | None = None,  # None = 用默认 3600
    **mcp_kwargs,
)
```

### 2.3 Tool 接口约定（强制规范）

| 项 | 规则 |
|---|---|
| 函数 | `async def`，必须 |
| 类型注解 | 必须（FastMCP 自动从类型生成 JSON schema）|
| docstring | 必须中文描述 + 返回结构示例 |
| 返回 | 必须 dict，必须含 `"ok": bool` |
| 失败 | **return**，不 raise（`{"ok": false, "error": "...", "hint": "..."}`）|
| 副作用/数字 | 设 `require_approval=True`，并写 `summary_fn` |
| 纯查询 | `require_approval=False` |

ToolSuccess / ToolError schema 见 `types.py`：

```python
class ToolSuccess(TypedDict):
    ok: Literal[True]
    # 业务字段...

class ToolError(TypedDict):
    ok: Literal[False]
    error: str          # 机器可读 code
    hint: str           # 给 LLM 的下一步建议
    note: str | None    # 给人看的补充
```

### 2.4 错误返回的 LLM 友好格式

| 错误类型 | 返回示例 |
|---|---|
| 资源不存在 | `{ok:false, error:"sku_not_found", hint:"可调 list_skus 查可用 ID"}` |
| 参数非法 | `{ok:false, error:"invalid_period", hint:"period 须为 7d/30d/90d 之一"}` |
| 第三方失败 | `{ok:false, error:"compass_unreachable", hint:"重试 / 或问用户是否 cookie 过期"}` |
| 用户驳回 | `{ok:false, error:"rejected_by_user", note:"老板说先不动这个 SKU"}` |
| 超时 | `{ok:false, error:"timeout", hint:"任务大, 可拆小批"}` |

### 2.5 模型选择（tool_models.yaml）

#### 起步配置（全 Sonnet 默认，用户后续自行调）

```yaml
__default__:
  provider: anthropic
  model: claude-sonnet-4-6
  temperature: 0.3

compute_margin:
  provider: anthropic
  model: claude-opus-4-7
  temperature: 0.0

generate_brief:
  provider: anthropic
  model: claude-sonnet-4-6
  temperature: 0.7

run_sku_orch:
  provider: anthropic
  model: claude-sonnet-4-6
  temperature: 0.5

generate_recording_insights:
  provider: anthropic
  model: claude-sonnet-4-6

parse_long_doc_with_gemini:
  provider: gemini
  model: gemini-2.5-flash

generate_image:
  provider: openai
  model: gpt-image-2

generate_video:
  provider: seedance
  model: seedance-2.0

chat_about_secret_recording:
  provider: ollama
  model: qwen2.5:32b
```

#### 三层切换粒度

| 想干啥 | 怎么做 | 重启吗 |
|---|---|---|
| 永久把 X tool 换模型 | 改 yaml 一行 | 重启 knowledge-engine |
| 想试几次某 tool 换模型 | 跟 Claude 说"这次用 opus" → tool 接受 `model_override` 参数 | 不用 |
| 全局降级省钱 | 改 `__default__` + 把高配 tool 也改成中配 | 重启 |

### 2.6 ai-hub 现状（已调研，无需改造）

调研于 2026-05-03 通过 Explore agent 确认：

| 检查项 | 文件位置 | 状态 |
|---|---|---|
| 图像 HTTP 路径 | `routers/ai.py:93` POST `/api/v1/ai/images/generate` | ✅ |
| `ImageGenerateRequest.model` 默认 | `schemas/ai.py:54-64` 默认 `"gpt-image-2"` | ✅ |
| openai_provider 已支持的图像 model | `openai_provider.py:21-26` (gpt-image-2 / 1.5 / 1 / 1-mini) | ✅ |
| 生图参考图 | `openai_provider.py:154-163` 转中文约束注入 prompt | ✅ |
| 视频 HTTP 路径 | `routers/ai.py:104` POST `/api/v1/ai/videos/generate` | ✅ |
| 视频状态查询 | `routers/ai.py:113` GET `/api/v1/ai/videos/status/{task_id}` | ✅ |
| seedance_provider 默认 | `config.py:23` `doubao-seedance-2-0-260128` (Seedance 2.0) | ✅ |
| 多参考图实现 | `seedance_provider.py:176-187` `_build_content` 落地 role=reference_image | ✅ |
| BaseProvider 抽象 | `providers/base.py:44-67` chat/embedding/generate_image/generate_video | ✅ |
| Provider 注册 | `providers/registry.py:16-17` ProviderRegistry 单例 | ✅ |

唯一新建：`services/knowledge-engine/app/services/ai_hub_client.py` 统一封装（chat/image/video），约 80 行 thin wrapper（替代各 service 重复 httpx 调用模式）。

### 2.7 Claude Code 端注册

放在 omni 项目根的 `E:\agent\omni\.claude\settings.local.json`（项目级，跟仓库耦合）：

```json
{
  "mcpServers": {
    "omni": {
      "type": "http",
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

如果想"任何目录都能用 omni MCP"，可改放到 `~/.claude/settings.local.json`（用户级）。但项目级更稳——Claude Code 进 omni 项目目录时自动加载，离开就不连。

### 2.8 全局写作风格强制注入（说人话 + 反幻觉 + 去 AI 化）

**所有"生成内容"的 prompt 必须遵守三条强制约束**（用户拍板，全局规范，详见 `feedback_writing_style.md`）：

1. **说人话**：日常对话语气 / 短句 / 直接顶到重点 / 用具体数字 / 不用"综上""值得注意的是"等套话 / 不机械堆"首先/其次"
2. **反幻觉**：只用提供的资料 / KB 没有的直说"没找到" / 数字必须有出处 / 推测加"我猜""可能"
3. **去 AI 化**：删除"作为 AI""以下是""希望对您有帮助" / 无意义 emoji 禁用 / 无意义的 markdown 标题堆叠禁用 / 客套结尾禁用

#### 5 个注入点（落地实施时必做）

| 注入点 | 文件 | 覆盖范围 |
|---|---|---|
| ① 项目级偏好 | `E:\agent\omni\CLAUDE.md` 顶部"老板写作偏好"段 | Claude Code 主对话 |
| ② 共享 prompt 常量 | `app/mcp/prompt_constraints.py` 导出 `ANTI_AI_HUMAN_VOICE` | 内部生成类调用 |
| ③ ai_hub_client 默认注入 | `ai_hub_client.chat()` 加参数 `enforce_human_voice=True`，开则在 system 头拼上常量 | 所有 ai-hub 生成 |
| ④ 每个生成类 tool | docstring + system prompt 头部引用 `ANTI_AI_HUMAN_VOICE` | generate_brief / generate_recording_insights / summarize_text 等 |
| ⑤ Skill SOP 末尾 | `~/.claude/skills/<name>/SKILL.md` 末尾标注"输出遵循 CLAUDE.md 写作偏好" | 6+ 个业务 skill |

#### `ANTI_AI_HUMAN_VOICE` 常量草案

```python
# app/mcp/prompt_constraints.py
ANTI_AI_HUMAN_VOICE = """
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
"""
```

#### CLAUDE.md 注入草案（项目根）

```markdown
# Omni 项目上下文 - 老板偏好

## 写作风格（强制）
回答和生成内容时遵守三条：
1. 说人话：日常对话语气，短句，直接说重点
2. 反幻觉：只用资料里的信息，没有就明说，数字必须有出处
3. 去 AI 化：不写"作为 AI""以下是""希望对您有帮助"，不堆 emoji 和 markdown 标题
反例 / 详细规则见 ~/.claude/projects/E--agent-omni/memory/feedback_writing_style.md
```

#### 实施时的强制检查

- 任何新 tool 的 PR 必须看：system prompt 头部是否拼 `ANTI_AI_HUMAN_VOICE`
- 任何新 skill 的 PR 必须看：SKILL.md 末尾是否标注"遵循 CLAUDE.md 风格"
- 用户审 SOP / Brief / 周报草稿时，看到任何 AI 套话立即驳回，自动写入 `failed_patterns.md`

### 2.9 危险 tool 的二次防护

`.claude/settings.local.json` 黑名单：
```json
{
  "permissions": {
    "deny": [
      "mcp__omni__dy_publish_creative",
      "mcp__omni__send_wecom_message"
    ]
  }
}
```

这层是 Claude Code 客户端阻拦，**Claude 模型连请求都发不出去**——比 require_approval 更刚。

---

## §3 Tool 清单 + 4 周排程

### 3.1 4 周排程总览

| 周 | 主题 | 验收指标 |
|---|---|---|
| W1 | **闭环周** — MCP 底座 + 5 个 tool | Claude Code `/mcp` 看到 omni；能问"我有几个 SKU"、"查 X 在 KB 里" |
| W2 | **算账 + 编排 + 媒体** — cost 表 + 7 个 tool + /cost 页 | 全链路打通：分析 → 算账 → Brief → 生图 → 生视频（每步签字）|
| W3 | **专家模型 + 跨服务** — scout / 多 provider / 素材 / 录音 | 能问"今天罗盘有啥异动"、"近 30 天录音都聊了啥" |
| W4 | **前端收尾 + skill + 进化机制** — /inbox + /agent-log + 6 业务 skill + 反馈循环 | 手机能批待办；6 套 SOP 能在 Claude Code 触发；点 👍/👎 反馈生效 |

### 3.2 Tool 完整清单（28 个第一期 + 6 个 W4 加分）

总计 W1+W2+W3+W4 = 5+7+13+3 = **28 个**第一期必出。W4 加分项另计 6 个，按需。

`appr` 列：T = require_approval=True，F = 纯查询

#### W1（5 个）— 让闭环跑起来

| tool | 一句描述 | appr | 内部实现路径 |
|---|---|---|---|
| `list_skus(status?)` | 列 SKU 主数据 | F | 直接查 `mvp_sku` 表 |
| `get_sku(sku_id)` | 单 SKU 详情 + 库存 + 近期订单 | F | 查 mvp_sku + content_studio.* |
| `search_kb(query, kb_ids?, kb_roles?, top_k?)` | KB 检索（带 role 分区）| F | 调 `rag_chain.retrieve_multi_kb` |
| `list_kbs(role?)` | 列所有 KB | F | 调 `ingestion.list_kbs` |
| `list_briefs(sku_id?, status?)` | 列已生成的 Brief | F | 查 briefs 表 |

#### W2（7 个）— 算账 + 编排 + 媒体

| tool | 一句描述 | appr | model |
|---|---|---|---|
| `query_costs(sku_id?, category?, period?)` | 查成本明细 | F | 不调 LLM |
| `compute_margin(sku_id, sale_price)` | 算净利率 + breakdown | T | opus-4-7 / temp 0.0 |
| `run_sku_orch(sku_id, target_purpose?)` | 跑 SKU 9 步编排 | T | sonnet-4-6 |
| `get_sku_orch_status(orch_id)` | 查编排状态 | F | 不调 LLM |
| `generate_brief(sku_id, audience?, purpose?)` | 单步生成 Brief 草稿 | T | sonnet-4-6 / temp 0.7 |
| `generate_image(prompt, refs?, aspect?, n?)` | 生图（默认 gpt-image-2）| T | openai/gpt-image-2 |
| `generate_video(prompt, refs?, duration_sec?)` | 生视频（默认 Seedance 2.0 多参考图）| T | seedance/2.0 |

#### W3（13 个）— 专家模型 + 跨服务 + 录音管理

| tool | 一句描述 | appr | 内部调 |
|---|---|---|---|
| `fetch_compass_store_daily(date?)` | 罗盘全店日报 | F | scout-agent runbook A |
| `fetch_compass_sku_detail(sku_id, date?)` | 罗盘单 SKU | F | scout-agent runbook B |
| `fetch_compass_search_traffic(date?)` | 罗盘搜索/流量/营销 | F | scout-agent runbook D |
| `fetch_yuntu_5a(date?)` | 云图 5A 资产 | F | scout-agent runbook G |
| `fetch_yuntu_brand_mind(date?)` | 品牌心智 3 指标 | F | scout-agent runbook H |
| `summarize_text(text, instruction?)` | 海量文本摘要 | F | sonnet（用户后改）|
| `parse_long_doc_with_gemini(file_path)` | 200 页+ PDF 长文档解析 | F | gemini-2.5-flash |
| `query_template_chunks(type, industry?, duration_sec?)` | 按结构标签筛素材 | F | hybrid_search + metadata |
| `generate_recording_insights(period, recording_ids?)` | 录音洞察周报 | F | sonnet（用户后改）|
| `list_recordings(kb_id?, period?)` | 列录音 | F | 不调 LLM |
| `get_recording(recording_id)` | 取录音原文 + 摘要 chunks | F | 不调 LLM |
| `kb_upload_doc(kb_id, file_path)` | 上传文档入库 | T | ingestion 现有 |
| `kb_set_role(kb_id, kb_role)` | 改 KB 角色 | T | PATCH endpoint 现有 |

#### W4（3 个）— 进化机制

| tool | 一句描述 | appr | 用途 |
|---|---|---|---|
| `agent_self_review(period?)` | 反思周报，复盘 tool_calls + 用户评分 | F | 进化机制 |
| `codify_pattern_to_skill(skill_name, description, tool_sequence)` | 把高频 pattern 升级成 skill 草稿 | T | 进化机制 |
| `refresh_project_context()` | 自动更新 CLAUDE.md dynamic 区块 | T | 业务底色刷新 |

#### W4 加分（6 个，按需上）

| tool | 一句描述 | appr |
|---|---|---|
| `dy_publish_creative(sku_id, draft_id)` | 抖店发布商品/创意 | T（高危）|
| `send_wecom_message(channel, content)` | 企微通知 | T |
| `save_decision(...)` | 写一行 decisions 日志 | F |
| `schedule_observation(cron, prompt)` | 设主动巡检任务 | T |
| `rate_tool_call(call_id, rating, note?)` | 给一次调用打 👍/👎 | F |
| `generate_image_compare(prompt, models)` | 多模型 A/B 对比生图 | T |

### 3.3 6 个业务 Skill 清单（住 `~/.claude/skills/`）

跟原阶段二"6 任务模板"一一对应，但变成 markdown 文件：

| skill | 触发场景 | 内部 tool 序列 |
|---|---|---|
| `personal-review` | "回顾我最近的录音" | list_recordings → generate_recording_insights → search_kb(personal_log) → 出周报 |
| `crowd-sop` | "圈一个 X 的人群包" | search_kb(authoritative+methodology) → query_template_chunks → 出策略 |
| `product-analysis` | "分析 X 产品的健康度" | get_sku → query_costs → fetch_compass_sku_detail → search_kb 历史决策 → 报告 |
| `script-writer` | "给 X 写个脚本" | get_sku → search_kb(template+audience) → query_template_chunks → generate_brief |
| `selling-point-finder` | "找 X 的卖点" | get_sku → search_kb(template) → query_template_chunks → 三类卖点 |
| `daily-store-pulse` | "看一下今天店铺咋样" | fetch_compass_store_daily → fetch_yuntu_brand_mind → search_kb 异动模板 → 日报 |

### 3.4 改动量（X 方案 4 周）

| 类型 | 文件数 | 行数（估）|
|---|---|---|
| 新增（mcp/ 顶层模块）| 7 个 .py（server/audit/human_gate/model_config/doctor/types/__init__）| ~500 |
| 新增（mcp/tools/）| 10 个 .py（含 __init__）| ~700 |
| 新增（数据库 migration）| 3 个 .sql（016/017/018）| ~120 |
| 新增（前端页）| 3 页（/cost /inbox /agent-log）| ~1500 行 TSX |
| 新增（业务 skill）| 6 个 .md（住 ~/.claude/skills/）| ~600 |
| 新增（ai_hub_client.py）| 1 个 | ~80 |
| 新增（observation/ 模块）| 4 个 .py（4 个观察任务 + 共享）| ~250 |
| 改动 现有 service | 极少（scout-agent 加几个 internal endpoint）| ~150 |
| 删除现有代码 | 0（前期）| — |
| 现有 RAG 链路改动 | **0** | — |
| **合计 omni 新代码** | ~25 个新文件 | **~3900 行**（含前端 TSX）|

---

## §4 Memory + Observation

### 4.1 Memory 三层分工

| 类型 | 例子 | 住哪 | 谁管 | omni 要写代码吗 |
|---|---|---|---|---|
| 合作偏好 | "老板偏好先框架后内容" | `~/.claude/projects/.../memory/` | Claude Code 自动 | ❌ |
| 当前对话上下文 | "刚才说的 X SKU" | Claude Code 会话内 | Claude Code 自动 | ❌ |
| 业务事实 | SKU/cost/KB/decisions/orchestrations | omni Postgres | omni 自己 | ✅ 已有不动 |

### 4.2 让 Claude 进项目时拿到"业务底色"

omni 项目根放 `CLAUDE.md`：
- 静态区块：老板身份、工厂、品牌、关键关注指标、决策原则
- Dynamic 区块：当前主推 SKU、本周事件、库存告急——由 `refresh_project_context` tool 每周自动刷新

### 4.3 Observation（主动巡检）

Claude Code 不能 24/7 后台跑，omni 自己跑 cron worker。

#### 起步 4 个观察任务

| 名 | 频率 | 实现 | 推到哪 |
|---|---|---|---|
| `daily_store_pulse` | 每日 9:00 | omni cron + Sonnet（轻 agent-lite）| 企微 + /inbox |
| `stock_low_alert` | 每日 8:30 | omni cron（查阈值，无需 LLM）| 企微 + /inbox |
| `weekly_recording_insights` | 每周一 9:00 | omni cron + Sonnet（调 generate_recording_insights）| /inbox |
| `weekly_full_review` | 每周一 18:00 | **`claude -p "/skill weekly-review"` headless** | /inbox |

### 4.4 cron 调度

| 选项 | 说明 |
|---|---|
| **Windows Task Scheduler**（你电脑上）| 已有，0 引入；脚本：`python -m app.observation.daily_pulse` |
| APScheduler 备用 | 嵌入 knowledge-engine，处理 service 内部小循环 |

### 4.5 启动方式（推荐）

```
[开机]
   ↓
[omni 后端常驻]  ← 加到 Windows Startup 自启
   • dev-start.ps1 后端部分（knowledge-engine, ai-hub, scout-agent, postgres）
   • cron 巡检 worker 自动跑
   ↓
[随时打开 Claude Code 对话] ← 每次开都能直接用
```

操作：`Win+R` → `shell:startup` → 新建快捷方式指向 `powershell.exe -WindowStyle Hidden -File "E:\agent\omni\dev-start.ps1"`

---

## §5 Human Gate 详设

### 5.1 4 类签字 → 落到 require_approval 的 tool

| 签字类型 | 对应 tool |
|---|---|
| 出 Brief / 脚本 前 | `generate_brief` / `run_sku_orch` |
| 发动作到平台前 | `dy_publish_creative` / `kb_upload_doc` / `kb_set_role` / `send_wecom_message` |
| 算账 / 出数字 前 | `compute_margin` |
| 任何"多一步"动作 | `generate_image` / `generate_video` / `schedule_observation` / `codify_pattern_to_skill` / `refresh_project_context` |

### 5.2 完整流程

```
Claude Code 决定调 X(args)
   → omni MCP server 收到调用
   → audit 写 mcp.tool_calls (status=pending)
   → require_approval=True ?
       → 写 mcp.human_gates (含 summary)
       → push 通知（企微 + /inbox）
       → await 等批/驳/超时
           → approved → 真执行 → 返回结果
           → rejected → 返回 {ok:false, error:"rejected_by_user"}
           → timeout (默认 1h) → 算 reject
   → require_approval=False → 直接执行
```

### 5.3 `/inbox` 页 UI（手机友好）

两个 tab：
- **待审 tool 调用**（mcp.human_gates，未决定的）
- **观察通知**（mcp.observations，未 ack 的）

每条卡片：summary + 时间 + tool 名 + 参数概览 + [详情] [✅] [❌]。

### 5.4 超时机制

```yaml
human_gate:
  default_timeout_seconds: 3600          # 1h
  long_timeout_tools:
    - run_sku_orch: 14400                # 4h
    - generate_video: 7200               # 2h
  on_timeout: rejected
```

### 5.5 会话级 grant

**用户拍板：不启用**（每次签字最稳）。如果以后觉得繁琐再加。

### 5.6 黑名单

起步空（不预设黑名单）。后续按事故经验添加，配在 `.claude/settings.local.json` 的 `permissions.deny`。

---

## §6 错误处理 + 测试

### 6.1 错误处理三层

```
层 1: tool 内部
  不抛异常, return {ok:false, error, hint}

层 2: MCP server / audit 装饰器
  未捕获异常 → audit 写 status=error
  返回 {ok:false, error: 异常类名}

层 3: 跨服务（HTTP 调 ai-hub / scout-agent）
  timeout 设合理（5-120 秒按 tool 调）
  503 / connection refused → 友好 hint
```

### 6.2 必须有单测的 tool（5 个）

| tool | 测什么 |
|---|---|
| `compute_margin` | 算数对不对（金额、利率、breakdown）|
| `query_costs` | 时间窗 / 过滤 / 空数据 |
| `search_kb` | 命中 / 不命中 / kb_role 优先级 |
| `run_sku_orch` | 状态机 / 失败回退 |
| `human_gate` 流程 | 批/驳/超时 |

其他 tool 不强制单测（个人用，跑起来看真实数据更高效）。

### 6.3 调试三件套

#### 1. `/agent-log` 页
每个 tool 调用一行，按 tool/时间/状态筛选。点详情看完整 args + result + tokens + duration + rating。

#### 2. `omni-mcp-doctor` CLI
```bash
$ python -m app.mcp.doctor
[✓] knowledge-engine 8002 健康
[✓] ai-provider-hub 8001 健康
[✓] scout-agent 8009 健康
[✓] postgres infra-core 健康
[✓] mcp.tool_calls 表存在
[✓] tool_models.yaml 加载成功 (28 个 tool 配置)
[✓] /mcp 端点返回 28 个 tool schema
[!] gpt-image-2 未配 OPENAI_API_KEY    ← 提醒
```

#### 3. tool 调用 dry-run 模式
`require_approval=True` 的 tool 加 `dry_run` 参数。Claude 可以说"先模拟一下"。

### 6.4 回滚策略

不灰度（个人用）。某个 tool 出问题 → 在 `tool_models.yaml` 顶部加 `disabled_tools` 列表（启动时跳过该 tool 的注册，Claude Code 看不到 = 不会调）：

```yaml
# tool_models.yaml 顶部
disabled_tools:
  - generate_video
  - dy_publish_creative

__default__:
  ...
```

实现：`app/mcp/server.py` 启动时读 `disabled_tools` 列表，FastMCP 注册阶段跳过这些 tool。重启 knowledge-engine 生效。

---

## §7 进化机制

### 7.1 Agent 进化的 5 个层次

| 层 | 机制 | 谁驱动 | 落到哪 |
|---|---|---|---|
| ① 记忆被动累积 | Claude Code memory 自动学；KB 上传；decisions 入库 | 系统自动 | `~/.claude/.../memory/` + omni Postgres |
| ② Skill 迭代 | 改 markdown SOP；新加业务 SOP | 你 / Claude 协助 | `~/.claude/skills/` |
| ③ Tool 调优 | 改 tool description；改 yaml 换模型；加新 tool | 你 | yaml + 代码 |
| ④ 反思周报 | Claude 复盘 tool_calls + human_gates，提改进建议 | Claude（cron 触发或你触发）| `mcp.observations` 表 → /inbox |
| ⑤ 工具自衍 | Claude 发现高频组合 → 提议加新 tool；你点头它自己改 omni 代码 | Claude（Claude Code 本来就能改 omni 代码）| omni 代码 + git commit |

### 7.2 自动 SOP 总结流程（带草稿 + 审批）

```
[每周日 19:00 触发 agent_self_review]
   → 读 mcp.tool_calls 7 天历史
   → 发现 pattern: "用户 12 次问'X 产品咋样', 我都按 'get_sku → query_costs → 
                    fetch_compass_sku_detail → search_kb → 报告' 走"
   → 调 codify_pattern_to_skill (require_approval=True)
   → 写草稿到 ~/.claude/skills/_drafts/product-analysis/SKILL.md
   → /inbox 推一条审批：
       [✅ 采纳]   [❌ 驳回]   [✏️ 改了再用]
   → 用户决定:
       采纳 → 移到 /skills/
       驳回 → 删草稿（驳回原因记入 failed_patterns.md）
       改了 → IDE 打开 → 保存后移到 /skills/
```

### 7.3 5 层干预机制（防止 SOP 走偏）

| 层 | 时机 | 干预方式 |
|---|---|---|
| ① 事前·草稿模式 | SOP 生成前 | `codify_pattern_to_skill` 强制 require_approval=True |
| ② 事中·打断对话 | SOP 在用时 | 直接说"等等这条路不对，先停" |
| ③ 事后·改文件 | 用过一阵发现问题 | 跟 Claude 说"把 X skill 第 N 步改成 Y"，它改 markdown |
| ④ 版本化·git 回退 | 改坏了 | skill 文件全 git 跟踪 |
| ⑤ A/B 试用·灰度 | 不确定值不值 | skill frontmatter 标 `status: experimental`，1 周后看 mcp.tool_calls 数据再决定 |

### 7.4 反馈循环（替代 RL）

不引入真 RL（数据/算力/工程不匹配个人用）。引入轻量反馈机制：

#### Outcome Tracking
- `mcp.tool_calls` 加 `user_rating` 字段（good/bad/redo/null）
- `/agent-log` 每条加 👍 👎 ↻ 三按钮
- 复盘时 `agent_self_review` 看 rating 分布

#### Pattern Library
- `~/.claude/projects/.../memory/successful_patterns.md` 自动累积成功 case
- `~/.claude/projects/.../memory/failed_patterns.md` 自动累积失败 case
- Claude 面对相似问题前自动读这两个文件（Claude Code memory 机制原生支持）

#### Bandit（暂不加）
仅在某 tool 有多个候选模型时考虑。**起步不开**，6 个月观察后按需加。

### 7.5 进化机制改动量

| 项 | 行数 |
|---|---|
| `agent_self_review` tool | ~80 |
| `codify_pattern_to_skill` tool（含 _drafts/ 目录支持）| ~80 |
| `weekly_self_review` 观察任务 | ~30 |
| `/inbox` 加 SOP 草稿卡片（3 按钮）| ~120 行 TSX |
| `mcp.tool_calls.user_rating` 字段 + UI 评分按钮 | ~80 行 |
| 自动写 successful/failed patterns.md hook | ~50 行 |
| skill 状态字段（frontmatter `status: stable/experimental/deprecated`）| 0（仅约定）|

总进化机制：~440 行（落在 W4）。

### 7.6 永远是用户拍板（核心约束）

| 行为 | 是否需要用户点头 |
|---|---|
| Claude 改 omni 代码 | ✅ git diff + 用户确认才 commit |
| Claude 写新 skill 草稿 | ✅ require_approval（推 /inbox）|
| Claude 改正在生效的 skill | ✅ require_approval |
| Claude 删 skill | ✅ require_approval |
| Claude 改 yaml | ✅ require_approval |
| Claude 调 search_kb / list_skus 等纯查询 | ❌ 自由 |

---

## §8 数据库变更总表

3 张新表，全部在 `mcp` schema：

```sql
-- migrations/016_mcp_audit.sql
CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE mcp.tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name TEXT NOT NULL,
    args JSONB NOT NULL,
    result JSONB,
    status TEXT NOT NULL,            -- pending|approved|rejected|completed|error
    require_approval BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms INT,
    error TEXT,
    user_rating TEXT,                 -- good|bad|redo|null
    rating_note TEXT,
    model_used TEXT,                  -- 实际用的 provider/model
    tokens_input INT,
    tokens_output INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX ON mcp.tool_calls (tool_name, created_at DESC);
CREATE INDEX ON mcp.tool_calls (status) WHERE status='pending';
CREATE INDEX ON mcp.tool_calls (user_rating) WHERE user_rating IS NOT NULL;

CREATE TABLE mcp.human_gates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_call_id UUID REFERENCES mcp.tool_calls(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    decision TEXT,                    -- approved|rejected
    decision_note TEXT,
    decided_at TIMESTAMPTZ,
    timeout_seconds INT NOT NULL DEFAULT 3600,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON mcp.human_gates (decision) WHERE decision IS NULL;

-- migrations/017_observations.sql
CREATE TABLE mcp.observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,               -- daily_pulse|stock_alert|weekly_review|self_review
    severity TEXT NOT NULL,           -- info|warn|urgent
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    details JSONB,
    pushed_to TEXT,                   -- wecom|inbox|both
    acked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON mcp.observations (kind, created_at DESC);
CREATE INDEX ON mcp.observations (acked_at) WHERE acked_at IS NULL;

-- migrations/018_cost_items.sql（W2 用到，KB Role 阶段二的工作）
CREATE TABLE IF NOT EXISTS cost_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku_id TEXT,                            -- 可选：关联到 mvp_sku，NULL 表示通用成本
    category TEXT NOT NULL,                 -- product | logistics | partner_quote | other
    item_name TEXT NOT NULL,                -- "原料-酱油基底"、"快递包装"等
    unit_cost NUMERIC(12, 4) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    vendor TEXT,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to DATE,                          -- NULL = 当前有效
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON cost_items (sku_id) WHERE sku_id IS NOT NULL;
CREATE INDEX ON cost_items (category, valid_from);
CREATE INDEX ON cost_items (valid_to) WHERE valid_to IS NULL;
```

跟 `project_kb_role_upgrade.md` 阶段二 2.1 节一致，提前在 W2 落地。

---

## §9 验收标准（按周）

### W1 闭环周
- [ ] Claude Code `/mcp` 命令显示 `omni` 已连接
- [ ] 5 个 tool schema 全部可见
- [ ] 测试对话："我有几个 SKU" → Claude 调 list_skus → 返回正确数量
- [ ] 测试对话："查 X 在 KB 里" → Claude 调 search_kb → 返回相关 chunks
- [ ] mcp.tool_calls 表每次调用记一行
- [ ] omni-mcp-doctor 全绿

### W2 算账 + 编排 + 媒体
- [ ] /cost 页能录入/编辑/筛选成本项
- [ ] 测试对话："算 SKU-001 售价 38 净利率" → 触发 human gate → 你批 → 返回数字
- [ ] 测试对话："让 X 产品跑一次编排" → 触发 human gate → 你批 → 创建 orch
- [ ] 测试对话："给 SKU-001 生一个产品图" → gpt-image-2 → 返回 URL
- [ ] 测试对话："给 SKU-001 生一个 5 秒视频，参考图 ..." → Seedance 2.0 → 返回 URL

### W3 专家模型 + 跨服务
- [ ] 测试对话："今天罗盘有啥异动" → fetch_compass_store_daily → 返回 anomalies
- [ ] 测试对话："上周录音聊了啥" → generate_recording_insights → 返回主题聚类
- [ ] 测试对话："这个 200 页 PDF 总结一下" → parse_long_doc_with_gemini → 返回结构化
- [ ] 测试对话："找抖音风格的 6 秒钩子素材" → query_template_chunks → 返回带标签 chunks

### W4 前端 + skill + 进化机制
- [ ] /inbox 页 PC + 手机能用，点 ✅/❌ 工作
- [ ] /agent-log 页能筛选/搜索/查看详情
- [ ] 6 个业务 skill 写在 ~/.claude/skills/，能在 Claude Code 用 `/skill <name>` 触发
- [ ] 点 👍/👎 后 user_rating 入库，successful/failed_patterns.md 被写入
- [ ] 周日 19:00 自动跑 agent_self_review，/inbox 收到反思周报
- [ ] CLAUDE.md 项目根存在，dynamic 区块每周一刷新

### 整体（4 周末）
- [ ] 月成本 ≤ $100
- [ ] cron 巡检 4 个任务正常运行
- [ ] 一个真实场景跑通：手机收企微告警 → 上电脑跟 Claude 多轮讨论 → 调多个 tool → 出 brief → 生图/视频 → 入决策日志
- [ ] 文档：README.md 描述如何启动 / 注册 Claude Code / 配 yaml / 加新 tool

---

## §10 依赖与风险

| 风险 | 缓解 |
|---|---|
| FastMCP 与 FastAPI 兼容性 | W1 头一天先验证（30 分钟搞定）|
| Claude Code Windows 上 MCP HTTP 配置 | 已知可行，备选 stdio 也支持 |
| 编排 tool 跑很久 | 拆成 `start_orch` + `get_status` 两 tool，agent 轮询 |
| Human Gate 等批超时 | timeout=1h，超时算 reject，记审计 |
| scout-agent 现有 endpoint 不全部对齐 | W3 第一天先盘点缺口，缺啥补啥 |
| Claude Code Max 订阅政策变动 | 备用：开 Anthropic API key（按 token 付）|
| Pattern Library 累积过大 | 6 个月后压缩 / 归档老 case |

---

## §11 后续展望（不在本期 4 周内）

- Bandit 多臂老虎机（仅在某 tool 有多模型候选时）
- 接更多第三方 MCP server（飞书 / Notion / GitHub / Slack）
- 录音 ASR（用户当前是手动转写，未来可加自动）
- 主动观察任务 UI 编辑（让用户在网页上配 cron + prompt）
- 跨设备同步（个人用，单机够；如要跨设备，Postgres 上云）

---

## 附录 A：术语对照表

| 术语 | 定义 |
|---|---|
| Agent | LLM 推理 + 工具调用 + 循环执行 + 记忆的整体系统 |
| Tool | 暴露给 LLM 的函数（JSON schema），LLM 可在对话中调用 |
| Skill | Claude Code 的 markdown 文档 + 可选脚本，描述 SOP / 行为指引 |
| MCP | Model Context Protocol，Anthropic 出的 agent-tool 通信协议 |
| FastMCP | Python MCP server 库 |
| Human Gate | require_approval=True 的 tool 在执行前等用户批准的机制 |
| ICL | In-Context Learning，Claude 看上下文（历史/记忆）现学的能力 |
| Pattern Library | successful/failed_patterns.md，case 库供 Claude 参考 |

---

## 附录 B：相关 memory 文件

| 文件 | 内容 |
|---|---|
| `~/.claude/projects/E--agent-omni/memory/MEMORY.md` | memory 索引 |
| `feedback_personal_use_no_overengineering.md` | 个人自用约束 |
| `feedback_model_selection.md` | 模型选择策略 |
| `feedback_collaboration_style.md` | 合作风格 |
| `project_kb_role_upgrade.md` | KB Role 阶段一/二/三 |
| `project_omni_pathA_pathB.md` | 路径 A/B 现状 |
| `reference_omni_assets.md` | 项目资产路径 |

---

**文档结束。等待用户审批后进入 implementation plan。**
