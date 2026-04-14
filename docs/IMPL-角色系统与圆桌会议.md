# 技术实现文档 — 角色系统与圆桌会议（Persona & Roundtable）

> 模块代号：SP9-Persona  
> 版本：v1.0  
> 日期：2026-04-07

---

## 1. 系统架构

### 1.1 方案选型

**不新增后端服务**，在现有前端 + Knowledge Engine + AI Provider Hub 上扩展。

理由：
- 角色配置是纯前端数据（MVP 阶段存 localStorage），无需独立后端
- 圆桌会议本质是多次 RAG 调用的编排，复用现有 Knowledge Engine 的 `/api/v1/knowledge/rag` 接口
- Tri-Mind 的 debate-controller 架构可直接改造为 roundtable-controller
- 不引入新的基础设施依赖

### 1.2 架构图

```
┌──────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Chat Page (/app/chat/page.tsx)                     │   │
│  │  ├── PersonaSelector（角色选择器）                    │   │
│  │  ├── ModeTab（单人问答 / 圆桌会议 tab）              │   │
│  │  ├── RoundtableConfig（圆桌配置面板）                 │   │
│  │  ├── RoundtableView（讨论过程展示）                   │   │
│  │  └── PersonaManager（角色管理弹窗）                   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Stores                                              │   │
│  │  ├── personaStore.ts（角色状态 + localStorage 持久化）│   │
│  │  ├── chatStore.ts（扩展：persona 字段）              │   │
│  │  └── roundtableStore.ts（圆桌会议状态）              │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Server (改造 tri-mind → roundtable)                 │   │
│  │  └── /server/roundtable/                              │   │
│  │       ├── roundtable-controller.ts（核心编排控制器）  │   │
│  │       ├── prompt-factory.ts（角色prompt + 圆桌prompt）│   │
│  │       └── types.ts（圆桌类型定义）                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                         │                                    │
│  ┌──────────────────────┴───────────────────────────────┐   │
│  │  API Routes                                          │   │
│  │  ├── /api/omni/knowledge/rag  （现有，透传 persona） │   │
│  │  └── /api/omni/roundtable     （新增，圆桌会议 SSE） │   │
│  └──────────────────────────────────────────────────────┘   │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │ HTTP
              ┌───────────┼───────────────┐
              │           │               │
     ┌────────▼───┐ ┌────▼──────┐        │
     │ AI Provider │ │ Knowledge │        │
     │ Hub :8001   │ │ Engine    │        │
     │             │ │ :8002     │        │
     │ - 纯角色问答│ │ - RAG问答  │        │
     │   (无知识库) │ │ - persona │        │
     │             │ │   prompt  │        │
     └─────────────┘ │   注入    │        │
                      └───────────┘        │
```

### 1.3 改动范围

| 层级 | 文件 | 改动类型 | 说明 |
|------|------|---------|------|
| 前端 Store | `stores/personaStore.ts` | 新增 | 角色状态管理 |
| 前端 Store | `stores/chatStore.ts` | 修改 | 新增 persona 字段 |
| 前端 Store | `stores/roundtableStore.ts` | 新增 | 圆桌会议状态管理 |
| 前端页面 | `app/chat/page.tsx` | 修改 | 新增 tab、角色选择器、圆桌UI |
| 前端组件 | `components/persona-selector.tsx` | 新增 | 角色选择器组件 |
| 前端组件 | `components/persona-manager.tsx` | 新增 | 角色管理弹窗 |
| 前端组件 | `components/roundtable-view.tsx` | 新增 | 圆桌讨论展示组件 |
| 前端Server | `server/roundtable/` | 新增（替代 tri-mind） | 圆桌控制器 |
| 前端API | `app/api/omni/roundtable/route.ts` | 新增 | 圆桌会议 SSE 接口 |
| 前端API | `app/api/omni/knowledge/rag/route.ts` | 修改 | 透传 persona 字段 |
| 后端 | `knowledge-engine/app/schemas.py` | 修改 | RAGRequest 新增 persona 字段 |
| 后端 | `knowledge-engine/app/services/rag_chain.py` | 修改 | system prompt 注入 persona |

---

## 2. 数据结构设计

### 2.1 角色数据模型（前端 TypeScript）

```typescript
// stores/personaStore.ts

export interface Persona {
  id: string                    // 预设角色用固定ID，自建角色用 uuid
  name: string                  // 角色名称
  icon: string                  // emoji 图标
  description: string           // 角色描述（一行）
  systemPrompt: string          // System Prompt 全文
  exampleQueries: string[]      // 示例问题列表
  isPreset: boolean             // 是否预设角色（预设不可删除）
  createdAt: number             // 创建时间戳
  updatedAt: number             // 修改时间戳
}

export interface PersonaState {
  personas: Persona[]           // 所有角色（预设 + 自建）
  selectedPersonaId: string | null  // 当前选中角色ID

  // Actions
  selectPersona: (id: string | null) => void
  createPersona: (data: Omit<Persona, 'id' | 'isPreset' | 'createdAt' | 'updatedAt'>) => void
  updatePersona: (id: string, data: Partial<Persona>) => void
  deletePersona: (id: string) => void  // 仅允许删除自建角色
  resetPresetPrompt: (id: string) => void  // 重置预设角色prompt为默认
  getSelectedPersona: () => Persona | null
}
```

### 2.2 圆桌会议数据模型

```typescript
// stores/roundtableStore.ts

export type ModeratorType = 'default' | 'boss'

export interface RoundtableSpeech {
  id: string
  personaId: string
  personaName: string
  personaIcon: string
  round: number
  content: string
  sources?: SourceRef[]         // RAG 检索到的引用来源
  loading: boolean
  timestamp: number
}

export interface RoundtableIntervention {
  id: string
  content: string
  targetPersonaId: string | null  // null = 全员回应, 有值 = @指定角色
  afterRound: number              // 在第几轮之后插话
  timestamp: number
}

export interface RoundtableSummary {
  content: string
  moderatorType: ModeratorType
  loading: boolean
  timestamp: number
}

export interface RoundtableSession {
  id: string
  topic: string                    // 议题
  participantIds: string[]         // 参会角色ID列表（2-5个）
  moderatorType: ModeratorType
  totalRounds: number              // 配置的总轮数（3-5）
  currentRound: number             // 当前进行到第几轮
  kbIds: string[]                  // 选中的知识库
  model: string | null             // 使用的模型
  provider: string | null          // 使用的提供者

  speeches: RoundtableSpeech[]
  interventions: RoundtableIntervention[]
  summary: RoundtableSummary | null

  status: 'configuring' | 'discussing' | 'intervening' | 'summarizing' | 'completed'
  createdAt: number
}

export interface RoundtableState {
  session: RoundtableSession | null
  abortController: AbortController | null

  // Actions
  createSession: (config: {
    topic: string
    participantIds: string[]
    moderatorType: ModeratorType
    totalRounds: number
    kbIds: string[]
    model?: string
    provider?: string
  }) => void
  appendSpeechToken: (speechId: string, token: string) => void
  finishSpeech: (speechId: string, sources?: SourceRef[]) => void
  addIntervention: (content: string, targetPersonaId: string | null) => void
  setSummary: (content: string) => void
  appendSummaryToken: (token: string) => void
  setStatus: (status: RoundtableSession['status']) => void
  abort: () => void
  reset: () => void
}
```

### 2.3 后端 RAGRequest 扩展

```python
# services/knowledge-engine/app/schemas.py

class RAGRequest(BaseModel):
    kb_id: str = ""
    kb_ids: list[str] | None = None
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    model: str | None = None
    provider: str | None = None
    stream: bool = False
    session_id: str | None = None
    target_chars: int | None = Field(default=None, ge=0, le=500_000)
    continue_max_rounds: int | None = Field(default=None, ge=1, le=100)

    # ═══ SP9 新增 ═══
    persona_prompt: str | None = None   # 角色 system prompt，注入到 RAG prompt 前
```

---

## 3. 核心实现

### 3.1 角色 Store — `personaStore.ts`

```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { v4 as uuidv4 } from 'uuid'
import type { Persona, PersonaState } from './types'
import { PRESET_PERSONAS } from './preset-personas'

export const usePersonaStore = create<PersonaState>()(
  persist(
    (set, get) => ({
      personas: [...PRESET_PERSONAS],
      selectedPersonaId: null,

      selectPersona: (id) => set({ selectedPersonaId: id }),

      createPersona: (data) => {
        const newPersona: Persona = {
          ...data,
          id: uuidv4(),
          isPreset: false,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        }
        set((state) => ({
          personas: [...state.personas, newPersona],
        }))
      },

      updatePersona: (id, data) => {
        set((state) => ({
          personas: state.personas.map((p) =>
            p.id === id ? { ...p, ...data, updatedAt: Date.now() } : p
          ),
        }))
      },

      deletePersona: (id) => {
        const persona = get().personas.find((p) => p.id === id)
        if (persona?.isPreset) return // 预设角色不可删除
        set((state) => ({
          personas: state.personas.filter((p) => p.id !== id),
          selectedPersonaId:
            state.selectedPersonaId === id ? null : state.selectedPersonaId,
        }))
      },

      resetPresetPrompt: (id) => {
        const preset = PRESET_PERSONAS.find((p) => p.id === id)
        if (!preset) return
        set((state) => ({
          personas: state.personas.map((p) =>
            p.id === id ? { ...p, systemPrompt: preset.systemPrompt, updatedAt: Date.now() } : p
          ),
        }))
      },

      getSelectedPersona: () => {
        const { personas, selectedPersonaId } = get()
        return personas.find((p) => p.id === selectedPersonaId) ?? null
      },
    }),
    {
      name: 'omni-persona-store',
      version: 1,
    }
  )
)
```

### 3.2 预设角色定义 — `preset-personas.ts`

```typescript
import type { Persona } from './types'

export const PRESET_PERSONAS: Persona[] = [
  {
    id: 'ecom_ops',
    name: '电商运营',
    icon: '🏪',
    description: '京东/天猫/淘宝平台策略与执行',
    systemPrompt: `你是一位资深电商运营专家，精通京东、天猫、淘宝三大平台的运营规则和策略。
你的回答必须遵循以下原则：
1. 平台规则优先：所有建议必须符合当前平台规则，提及规则变动时标注时效性
2. 可执行性：给出具体的操作步骤，而非笼统建议
3. 数据驱动：建议中尽量包含行业基准数据（如品类平均CTR、转化率）
4. 竞品意识：分析时考虑竞品动态和类目竞争格局
5. 活动节奏：建议要考虑平台大促节点和日常运营的节奏差异
6. 涵盖范围：listing优化、搜索排名、活动报名、店铺诊断、客服管理、售后处理`,
    exampleQueries: [
      '这个品双11应该怎么定价策略？',
      '天猫搜索权重最近有什么变化？',
      '帮我分析下竞品A的listing优化方向',
    ],
    isPreset: true,
    createdAt: 0,
    updatedAt: 0,
  },
  // ... 其余 8 个预设角色（结构相同，prompt 内容见 PRD）
]
```

### 3.3 RAG System Prompt 注入 — `rag_chain.py` 改动

```python
# services/knowledge-engine/app/services/rag_chain.py
# 修改 generate 节点中的 system prompt 构造逻辑

def _build_system_prompt(
    context: str,
    graph_context: str,
    persona_prompt: str | None = None,
    crag_note: str = "",
) -> str:
    """构造最终的 system prompt，支持角色 prompt 注入。"""

    rag_prompt = RAG_SYSTEM_PROMPT.format(
        context=context,
        graph_context=graph_context,
    )

    if crag_note:
        rag_prompt += "\n" + crag_note

    if persona_prompt:
        return (
            f"{persona_prompt}\n\n"
            f"---\n\n"
            f"以下是你在回答时需要参考的资料和规则：\n\n"
            f"{rag_prompt}"
        )

    return rag_prompt
```

在 `generate` 节点中调用：

```python
async def _generate(state: RAGState) -> dict:
    # ... 现有的 context 和 graph_context 组装逻辑 ...

    system_prompt = _build_system_prompt(
        context=context_str,
        graph_context=graph_context_str,
        persona_prompt=state.get("persona_prompt"),
        crag_note=crag_note,
    )

    # ... 后续 LLM 调用逻辑不变 ...
```

RAGState 新增字段：

```python
class RAGState(TypedDict, total=False):
    # ... 现有字段 ...
    persona_prompt: str | None  # SP9: 角色 system prompt
```

### 3.4 前端 RAG 请求透传 persona — `route.ts` 改动

```typescript
// frontend/src/app/api/omni/knowledge/rag/route.ts
// 在构造发送给 knowledge-engine 的请求体时，新增 persona_prompt 字段

const payload = {
  kb_id: body.kb_id || '',
  kb_ids: body.kb_ids || [],
  query: body.query,
  top_k: body.top_k ?? 10,
  model: body.model,
  provider: body.provider,
  stream: true,
  session_id: body.session_id,
  // SP9 新增
  persona_prompt: body.persona_prompt || null,
}
```

### 3.5 圆桌控制器 — `roundtable-controller.ts`

```typescript
// frontend/src/server/roundtable/roundtable-controller.ts

import { v4 as uuidv4 } from 'uuid'
import type { Persona } from '@/stores/personaStore'

export interface RoundtableParams {
  topic: string
  participants: Persona[]
  moderatorType: 'default' | 'boss'
  totalRounds: number
  kbIds: string[]
  model?: string
  provider?: string
}

export interface RoundtableStreamEvent {
  type: 'speech-start' | 'speech-token' | 'speech-done'
       | 'round-complete' | 'intervention-prompt'
       | 'summary-start' | 'summary-token' | 'summary-done'
       | 'error'
  personaId?: string
  personaName?: string
  personaIcon?: string
  round?: number
  content?: string
  sources?: any[]
  error?: string
}

export class RoundtableController {
  private abortController: AbortController | null = null
  private roundHistory: Map<number, Map<string, string>> = new Map()
  private interventions: Array<{ content: string; targetPersonaId: string | null }> = []

  /**
   * 执行一轮讨论
   * 同一轮内所有角色并发调用 RAG，各自独立发言
   */
  async runRound(
    params: RoundtableParams,
    round: number,
    onEvent: (event: RoundtableStreamEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const roundResponses = new Map<string, string>()

    // 构造每个角色的 prompt
    const tasks = params.participants.map(async (persona) => {
      onEvent({
        type: 'speech-start',
        personaId: persona.id,
        personaName: persona.name,
        personaIcon: persona.icon,
        round,
      })

      const query = this.buildPersonaQuery(params.topic, persona, round)
      let fullContent = ''

      try {
        // 调用 RAG 接口（流式）
        const response = await fetch('/api/omni/knowledge/rag', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            kb_ids: params.kbIds,
            query,
            model: params.model,
            provider: params.provider,
            stream: true,
            session_id: `roundtable-${persona.id}-${round}`,
            persona_prompt: persona.systemPrompt,
          }),
          signal,
        })

        // 处理 SSE 流
        const reader = response.body?.getReader()
        const decoder = new TextDecoder()

        if (reader) {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            const text = decoder.decode(value)
            // 解析 SSE 事件，提取 token
            const tokens = this.parseSSETokens(text)
            for (const token of tokens) {
              fullContent += token
              onEvent({
                type: 'speech-token',
                personaId: persona.id,
                content: token,
                round,
              })
            }
          }
        }

        roundResponses.set(persona.id, fullContent)

        onEvent({
          type: 'speech-done',
          personaId: persona.id,
          personaName: persona.name,
          round,
          content: fullContent,
        })
      } catch (err: any) {
        if (err.name !== 'AbortError') {
          onEvent({
            type: 'error',
            personaId: persona.id,
            error: err.message,
          })
        }
      }
    })

    // 并发执行所有角色发言
    await Promise.all(tasks)

    this.roundHistory.set(round, roundResponses)

    onEvent({ type: 'round-complete', round })
  }

  /**
   * 构造单个角色的查询文本
   */
  private buildPersonaQuery(
    topic: string,
    persona: Persona,
    round: number,
  ): string {
    let query = ''

    if (round === 1) {
      query = `你正在参加一场多角色圆桌会议。\n\n议题：${topic}\n\n请从你的专业角度分析这个议题，给出你的核心观点、关键数据/依据、以及具体建议。`
    } else {
      // 拼接上一轮所有角色的发言
      const prevRound = this.roundHistory.get(round - 1)
      let prevSpeechesText = ''
      if (prevRound) {
        for (const [pid, content] of prevRound) {
          // 通过 personaId 查找名字（需要外部传入映射）
          prevSpeechesText += `【${pid}】\n${content}\n\n`
        }
      }

      query = `你正在参加一场多角色圆桌会议。以下是其他参会者上一轮的发言。\n\n` +
        `请结合你的专业视角：\n` +
        `1. 审视其他角色的观点，指出可能存在的盲区或风险\n` +
        `2. 补充你的专业领域中其他角色可能忽略的要点\n` +
        `3. 如果你认同某个观点，明确表示并说明原因\n\n` +
        `---其他参会者上轮发言---\n${prevSpeechesText}\n` +
        `---议题---\n${topic}`

      // 注入用户插话（如有）
      const interventionForThisRound = this.interventions.find(
        (i) => i.targetPersonaId === null || i.targetPersonaId === persona.id
      )
      if (interventionForThisRound) {
        query += `\n\n---用户追问---\n${interventionForThisRound.content}`
      }
    }

    return query
  }

  /**
   * 添加用户插话
   */
  addIntervention(content: string, targetPersonaId: string | null): void {
    this.interventions.push({ content, targetPersonaId })
  }

  /**
   * 生成主持人总结
   */
  async runSummary(
    params: RoundtableParams,
    onEvent: (event: RoundtableStreamEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    onEvent({ type: 'summary-start' })

    // 汇总所有轮次的发言
    let allSpeechesText = ''
    for (const [round, responses] of this.roundHistory) {
      allSpeechesText += `--- 第 ${round} 轮 ---\n\n`
      for (const [personaId, content] of responses) {
        allSpeechesText += `【${personaId}】\n${content}\n\n`
      }
    }

    // 加入用户插话记录
    if (this.interventions.length > 0) {
      allSpeechesText += `--- 用户插话记录 ---\n\n`
      for (const intervention of this.interventions) {
        const target = intervention.targetPersonaId
          ? `@${intervention.targetPersonaId}`
          : '全员'
        allSpeechesText += `[${target}] ${intervention.content}\n\n`
      }
    }

    const moderatorPrompt = params.moderatorType === 'boss'
      ? BOSS_MODERATOR_PROMPT
      : DEFAULT_MODERATOR_PROMPT

    const query = `以下是一场多角色圆桌会议的完整讨论记录。\n\n` +
      `议题：${params.topic}\n` +
      `参会角色：${params.participants.map(p => p.name).join('、')}\n` +
      `讨论轮数：${this.roundHistory.size}轮\n\n` +
      `${allSpeechesText}\n\n` +
      `请根据以上讨论内容，生成结构化的总结报告。`

    try {
      // 走 AI Provider Hub 直接 chat（主持人总结不走 RAG）
      const response = await fetch('/api/omni/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [
            { role: 'system', content: moderatorPrompt },
            { role: 'user', content: query },
          ],
          model: params.model,
          provider: params.provider,
          stream: true,
        }),
        signal,
      })

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (reader) {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          const text = decoder.decode(value)
          const tokens = this.parseSSETokens(text)
          for (const token of tokens) {
            onEvent({ type: 'summary-token', content: token })
          }
        }
      }

      onEvent({ type: 'summary-done' })
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', error: err.message })
      }
    }
  }

  /**
   * 解析 SSE 文本中的 token
   */
  private parseSSETokens(text: string): string[] {
    const tokens: string[] = []
    const lines = text.split('\n')
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6)
        if (data === '[DONE]') continue
        try {
          const parsed = JSON.parse(data)
          if (parsed.token) tokens.push(parsed.token)
          if (parsed.choices?.[0]?.delta?.content) {
            tokens.push(parsed.choices[0].delta.content)
          }
        } catch {
          // 非 JSON 数据，可能是纯文本 token
          if (data.trim()) tokens.push(data)
        }
      }
    }
    return tokens
  }

  /**
   * 中止讨论
   */
  abort(): void {
    this.abortController?.abort()
  }

  /**
   * 重置状态
   */
  reset(): void {
    this.roundHistory.clear()
    this.interventions = []
    this.abortController = null
  }
}

// 主持人 Prompt 常量
const DEFAULT_MODERATOR_PROMPT = `你是一场多角色圆桌会议的主持人，需要将所有参会者的多轮讨论整合为一份结构化决策报告。

请严格按照以下结构输出：

## 一、议题概述
简要说明讨论的核心问题和背景。

## 二、各方核心观点
按角色逐一列出其核心观点和关键依据（标注角色名）。

## 三、共识点
各角色一致认同的结论，说明达成共识的理由。

## 四、分歧点
存在不同意见的地方，列出各方理由和依据。

## 五、风险清单
综合各角色提到的风险，按严重程度排序。

## 六、决策建议
给出明确的决策建议（做/不做/有条件做），附带判断依据。

## 七、行动项
具体的下一步行动，标注建议负责角色和优先级。

要求：客观中立，引用发言时标注来源角色和轮次，对不确定的结论明确标注。`

const BOSS_MODERATOR_PROMPT = `你是公司CEO，刚听完一场多角色圆桌讨论。请以老板决策者的视角整合所有信息，输出决策报告。

请严格按照以下结构输出：

## 一、议题概述
一句话概括：这件事值不值得做。

## 二、各方核心观点
每个角色说了什么，哪些有价值，哪些是废话。

## 三、共识点
团队一致认同的结论，可以直接拍板的部分。

## 四、分歧点
有争议的地方，我的判断倾向哪一方，为什么。

## 五、风险清单
最可能出问题的地方，最坏情况会亏多少。

## 六、决策建议
我的最终决定（做/不做/先试再说），附带止损线。

## 七、行动项
谁来做、什么时候交付、怎么验收。

要求：用老板的口吻，简洁直接，关注利润、人效、现金流，每个行动项要有明确的判断标准。`
```

### 3.6 圆桌会议 API Route — `route.ts`

```typescript
// frontend/src/app/api/omni/roundtable/route.ts

import { NextRequest } from 'next/server'
import { RoundtableController } from '@/server/roundtable/roundtable-controller'

export async function POST(req: NextRequest) {
  const body = await req.json()
  const {
    topic,
    participants,     // Persona[]
    moderatorType,
    totalRounds,
    kbIds,
    model,
    provider,
    intervention,     // 可选：{ content: string, targetPersonaId: string | null }
    currentRound,     // 当前要执行的轮次
    action,           // 'run-round' | 'run-summary' | 'add-intervention'
    roundHistory,     // 前端传入已有的轮次记录（用于恢复状态）
  } = body

  const encoder = new TextEncoder()
  const controller = new RoundtableController()

  // 恢复轮次历史（如果有）
  if (roundHistory) {
    controller.restoreHistory(roundHistory)
  }

  const stream = new ReadableStream({
    async start(streamController) {
      const sendEvent = (event: any) => {
        const data = `data: ${JSON.stringify(event)}\n\n`
        streamController.enqueue(encoder.encode(data))
      }

      try {
        if (action === 'add-intervention' && intervention) {
          controller.addIntervention(intervention.content, intervention.targetPersonaId)
          sendEvent({ type: 'intervention-added' })
        }

        if (action === 'run-round') {
          await controller.runRound(
            { topic, participants, moderatorType, totalRounds, kbIds, model, provider },
            currentRound,
            sendEvent,
            req.signal,
          )
        }

        if (action === 'run-summary') {
          await controller.runSummary(
            { topic, participants, moderatorType, totalRounds, kbIds, model, provider },
            sendEvent,
            req.signal,
          )
        }

        streamController.enqueue(encoder.encode('data: [DONE]\n\n'))
      } catch (err: any) {
        sendEvent({ type: 'error', error: err.message })
      } finally {
        streamController.close()
      }
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  })
}
```

### 3.7 PDF 导出 — 浏览器端实现

```typescript
// 在 roundtable-view.tsx 中使用 html2pdf.js

async function exportToPDF(session: RoundtableSession, summaryHtml: string) {
  const html2pdf = (await import('html2pdf.js')).default

  const container = document.createElement('div')
  container.innerHTML = `
    <div style="font-family: 'Microsoft YaHei', sans-serif; padding: 40px;">
      <h1 style="text-align: center; border-bottom: 2px solid #333; padding-bottom: 16px;">
        圆桌会议报告
      </h1>
      <table style="width: 100%; margin: 20px 0; border-collapse: collapse;">
        <tr><td style="padding: 8px; font-weight: bold;">议题</td><td style="padding: 8px;">${session.topic}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">日期</td><td style="padding: 8px;">${new Date(session.createdAt).toLocaleDateString('zh-CN')}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">参会角色</td><td style="padding: 8px;">${session.participantIds.join('、')}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">讨论轮数</td><td style="padding: 8px;">${session.totalRounds}轮</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">主持人</td><td style="padding: 8px;">${session.moderatorType === 'boss' ? '老板视角' : '默认主持人'}</td></tr>
      </table>
      <hr/>
      ${summaryHtml}
    </div>
  `

  const topicShort = session.topic.slice(0, 20)
  const date = new Date().toISOString().slice(0, 10)
  const filename = `圆桌会议_${topicShort}_${date}.pdf`

  await html2pdf()
    .set({
      margin: [15, 15, 15, 15],
      filename,
      html2canvas: { scale: 2, useCORS: true },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
    })
    .from(container)
    .save()
}
```

---

## 4. 前端组件设计

### 4.1 新增组件清单

```
frontend/src/
├── components/
│   ├── persona-selector.tsx       # 角色下拉选择器（含管理入口）
│   ├── persona-manager.tsx        # 角色管理弹窗（编辑/创建/删除）
│   ├── persona-editor.tsx         # 单个角色编辑表单
│   └── roundtable-view.tsx        # 圆桌会议完整视图
│       ├── 配置面板（角色勾选、轮数、主持人）
│       ├── 讨论过程（分轮展示、流式发言）
│       ├── 插话输入框（支持@角色）
│       └── 主持人总结 + 导出按钮
├── stores/
│   ├── personaStore.ts            # 角色状态（含 localStorage 持久化）
│   ├── roundtableStore.ts         # 圆桌会议状态
│   └── preset-personas.ts        # 9 个预设角色定义
└── server/
    └── roundtable/
        ├── roundtable-controller.ts  # 圆桌讨论编排核心
        ├── prompt-factory.ts         # prompt 构造
        └── types.ts                  # 类型定义
```

### 4.2 Chat 页面改造 — `page.tsx`

关键改动点：

```typescript
// 1. 新增 tab 状态
type ChatMode = 'single' | 'roundtable'
const [chatMode, setChatMode] = useState<ChatMode>('single')

// 2. 引入 persona store
const { selectedPersonaId, getSelectedPersona } = usePersonaStore()

// 3. 发送 RAG 请求时注入 persona prompt
async function streamRAG(...) {
  const persona = getSelectedPersona()
  const payload = {
    // ... 现有字段 ...
    persona_prompt: persona?.systemPrompt || null,
  }
  // ... 现有 SSE 逻辑 ...
}

// 4. 渲染 tab 切换
<div className="flex gap-2 mb-4">
  <Button
    variant={chatMode === 'single' ? 'default' : 'outline'}
    onClick={() => setChatMode('single')}
  >
    💬 单人问答
  </Button>
  <Button
    variant={chatMode === 'roundtable' ? 'default' : 'outline'}
    onClick={() => setChatMode('roundtable')}
  >
    🪑 圆桌会议
  </Button>
</div>

// 5. 根据模式渲染不同内容
{chatMode === 'single' ? (
  <>
    <PersonaSelector />
    {/* 现有聊天界面 */}
  </>
) : (
  <RoundtableView />
)}
```

### 4.3 Tri-Mind 迁移策略

1. **保留底层代码**：`/server/tri-mind/` 目录保留但不再引入
2. **移除入口**：删除前端页面中所有 Tri-Mind 的入口链接和 tab
3. **复用适配器**：如果圆桌需要支持多模型（后续需求），可复用 tri-mind 的 adapter 层
4. **不迁移数据**：Tri-Mind 历史讨论数据存在 memory storage 中，不做迁移

---

## 5. 纯角色问答（无知识库）

当用户选择了角色但未选择任何知识库时，请求不走 Knowledge Engine，直接走 AI Provider Hub：

```typescript
// chat/page.tsx 中的发送逻辑

async function handleSend(query: string) {
  const persona = getSelectedPersona()
  const kbIds = chatStore.kbIds

  if (kbIds.length === 0) {
    // 无知识库 → 直接走 AI Provider Hub chat
    await streamDirectChat(query, persona?.systemPrompt || null)
  } else {
    // 有知识库 → 走 Knowledge Engine RAG（注入 persona prompt）
    await streamRAG(query, persona?.systemPrompt || null)
  }
}

async function streamDirectChat(query: string, personaPrompt: string | null) {
  const messages = []

  if (personaPrompt) {
    messages.push({ role: 'system', content: personaPrompt })
  }

  // 注入历史消息
  for (const msg of chatStore.messages) {
    messages.push({ role: msg.role, content: msg.content })
  }
  messages.push({ role: 'user', content: query })

  const response = await fetch('/api/omni/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      model: selectedModel,
      provider: selectedProvider,
      stream: true,
    }),
  })

  // ... SSE 流式处理 ...
}
```

---

## 6. 依赖清单

### 6.1 新增前端依赖

| 包名 | 用途 | 版本 |
|------|------|------|
| `html2pdf.js` | PDF 导出 | `^0.10.1` |

### 6.2 后端改动（无新依赖）

仅修改 `schemas.py` 和 `rag_chain.py`，不引入新的 Python 依赖。

---

## 7. 开发计划

| 阶段 | 任务 | 涉及文件 | 估计改动量 |
|------|------|---------|-----------|
| **P0** | 预设角色定义 + personaStore | `preset-personas.ts`, `personaStore.ts` | 新增 2 文件 |
| **P0** | 角色选择器组件 | `persona-selector.tsx` | 新增 1 文件 |
| **P0** | RAG prompt 注入（后端） | `schemas.py`, `rag_chain.py` | 改 2 文件，各 ~10 行 |
| **P0** | RAG 请求透传（前端API） | `rag/route.ts` | 改 1 文件，~5 行 |
| **P0** | Chat 页面集成角色选择 | `chat/page.tsx` | 改 1 文件，~50 行 |
| **P1** | 角色管理弹窗 | `persona-manager.tsx`, `persona-editor.tsx` | 新增 2 文件 |
| **P2** | roundtableStore | `roundtableStore.ts` | 新增 1 文件 |
| **P2** | 圆桌控制器 | `roundtable-controller.ts`, `types.ts` | 新增 2 文件 |
| **P2** | 圆桌 API Route | `api/omni/roundtable/route.ts` | 新增 1 文件 |
| **P2** | 圆桌视图组件 | `roundtable-view.tsx` | 新增 1 文件 |
| **P2** | Chat 页面 tab 切换 | `chat/page.tsx` | 改 1 文件，~100 行 |
| **P3** | PDF 导出 | `roundtable-view.tsx` 内 | ~50 行 |
| **P3** | Tri-Mind 入口移除 | 导航组件 | 改 1-2 文件，删除引用 |
