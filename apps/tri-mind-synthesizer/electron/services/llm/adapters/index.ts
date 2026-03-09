import { ModelProvider } from '../../../../src/lib/types'
import { LLMAdapter } from './base.adapter'
import { OpenAIAdapter } from './openai.adapter'
import { AnthropicAdapter } from './anthropic.adapter'
import { GeminiAdapter } from './gemini.adapter'
import { OllamaAdapter } from './ollama.adapter'

export * from './base.adapter'
export * from './openai.adapter'
export * from './anthropic.adapter'
export * from './gemini.adapter'
export * from './ollama.adapter'

/**
 * 适配器管理器
 * 提供统一的适配器访问接口
 */
class AdapterManager {
  private adapters: Map<ModelProvider, LLMAdapter> = new Map()

  constructor() {
    // 注册所有适配器
    this.register(new OpenAIAdapter())
    this.register(new AnthropicAdapter())
    this.register(new GeminiAdapter())
    this.register(new OllamaAdapter())
  }

  /**
   * 注册适配器
   */
  private register(adapter: LLMAdapter) {
    this.adapters.set(adapter.provider, adapter)
  }

  /**
   * 获取适配器
   */
  get(provider: ModelProvider): LLMAdapter | undefined {
    return this.adapters.get(provider)
  }

  /**
   * 获取所有适配器
   */
  getAll(): LLMAdapter[] {
    return Array.from(this.adapters.values())
  }

  /**
   * 检查适配器是否存在
   */
  has(provider: ModelProvider): boolean {
    return this.adapters.has(provider)
  }
}

// 导出单例实例
export const adapterManager = new AdapterManager()
