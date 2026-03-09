import { Message, ModelProvider } from '../../../../src/lib/types'

/**
 * 流式输出块
 */
export interface StreamChunk {
  content: string
  done: boolean
  usage?: {
    inputTokens: number
    outputTokens: number
  }
  error?: string
}

/**
 * 适配器配置
 */
export interface AdapterConfig {
  apiKey: string
  baseUrl?: string
  model: string
  signal?: AbortSignal
}

/**
 * LLM 适配器抽象基类
 * 
 * 所有模型厂商的适配器都需要继承此类，实现统一的接口
 */
export abstract class LLMAdapter {
  /** 提供商标识 */
  abstract readonly provider: ModelProvider

  /** 提供商名称 */
  abstract readonly name: string

  /** 默认 API 端点 */
  abstract readonly defaultBaseUrl: string

  /**
   * 流式对话
   * @param messages 消息列表
   * @param config 配置
   * @yields StreamChunk 流式输出块
   */
  abstract stream(
    messages: Message[],
    config: AdapterConfig
  ): AsyncGenerator<StreamChunk>

  /**
   * 估算 Token 数量
   * 使用简单的字符计数估算，约 4 字符 = 1 token（英文）
   * 中文约 1.5 字符 = 1 token
   * @param text 文本内容
   * @returns 估算的 token 数量
   */
  estimateTokens(text: string): number {
    // 简单估算：英文约 4 字符/token，中文约 1.5 字符/token
    // 混合文本取平均值
    const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length
    const otherChars = text.length - chineseChars
    
    return Math.ceil(chineseChars / 1.5 + otherChars / 4)
  }

  /**
   * 获取模型的上下文窗口大小
   * @param model 模型ID
   * @returns 上下文窗口大小（tokens）
   */
  abstract getContextWindow(model: string): number

  /**
   * 测试连接
   * @param config 配置
   * @returns 是否连接成功
   */
  async testConnection(config: AdapterConfig): Promise<{ ok: boolean; error?: string }> {
    try {
      const testMessages: Message[] = [
        { id: 'test', role: 'user', content: 'Hi', timestamp: Date.now() }
      ]
      
      const generator = this.stream(testMessages, config)
      const firstChunk = await generator.next()
      
      // 取消生成
      if (config.signal) {
        // AbortController 会处理取消
      }
      
      if (firstChunk.value?.error) {
        return { ok: false, error: firstChunk.value.error }
      }
      
      return { ok: true }
    } catch (error) {
      return { ok: false, error: String(error) }
    }
  }

  /**
   * 将统一消息格式转换为提供商特定格式
   */
  protected formatMessages(messages: Message[]): unknown[] {
    return messages.map(m => ({
      role: m.role === 'verdict' ? 'assistant' : m.role,
      content: m.content
    }))
  }
}

/**
 * 模型上下文窗口配置
 */
export const MODEL_CONTEXT_WINDOWS: Record<string, number> = {
  // OpenAI
  'gpt-5.2': 256000,
  'gpt-5-mini': 256000,
  'gpt-4o': 128000,
  'gpt-4o-mini': 128000,
  'gpt-4-turbo': 128000,
  'gpt-4': 8192,
  'gpt-3.5-turbo': 16385,
  
  // Anthropic
  'claude-3-5-sonnet-20241022': 200000,
  'claude-3-opus-20240229': 200000,
  'claude-3-sonnet-20240229': 200000,
  'claude-3-haiku-20240307': 200000,
  
  // Google
  'gemini-3-pro-preview': 1000000,
  'gemini-3-flash-preview': 1000000,
  'gemini-1.5-pro': 2000000,
  'gemini-1.5-flash': 1000000,
  'gemini-pro': 32000,
  
  // 默认值
  'default': 4096,
}
