// frontend/src/lib/agent-chat/types.ts

// === Claude Code stream-json 输出的 4 类 chunk ===
// 参考: https://docs.anthropic.com/en/docs/claude-code/cli-reference#headless-mode

export interface ClaudeStreamChunk {
  type:
    | 'system'           // session 启动等系统消息
    | 'assistant'        // Claude 文本/思考输出（含 tool_use）
    | 'user'             // 工具调用返回（tool_result）
    | 'result'           // 整个任务完成
  message?: {
    id: string
    type: 'message'
    role: 'assistant' | 'user'
    content: Array<
      | { type: 'text'; text: string }
      | { type: 'thinking'; thinking: string }
      | { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> }
      | { type: 'tool_result'; tool_use_id: string; content: string | Array<{ type: string; text?: string }>; is_error?: boolean }
    >
    stop_reason?: string
    usage?: { input_tokens: number; output_tokens: number }
  }
  // result type chunk
  result?: string
  is_error?: boolean
  duration_ms?: number
  num_turns?: number
  session_id?: string
  total_cost_usd?: number
}

// === 前端渲染用的统一消息结构 ===
export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'human_gate' | 'system'
  // role='user' | 'assistant' 时
  text?: string
  // role='tool_call' 时
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_use_id?: string
  tool_status?: 'pending' | 'completed' | 'error'
  // role='tool_result' 时 - 多模态附件
  attachments?: ChatAttachment[]
  raw_result?: unknown
  // role='human_gate' 时
  gate_short_id?: string
  gate_summary?: string
  gate_decision?: 'pending' | 'approved' | 'rejected'
  created_at: string
}

export interface ChatAttachment {
  type: 'image' | 'video' | 'markdown' | 'json' | 'table' | 'link'
  // image / video
  url?: string
  thumbnail_url?: string
  alt?: string
  // markdown
  markdown?: string
  // json / table
  data?: unknown
  // link
  href?: string
  label?: string
}

// === Session 状态 ===
export interface SessionState {
  id: string                  // PG mcp.agent_sessions.id
  claude_session_id: string   // Claude Code 自己的 session uuid
  title: string
  sku_id: string | null
  last_message_preview: string | null
  message_count: number
  status: 'active' | 'archived' | 'deleted'
  created_at: string
  updated_at: string
}

// === WebSocket 消息协议（前后端互通）===
export type BrainProvider = 'codex' | 'claude'
export type BrainEffortLevel = 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface PlaygroundSpawnConfig {
  /** 主大脑 provider；不传时后端按环境默认处理 */
  brain_provider?: BrainProvider
  /** Codex/Claude 模型名；Codex 映射 --model，Claude 映射 --model */
  model?: string
  /** Codex 映射 model_reasoning_effort，Claude 映射 --effort */
  effort?: BrainEffortLevel
  /** 空数组或不传 = 全开;非空 = 限定为这几个 */
  allowed_tools?: string[]
  /** --append-system-prompt 内容 */
  append_system_prompt?: string
  /** --max-turns */
  max_turns?: number
}

export type WsClientMessage =
  | { kind: 'open_session'; session_id: string }
  | { kind: 'close_session'; session_id: string }
  | {
      kind: 'send_prompt'
      session_id: string
      prompt: string
      attachments?: ChatAttachment[]
      /** /playground 专用:覆盖 spawn args(model / allowed_tools / append_system_prompt / max_turns) */
      config?: PlaygroundSpawnConfig
    }
  | { kind: 'cancel'; session_id: string }
  | { kind: 'human_gate_decide'; short_id: string; decision: 'approved' | 'rejected'; note?: string }

export type WsServerMessage =
  | { kind: 'session_opened'; session: SessionState; history: ChatMessage[]; trace_id?: string }
  | { kind: 'chunk'; session_id: string; message: ChatMessage; trace_id?: string; sequence?: number }
  | { kind: 'chunk_delta'; session_id: string; message_id: string; text_delta: string }
  | { kind: 'message_completed'; session_id: string; message: ChatMessage }
  | { kind: 'task_done'; session_id: string; duration_ms: number; total_cost_usd: number; tokens: { input: number; output: number }; trace_id?: string }
  | { kind: 'trace_started'; session_id: string; trace_id: string; execution_id: string }
  | { kind: 'trace_gap'; session_id: string; trace_id: string; reason: 'publisher_disabled' | 'append_failed' }
  | { kind: 'error'; session_id?: string; error: string; detail?: string }
  | { kind: 'human_gate_new'; session_id: string; gate: { short_id: string; summary: string; tool_name: string } }
