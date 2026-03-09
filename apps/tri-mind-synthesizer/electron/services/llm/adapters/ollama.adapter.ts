import OpenAI from 'openai'
import { Message } from '../../../../src/lib/types'
import { LLMAdapter, StreamChunk, AdapterConfig, MODEL_CONTEXT_WINDOWS } from './base.adapter'

/**
 * Ollama 适配器
 * 使用 OpenAI 兼容接口连接本地 Ollama 服务
 */
export class OllamaAdapter extends LLMAdapter {
  readonly provider = 'ollama' as const
  readonly name = 'Ollama (本地)'
  readonly defaultBaseUrl = 'http://localhost:11434/v1'

  async *stream(messages: Message[], config: AdapterConfig): AsyncGenerator<StreamChunk> {
    const client = new OpenAI({
      apiKey: config.apiKey || 'ollama', // Ollama 不需要真正的 API Key
      baseURL: config.baseUrl || this.defaultBaseUrl,
      dangerouslyAllowBrowser: false,
    })

    try {
      const formattedMessages = this.formatMessages(messages) as OpenAI.Chat.ChatCompletionMessageParam[]

      const stream = await client.chat.completions.create({
        model: config.model,
        messages: formattedMessages,
        stream: true,
      }, {
        signal: config.signal,
      })

      let totalContent = ''

      for await (const chunk of stream) {
        // 检查是否被中断
        if (config.signal?.aborted) {
          yield { content: '', done: true, error: '生成已停止' }
          return
        }

        const delta = chunk.choices[0]?.delta?.content || ''
        totalContent += delta

        // 检查是否完成
        const finishReason = chunk.choices[0]?.finish_reason
        const done = finishReason !== null && finishReason !== undefined

        yield {
          content: delta,
          done,
          usage: done ? {
            inputTokens: this.estimateTokens(messages.map(m => m.content).join('')),
            outputTokens: this.estimateTokens(totalContent),
          } : undefined,
        }
      }

    } catch (error) {
      let errorMessage = String(error)
      
      if (errorMessage.includes('ECONNREFUSED')) {
        errorMessage = 'Ollama 服务未启动，请先运行 "ollama serve"'
      } else if (errorMessage.includes('model not found')) {
        errorMessage = `模型 "${config.model}" 未找到，请先运行 "ollama pull ${config.model}"`
      }
      
      yield { content: '', done: true, error: errorMessage }
    }
  }

  getContextWindow(model: string): number {
    // Ollama 模型的上下文窗口取决于具体模型
    // 默认使用较小的窗口，用户可以在配置中自定义
    return MODEL_CONTEXT_WINDOWS[model] || 4096
  }

  protected formatMessages(messages: Message[]): OpenAI.Chat.ChatCompletionMessageParam[] {
    return messages.map(m => ({
      role: (m.role === 'verdict' ? 'assistant' : m.role) as 'user' | 'assistant' | 'system',
      content: m.content,
    }))
  }

  /**
   * 测试 Ollama 连接
   * 直接检查服务是否可用
   */
  async testConnection(config: AdapterConfig): Promise<{ ok: boolean; error?: string }> {
    try {
      const baseUrl = config.baseUrl || this.defaultBaseUrl
      const response = await fetch(baseUrl.replace('/v1', '/api/tags'), {
        method: 'GET',
        signal: config.signal,
      })
      
      if (!response.ok) {
        return { ok: false, error: `Ollama 服务返回错误: ${response.status}` }
      }
      
      const data = await response.json()
      const models = data.models || []
      
      // 检查指定的模型是否存在
      const modelExists = models.some((m: { name: string }) => 
        m.name === config.model || m.name.startsWith(config.model + ':')
      )
      
      if (!modelExists && models.length > 0) {
        return { 
          ok: false, 
          error: `模型 "${config.model}" 未找到。可用模型: ${models.map((m: { name: string }) => m.name).join(', ')}`
        }
      }
      
      return { ok: true }
    } catch (error) {
      if (String(error).includes('ECONNREFUSED')) {
        return { ok: false, error: 'Ollama 服务未启动，请先运行 "ollama serve"' }
      }
      return { ok: false, error: String(error) }
    }
  }
}
