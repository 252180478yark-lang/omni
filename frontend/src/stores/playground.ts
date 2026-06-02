import { create } from 'zustand'
import type { ChatMessage } from '@/lib/agent-chat/types'

export type PlaygroundModel = 'sonnet' | 'opus' | 'haiku'

export interface PlaygroundConfig {
  model: PlaygroundModel
  /** 空数组 = 全开;非空 = 限定为这几个 tool 名 */
  allowedTools: string[]
  extraSystemPrompt: string
  maxTurns: number
}

export interface TraceField {
  // backend build_trace 返这个 schema
  model_provider?: string
  model?: string
  final_prompt?: string
  params?: Record<string, unknown>
  cost_estimate?: string
  // 老式或自定义字段(读取 tool 时尽量保留原 dict)
  [key: string]: unknown
}

export interface ToolCallTrace {
  /** Claude 给的 tool_use.id */
  tool_use_id: string
  tool_name: string
  input: Record<string, unknown> | undefined
  /** result 解析后的 dict, 含 ok / result / trace 等;原 result 也保留在 raw_output */
  parsed_output?: Record<string, unknown>
  raw_output?: unknown
  status: 'pending' | 'completed' | 'error'
  /** 从 parsed_output.trace 抽出来的, 没有就 undefined */
  trace_field?: TraceField
  /** 估算的 cost(ai-provider-hub 那层) — 解析 trace.cost_estimate 字符串 */
  cost_usd?: number
  /** ms */
  latency_ms?: number
  created_at: string
}

export interface PlaygroundState {
  config: PlaygroundConfig
  setConfig: (patch: Partial<PlaygroundConfig>) => void

  /** playground 的 sandbox session id (mcp.agent_sessions.id) */
  sessionId: string | null
  setSessionId: (id: string | null) => void

  messages: ChatMessage[]
  toolCalls: ToolCallTrace[]

  /** 累计 token (主 Claude) */
  tokensIn: number
  tokensOut: number
  /** 主 Claude task_done 给的 total_cost_usd(包含 Max 订阅, 仅供参考) */
  claudeCostUsd: number
  /** 次级 LLM 真实 API cost: 累计 toolCalls[*].cost_usd */
  toolApiCostUsd: number
  /** task 总 latency(ms) */
  totalLatencyMs: number

  running: boolean
  setRunning: (b: boolean) => void

  /** ConvPane 当前输入(lift up 让 ConfigPanel 的"运行"按钮也能触发发送) */
  pendingInput: string
  setPendingInput: (s: string) => void

  appendMessage: (msg: ChatMessage) => void
  upsertMessage: (msg: ChatMessage) => void
  appendToolCall: (tc: ToolCallTrace) => void
  updateToolCallResult: (toolUseId: string, parsedOutput: unknown, rawOutput: unknown) => void

  accumulateTask: (dur: number, costUsd: number, tokIn: number, tokOut: number) => void
  resetConversation: () => void
}

const DEFAULT_CONFIG: PlaygroundConfig = {
  model: 'sonnet',
  allowedTools: [],
  extraSystemPrompt: '',
  maxTurns: 10,
}

// trace.cost_estimate 是字符串如 "¥0.5" / "$0.0023" / "1 quota call" — 尝试解析
function parseCostEstimate(s: unknown): number | undefined {
  if (typeof s !== 'string') return undefined
  // 匹配第一个数字(可带小数点)
  const m = s.match(/[¥$]?\s*([0-9]+(?:\.[0-9]+)?)/)
  if (!m) return undefined
  const n = parseFloat(m[1])
  if (Number.isNaN(n)) return undefined
  // ¥ 简单 7:1 估算成 $
  if (s.includes('¥')) return n / 7
  return n
}

function extractTrace(parsed: unknown): { trace?: TraceField; cost?: number; latency?: number } {
  if (typeof parsed !== 'object' || parsed === null) return {}
  const obj = parsed as Record<string, unknown>
  const traceRaw = obj.trace
  if (typeof traceRaw !== 'object' || traceRaw === null) return {}
  const t = traceRaw as TraceField
  return {
    trace: t,
    cost: parseCostEstimate(t.cost_estimate),
    latency: typeof t.latency_ms === 'number' ? (t.latency_ms as number) : undefined,
  }
}

// tool_result.content 后端给的是 string (JSON 序列化的 dict) 或 array
// 复用 ws-handler 的策略 — 尝试 JSON.parse
function tryParseResult(raw: unknown): unknown {
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  }
  // array of { type: 'text', text } 时取第一个 text
  if (Array.isArray(raw) && raw.length > 0) {
    const first = raw[0] as { type?: string; text?: string }
    if (first && typeof first.text === 'string') {
      try {
        return JSON.parse(first.text)
      } catch {
        return null
      }
    }
  }
  return null
}

export const usePlaygroundStore = create<PlaygroundState>((set) => ({
  config: DEFAULT_CONFIG,
  setConfig: (patch) => set((s) => ({ config: { ...s.config, ...patch } })),

  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),

  messages: [],
  toolCalls: [],

  tokensIn: 0,
  tokensOut: 0,
  claudeCostUsd: 0,
  toolApiCostUsd: 0,
  totalLatencyMs: 0,

  running: false,
  setRunning: (b) => set({ running: b }),

  pendingInput: '',
  setPendingInput: (s) => set({ pendingInput: s }),

  appendMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  upsertMessage: (msg) =>
    set((s) => {
      if (msg.role === 'tool_result' && msg.tool_use_id) {
        // 把对应的 tool_call 标 completed,再 push 这条
        const callIdx = s.messages.findIndex(
          (m) => m.role === 'tool_call' && m.tool_use_id === msg.tool_use_id,
        )
        if (callIdx >= 0) {
          const next = [...s.messages]
          next[callIdx] = { ...next[callIdx], tool_status: 'completed' }
          return { messages: [...next, msg] }
        }
      }
      return { messages: [...s.messages, msg] }
    }),

  appendToolCall: (tc) => set((s) => ({ toolCalls: [...s.toolCalls, tc] })),

  updateToolCallResult: (toolUseId, parsedOutput, rawOutput) =>
    set((s) => {
      const idx = s.toolCalls.findIndex((t) => t.tool_use_id === toolUseId)
      if (idx < 0) return {}
      const tc = s.toolCalls[idx]
      const parsed = (parsedOutput as Record<string, unknown>) ?? undefined
      const { trace, cost, latency } = extractTrace(parsed ?? tryParseResult(rawOutput))
      const updated: ToolCallTrace = {
        ...tc,
        parsed_output: parsed,
        raw_output: rawOutput,
        status: 'completed',
        trace_field: trace,
        cost_usd: cost,
        latency_ms: latency,
      }
      const next = [...s.toolCalls]
      next[idx] = updated
      const totalCost = next.reduce((sum, t) => sum + (t.cost_usd || 0), 0)
      return { toolCalls: next, toolApiCostUsd: totalCost }
    }),

  accumulateTask: (dur, costUsd, tokIn, tokOut) =>
    set((s) => ({
      totalLatencyMs: s.totalLatencyMs + dur,
      claudeCostUsd: s.claudeCostUsd + costUsd,
      tokensIn: s.tokensIn + tokIn,
      tokensOut: s.tokensOut + tokOut,
    })),

  resetConversation: () =>
    set({
      messages: [],
      toolCalls: [],
      tokensIn: 0,
      tokensOut: 0,
      claudeCostUsd: 0,
      toolApiCostUsd: 0,
      totalLatencyMs: 0,
    }),
}))

// 公开 helpers 给组件 / api.ts 用
export { parseCostEstimate, extractTrace, tryParseResult }
