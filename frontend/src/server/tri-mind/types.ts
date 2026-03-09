// ==================== 模型相关类型 ====================

export type ModelProvider = 'openai' | 'anthropic' | 'google' | 'ollama'

export interface ModelConfig {
  id: string
  provider: ModelProvider
  modelId: string
  name: string
  enabled: boolean
  baseUrl?: string
  contextWindow: number
}

// ==================== 消息相关类型 ====================

export type MessageRole = 'user' | 'assistant' | 'system' | 'verdict'

export interface Message {
  id: string
  role: MessageRole
  content: string
  modelId?: string
  timestamp: number
}

export interface ChatNode {
  id: string
  sessionId: string
  parentId: string | null
  role: MessageRole
  modelId?: string
  content: string
  round?: number
  tokenInput?: number
  tokenOutput?: number
  createdAt: number
}

// ==================== 会话相关类型 ====================

export interface SessionConfig {
  models: string[]
  rounds: number
}

export interface Session {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  config?: SessionConfig
}

// ==================== 辩论相关类型 ====================

export interface DebateParams {
  sessionId: string
  query: string
  models: ModelConfig[]
  rounds: number
  files?: FileAttachment[]
  intervention?: string
  apiKeys?: Record<string, string> // provider -> apiKey (从 params 传入，不再调用 getApiKey)
  reportDetailLevel?: ReportDetailLevel
}

export type ReportDetailLevel = 'brief' | 'standard' | 'detailed'

export interface FileAttachment {
  name: string
  content: string
  type: string
}

export interface StreamChunk {
  sessionId: string
  modelId: string
  content: string
  done: boolean
  usage?: TokenUsage
  error?: string
}

export interface TokenUsage {
  inputTokens: number
  outputTokens: number
}

export interface DebateEvent {
  type: 'stream' | 'round-complete' | 'debate-complete' | 'error'
  sessionId: string
  modelId?: string
  content?: string
  round?: number
  usage?: TokenUsage
  error?: string
}

// ==================== Token预算相关类型 ====================

export type BudgetStrategy = 'pass-through' | 'compress' | 'truncate-and-warn'

export interface BudgetResult {
  strategy: BudgetStrategy
  budget: number
  compressRounds?: 'all-except-last'
  warning?: string
}

export interface RoundHistory {
  round: number
  responses: Map<string, string> // modelId -> response
  compressed?: boolean
}

// ==================== StreamWriter ====================

export interface StreamWriter {
  onChunk?: (chunk: StreamChunk) => void
  onEvent?: (event: DebateEvent) => void
}
