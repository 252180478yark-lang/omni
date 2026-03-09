import type { ModelProvider } from '../types'
import { LLMAdapter } from './base.adapter'
import { OpenAIAdapter } from './openai.adapter'
import { AnthropicAdapter } from './anthropic.adapter'
import { GeminiAdapter } from './gemini.adapter'
import { OllamaAdapter } from './ollama.adapter'

export * from './base.adapter'
export { OpenAIAdapter } from './openai.adapter'
export { AnthropicAdapter } from './anthropic.adapter'
export { GeminiAdapter } from './gemini.adapter'
export { OllamaAdapter } from './ollama.adapter'

class AdapterManager {
  private adapters = new Map<ModelProvider, LLMAdapter>()

  constructor() {
    this.register(new OpenAIAdapter())
    this.register(new AnthropicAdapter())
    this.register(new GeminiAdapter())
    this.register(new OllamaAdapter())
  }

  private register(adapter: LLMAdapter) {
    this.adapters.set(adapter.provider, adapter)
  }

  get(provider: ModelProvider): LLMAdapter | undefined {
    return this.adapters.get(provider)
  }

  getAll(): LLMAdapter[] {
    return Array.from(this.adapters.values())
  }

  has(provider: ModelProvider): boolean {
    return this.adapters.has(provider)
  }
}

export const adapterManager = new AdapterManager()
