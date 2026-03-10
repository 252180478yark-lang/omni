export type ModelProvider = 'openai' | 'anthropic' | 'gemini' | 'ollama'

export interface ModelConfig {
  id: string
  provider: ModelProvider
  modelId: string
  name: string
  enabled: boolean
  baseUrl?: string
  contextWindow: number
}

export interface ProviderConfig {
  provider: ModelProvider
  apiKey: string
  baseUrl?: string
  enabled: boolean
  models: ModelConfig[]
  hiddenDefaultModelIds?: string[]
}

export type MessageRole = 'user' | 'assistant' | 'system' | 'verdict'

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

export interface Session {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  config?: { models: string[]; rounds: number }
}

export interface DebateParams {
  sessionId: string
  query: string
  models: ModelConfig[]
  rounds: number
  files?: FileAttachment[]
  intervention?: string
  apiKeys?: Record<string, string>
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

export const DEFAULT_MODELS: Record<ModelProvider, ModelConfig[]> = {
  openai: [
    { id: 'gpt-5.2', provider: 'openai', modelId: 'gpt-5.2', name: 'GPT-5.2', enabled: true, contextWindow: 256000 },
    { id: 'gpt-5-mini', provider: 'openai', modelId: 'gpt-5-mini', name: 'GPT-5 Mini', enabled: false, contextWindow: 256000 },
  ],
  anthropic: [
    { id: 'claude-3-5-sonnet', provider: 'anthropic', modelId: 'claude-3-5-sonnet-20241022', name: 'Claude 3.5 Sonnet', enabled: true, contextWindow: 200000 },
    { id: 'claude-3-opus', provider: 'anthropic', modelId: 'claude-3-opus-20240229', name: 'Claude 3 Opus', enabled: false, contextWindow: 200000 },
    { id: 'claude-3-haiku', provider: 'anthropic', modelId: 'claude-3-haiku-20240307', name: 'Claude 3 Haiku', enabled: false, contextWindow: 200000 },
  ],
  gemini: [
    { id: 'gemini-3.1-pro-preview', provider: 'gemini', modelId: 'gemini-3.1-pro-preview', name: 'Gemini 3.1 Pro Preview', enabled: false, contextWindow: 1000000 },
    { id: 'gemini-3-pro-preview', provider: 'gemini', modelId: 'gemini-3-pro-preview', name: 'Gemini 3 Pro Preview', enabled: true, contextWindow: 1000000 },
    { id: 'gemini-3-flash-preview', provider: 'gemini', modelId: 'gemini-3-flash-preview', name: 'Gemini 3 Flash Preview', enabled: false, contextWindow: 1000000 },
  ],
  ollama: [
    { id: 'ollama-qwen3-14b', provider: 'ollama', modelId: 'qwen3:14b', name: 'Qwen3 14B', enabled: true, contextWindow: 32768 },
    { id: 'ollama-qwen3-14b-2', provider: 'ollama', modelId: 'qwen3:14b', name: 'Qwen3 14B (辩手B)', enabled: true, contextWindow: 32768 },
  ],
}

export interface ModelIdRule {
  pattern: string
  example: string
  notes: string
}

export const DEFAULT_MODEL_ID_RULES: Record<ModelProvider, ModelIdRule> = {
  openai: { pattern: '^[a-zA-Z0-9._:-]+$', example: 'gpt-5.2', notes: '仅允许字母、数字、点、下划线、冒号、连字符' },
  anthropic: { pattern: '^claude-[a-zA-Z0-9._:-]+$', example: 'claude-3-5-sonnet-20241022', notes: '建议以 claude- 开头' },
  gemini: { pattern: '^gemini-[a-zA-Z0-9._:-]+$', example: 'gemini-3.1-pro-preview', notes: '建议以 gemini- 开头' },
  ollama: { pattern: '^[a-zA-Z0-9._/-]+(?::[a-zA-Z0-9._-]+)?$', example: 'qwen3:14b', notes: '支持 name 或 name:tag 格式' },
}

export function validateModelIdByProvider(
  provider: ModelProvider,
  modelId: string,
  rules: Record<ModelProvider, ModelIdRule> = DEFAULT_MODEL_ID_RULES
): boolean {
  const rule = rules[provider]
  try {
    return new RegExp(rule.pattern).test(modelId.trim())
  } catch {
    return new RegExp(DEFAULT_MODEL_ID_RULES[provider].pattern).test(modelId.trim())
  }
}

export const PROVIDER_INFO: Record<ModelProvider, { name: string; defaultBaseUrl: string }> = {
  openai: {
    name: 'OpenAI',
    defaultBaseUrl:
      process.env.NEXT_PUBLIC_OPENAI_BASE_URL ||
      `${(process.env.NEXT_PUBLIC_OMNI_API_BASE_URL || 'http://localhost').replace(/\/$/, '')}/v1`,
  },
  anthropic: { name: 'Anthropic', defaultBaseUrl: 'https://api.anthropic.com' },
  gemini: { name: 'Gemini', defaultBaseUrl: 'https://generativelanguage.googleapis.com' },
  ollama: { name: 'Ollama (本地)', defaultBaseUrl: 'http://localhost:11434/v1' },
}
