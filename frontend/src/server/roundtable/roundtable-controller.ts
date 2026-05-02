import { serviceBase } from '@/app/api/omni/_shared'
import type { Persona } from '@/lib/personas/types'
import type { SourceRef } from '@/stores/chatStore'
import type { RoundtableStreamEvent } from './types'

export interface RoundtableParams {
  topic: string
  participants: Persona[]
  moderatorType: 'default' | 'boss'
  totalRounds: number
  kbIds: string[]
  model?: string
  provider?: string
  targetChars?: number
}

export interface RoundHistoryPayload {
  [roundKey: string]: Record<string, string>
}

export interface InterventionPayload {
  content: string
  targetPersonaId: string | null
  afterRound: number
}

const CITATION_NOTE_FOR_MODERATOR = `

## 关于发言中的引用标记
各角色发言中可能出现 [1][2] 等数字方括号标记——那是他们检索知识库时的来源编号，不是发言序号。在你的总结里：
- 可以**提及**某个事实"已被知识库资料支撑"，但**不要原样复用 [1][2] 这种编号**（你的总结没有挂靠的来源数组，复用会变成失效引用）。
- 引用某角色发言时使用"[投放优化·第 2 轮]"这种角色+轮次格式。`

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

要求：
- **只基于本次会议的实际发言**归纳，禁止编造未发生的观点或虚构数字。
- 客观中立，不偏向任何角色。
- 引用发言时标注来源角色和轮次（如"[投放优化·第 2 轮]"）。
- 对不确定的结论明确标注"尚无共识"或"依据不足"。
- 每个章节都应展开论述，给出充分的细节和依据。${CITATION_NOTE_FOR_MODERATOR}`

const BOSS_MODERATOR_PROMPT = `你是公司 CEO，刚听完一场多角色圆桌讨论。请以老板决策者的视角整合所有信息，输出决策报告。

注意：若会议中本身存在"老板决策"角色发言，你不是替代它，而是在其基础上做最终拍板——把各方观点（含老板角色的意见）收敛成一个可执行的决定。

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

要求：
- **只基于本次会议的实际发言**做判断，禁止编造未发生的观点或虚构数字。
- 用老板的口吻，简洁直接。
- 关注利润、人效、现金流，不纠结细节。
- 每个行动项要有明确的判断标准（什么情况下叫停）。
- 每个章节都应有具体的数据、判断逻辑和决策依据。${CITATION_NOTE_FOR_MODERATOR}`

function parseKnowledgeSseChunk(buffer: string): { lines: string[]; rest: string } {
  const lines = buffer.split('\n')
  const rest = lines.pop() ?? ''
  return { lines, rest }
}

export interface PreparedRag {
  context: string
  sources: SourceRef[]
  graph_context: string
  crag_result: Record<string, unknown> | null
}

async function prepareKnowledgeRag(
  query: string,
  kbIds: string[],
  signal: AbortSignal,
): Promise<PreparedRag> {
  const base = serviceBase()
  const res = await fetch(`${base.knowledge}/api/v1/knowledge/rag/prepare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kb_ids: kbIds, query, top_k: 15 }),
    signal,
  })
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(t || `RAG prepare ${res.status}`)
  }
  const json = (await res.json()) as {
    code?: number
    data?: {
      context?: string
      sources?: SourceRef[]
      graph_context?: string
      crag_result?: Record<string, unknown>
    }
  }
  const data = json?.data ?? {}
  return {
    context: data.context ?? '',
    sources: data.sources ?? [],
    graph_context: data.graph_context ?? '',
    crag_result: data.crag_result ?? null,
  }
}

async function streamKnowledgeGenerate(
  userQuery: string,
  prepared: PreparedRag,
  personaPrompt: string,
  model: string | undefined,
  provider: string | undefined,
  signal: AbortSignal,
  onText: (t: string) => void,
  targetChars?: number,
): Promise<SourceRef[]> {
  const base = serviceBase()
  const payload: Record<string, unknown> = {
    query: userQuery,
    context: prepared.context,
    sources: prepared.sources,
    graph_context: prepared.graph_context,
    crag_result: prepared.crag_result,
    persona_prompt: personaPrompt || null,
    model,
    provider,
  }
  if (targetChars && targetChars > 0) payload.target_chars = targetChars

  const res = await fetch(`${base.knowledge}/api/v1/knowledge/rag/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(t || `RAG generate ${res.status}`)
  }
  if (!res.body) throw new Error('RAG generate 响应体为空')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let sources: SourceRef[] = prepared.sources

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const { lines, rest } = parseKnowledgeSseChunk(buf)
    buf = rest

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      const payload = trimmed.slice(5).trim()
      if (payload === '[DONE]') continue
      try {
        const obj = JSON.parse(payload) as {
          type?: string
          content?: string
          sources?: SourceRef[]
        }
        if (obj.type === 'text' && obj.content) onText(obj.content)
        else if (obj.type === 'done' && obj.sources) sources = obj.sources
      } catch {
        /* skip */
      }
    }
  }

  return sources
}

async function streamAiHubChat(
  messages: { role: string; content: string }[],
  model: string | undefined,
  provider: string | undefined,
  signal: AbortSignal,
  onToken: (t: string) => void,
  maxTokens?: number,
): Promise<void> {
  const base = serviceBase()
  const payload: Record<string, unknown> = {
    messages,
    model,
    provider,
    temperature: 0.4,
  }
  if (maxTokens) payload.max_tokens = maxTokens

  const res = await fetch(`${base.aiHub}/api/v1/ai/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(t || `AI ${res.status}`)
  }
  if (!res.body) throw new Error('AI 流为空')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n')
    buffer = parts.pop() || ''

    for (const line of parts) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      const raw = trimmed.slice(5).trim()
      if (!raw || raw === '[DONE]') continue
      try {
        const chunk = JSON.parse(raw) as { content?: string; done?: boolean }
        if (chunk.content && !chunk.done) onToken(chunk.content)
      } catch {
        /* skip */
      }
    }
  }
}

export class RoundtableController {
  private roundHistory = new Map<number, Map<string, string>>()
  private prepared: PreparedRag | null = null

  restoreHistory(rh: RoundHistoryPayload | undefined): void {
    this.roundHistory.clear()
    if (!rh) return
    for (const [rk, inner] of Object.entries(rh)) {
      const n = Number(rk)
      if (Number.isNaN(n)) continue
      this.roundHistory.set(n, new Map(Object.entries(inner)))
    }
  }

  /** Inject a previously prepared RAG context (used by BFF cache for cross-round reuse). */
  setPrepared(p: PreparedRag | null): void {
    this.prepared = p
  }

  /** Read back the controller's prepared context (for caller-side cache writeback). */
  getPrepared(): PreparedRag | null {
    return this.prepared
  }

  private idToName(participants: Persona[]): Map<string, string> {
    return new Map(participants.map((p) => [p.id, p.name]))
  }

  /**
   * Build a clean retrieval query — just the topic, no prev-speech noise.
   * Used for the SHARED retrieval done once per round across all personas.
   * Avoids embedding a giant prev-round block, which would dilute the query
   * vector and cause off-topic chunks to surface in round 2+.
   */
  private buildRetrievalQuery(topic: string): string {
    return topic
  }

  private buildPersonaQuery(
    topic: string,
    persona: Persona,
    round: number,
    participants: Persona[],
    interventions: InterventionPayload[],
  ): string {
    const names = this.idToName(participants)
    const ivs = interventions.filter((i) => i.afterRound === round - 1)
    const otherNames = participants
      .filter((p) => p.id !== persona.id)
      .map((p) => p.name)
      .join('、')

    if (round === 1) {
      let q =
        `你正在参加一场多角色圆桌会议（第 1 轮）。\n` +
        `参会角色：${persona.name}（你）${otherNames ? `、${otherNames}` : ''}\n` +
        `议题：${topic}\n\n` +
        `请从【${persona.name}】的专业视角切入，重点输出**只有你这个角色才会看到、其他角色容易忽略**的观点。\n` +
        `避免泛泛而谈用户研究/数据看板/常识结论——把通用部分让给其他角色，专注你的差异化角度。\n` +
        `给出核心观点、关键数据/依据、可执行建议。`
      for (const iv of ivs) {
        if (iv.targetPersonaId === null || iv.targetPersonaId === persona.id) {
          q += `\n\n---用户追问---\n${iv.content}`
        }
      }
      return q
    }

    const prev = this.roundHistory.get(round - 1)
    let mySelfPrev = ''
    let othersPrev = ''
    if (prev) {
      for (const [pid, content] of Array.from(prev.entries())) {
        if (pid === persona.id) {
          mySelfPrev = content
        } else {
          const label = names.get(pid) || pid
          othersPrev += `【${label}】\n${content}\n\n`
        }
      }
    }

    let query =
      `这是圆桌会议第 ${round} 轮（共 ${participants.length} 位参会者）。\n\n` +
      `### 你（${persona.name}）的任务\n` +
      `- **不要重复你上一轮的观点**（见下方"你上一轮的发言"），要在原有基础上**往深推进**或**自我修正**\n` +
      `- 针对其他角色上轮发言中你认为的盲区、误判、风险，给出反驳或补充\n` +
      `- 必要时用具体数据、案例、方法论支撑\n\n` +
      `---你上一轮的发言（仅供你自我对照，避免复读）---\n${mySelfPrev || '（你上一轮未发言）'}\n\n` +
      `---其他参会者上轮发言---\n${othersPrev || '（暂无）'}\n` +
      `---议题---\n${topic}`

    for (const iv of ivs) {
      if (iv.targetPersonaId === null || iv.targetPersonaId === persona.id) {
        query += `\n\n---用户追问---\n${iv.content}`
      }
    }

    return query
  }

  async runRound(
    params: RoundtableParams,
    round: number,
    interventions: InterventionPayload[],
    onEvent: (e: RoundtableStreamEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const roundResponses = new Map<string, string>()

    // Shared retrieval: run the heavy RAG pipeline ONCE per roundtable session
    // (parse → embed → hybrid search → rerank → CRAG → compress). All personas
    // AND all rounds share these chunks; only LLM generation differs per persona.
    // Cache hit (set via setPrepared by caller) skips retrieval entirely.
    let prepared: PreparedRag
    try {
      if (this.prepared) {
        prepared = this.prepared
      } else {
        prepared = await prepareKnowledgeRag(
          this.buildRetrievalQuery(params.topic),
          params.kbIds,
          signal,
        )
        this.prepared = prepared
      }
    } catch (err: unknown) {
      const name = err instanceof Error ? err.name : ''
      if (name === 'AbortError') return
      const msg = err instanceof Error ? err.message : String(err)
      // Bubble retrieval failure as a per-persona error so the UI surfaces it,
      // and seed each speech with the error message so users see what happened.
      for (const persona of params.participants) {
        onEvent({
          type: 'speech-start',
          personaId: persona.id,
          personaName: persona.name,
          personaIcon: persona.icon,
          round,
        })
        onEvent({ type: 'error', personaId: persona.id, error: msg })
        onEvent({
          type: 'speech-done',
          personaId: persona.id,
          personaName: persona.name,
          personaIcon: persona.icon,
          round,
          content: `⚠ 检索失败：${msg}`,
          sources: [],
        })
      }
      this.roundHistory.set(round, roundResponses)
      onEvent({ type: 'round-complete', round })
      return
    }

    const tasks = params.participants.map(async (persona) => {
      onEvent({
        type: 'speech-start',
        personaId: persona.id,
        personaName: persona.name,
        personaIcon: persona.icon,
        round,
      })

      const userQuery = this.buildPersonaQuery(
        params.topic,
        persona,
        round,
        params.participants,
        interventions,
      )
      let full = ''

      try {
        const sources = await streamKnowledgeGenerate(
          userQuery,
          prepared,
          persona.systemPrompt || '',
          params.model,
          params.provider,
          signal,
          (t) => {
            full += t
            onEvent({ type: 'speech-token', personaId: persona.id, round, content: t })
          },
          params.targetChars,
        )

        roundResponses.set(persona.id, full)
        onEvent({
          type: 'speech-done',
          personaId: persona.id,
          personaName: persona.name,
          personaIcon: persona.icon,
          round,
          content: full,
          sources,
        })
      } catch (err: unknown) {
        const name = err instanceof Error ? err.name : ''
        if (name === 'AbortError') return
        const msg = err instanceof Error ? err.message : String(err)
        onEvent({ type: 'error', personaId: persona.id, error: msg })
        roundResponses.set(persona.id, full || `⚠ ${msg}`)
        onEvent({
          type: 'speech-done',
          personaId: persona.id,
          personaName: persona.name,
          personaIcon: persona.icon,
          round,
          content: full || `⚠ ${msg}`,
          sources: [],
        })
      }
    })

    await Promise.all(tasks)
    this.roundHistory.set(round, roundResponses)
    onEvent({ type: 'round-complete', round })
  }

  async runSummary(
    params: RoundtableParams,
    interventions: InterventionPayload[],
    onEvent: (e: RoundtableStreamEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    onEvent({ type: 'summary-start' })

    let allSpeechesText = ''
    const rounds = Array.from(this.roundHistory.keys()).sort((a, b) => a - b)
    for (const r of rounds) {
      const responses = this.roundHistory.get(r)
      if (!responses) continue
      allSpeechesText += `--- 第 ${r} 轮 ---\n\n`
      for (const [personaId, content] of Array.from(responses.entries())) {
        const p = params.participants.find((x) => x.id === personaId)
        const label = p?.name || personaId
        allSpeechesText += `【${label}】\n${content}\n\n`
      }
    }

    if (interventions.length > 0) {
      allSpeechesText += `--- 用户插话记录 ---\n\n`
      for (const intervention of interventions) {
        const target = intervention.targetPersonaId
          ? (params.participants.find((x) => x.id === intervention.targetPersonaId)?.name ||
            intervention.targetPersonaId)
          : '全员'
        allSpeechesText += `[${target}] ${intervention.content}\n\n`
      }
    }

    const baseModeratorPrompt =
      params.moderatorType === 'boss' ? BOSS_MODERATOR_PROMPT : DEFAULT_MODERATOR_PROMPT
    // 飞轮：拉取累积规则拼到末尾
    let moderatorPrompt = baseModeratorPrompt
    try {
      const r = await fetch('/api/omni/prompt/render-rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_id: 'chat.roundtable_moderator',
          scope: { moderator_type: params.moderatorType || 'default' },
        }),
      })
      const j = await r.json()
      const suffix = (j?.data?.suffix as string) || ''
      if (suffix) moderatorPrompt = baseModeratorPrompt + suffix
    } catch {
      /* 非关键路径,吞掉异常 */
    }

    const tgt = Math.min(Math.max(params.targetChars ?? 0, 0), 200_000)

    let userContent =
      `以下是一场多角色圆桌会议的完整讨论记录。\n\n` +
      `议题：${params.topic}\n` +
      `参会角色：${params.participants.map((p) => p.name).join('、')}\n` +
      `讨论轮数：${rounds.length}轮\n\n` +
      `${allSpeechesText}\n\n` +
      `请根据以上讨论内容，生成结构化的总结报告。`

    if (tgt > 0) {
      userContent +=
        `\n\n【系统指令】全文目标约 ${tgt} 个字符；` +
        `服务端将自动多轮续写直至接近此规模。` +
        `请务必开始撰写，勿以单次字数上限为由拒绝开篇；` +
        `单轮未写完时可自然收笔，下一轮会自动接续。`
    }

    try {
      if (tgt <= 0) {
        await streamAiHubChat(
          [
            { role: 'system', content: moderatorPrompt },
            { role: 'user', content: userContent },
          ],
          params.model,
          params.provider,
          signal,
          (t) => onEvent({ type: 'summary-token', content: t }),
          16384,
        )
      } else {
        const MAX_CONTINUE_ROUNDS = 10
        const TARGET_RATIO = 0.95
        const thread: { role: string; content: string }[] = [
          { role: 'system', content: moderatorPrompt },
          { role: 'user', content: userContent },
        ]
        let written = 0

        for (let r = 0; r < MAX_CONTINUE_ROUNDS; r++) {
          if (r > 0) {
            thread.push({
              role: 'user',
              content:
                `请直接接续上文输出（第 ${r + 1} 段），不要重复已写段落。` +
                `当前累计约 ${written} 字符，目标全文约 ${tgt} 字符；本段请尽量充实展开。`,
            })
          }

          let piece = ''
          await streamAiHubChat(
            thread,
            params.model,
            params.provider,
            signal,
            (t) => {
              piece += t
              onEvent({ type: 'summary-token', content: t })
            },
            16384,
          )

          thread.push({ role: 'assistant', content: piece })
          written += piece.length

          onEvent({
            type: 'summary-continue-meta',
            continueRound: r + 1,
            charsSoFar: written,
            target: tgt,
          })

          if (written >= tgt * TARGET_RATIO) break
          if (r > 0 && piece.trim().length < 40) break
        }
      }
      onEvent({ type: 'summary-done' })
    } catch (err: unknown) {
      const name = err instanceof Error ? err.name : ''
      if (name === 'AbortError') return
      const msg = err instanceof Error ? err.message : String(err)
      onEvent({ type: 'error', error: msg })
    }
  }
}
