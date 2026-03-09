import Anthropic from '@anthropic-ai/sdk'
import { Message } from '../../../../src/lib/types'
import { LLMAdapter, StreamChunk, AdapterConfig, MODEL_CONTEXT_WINDOWS } from './base.adapter'

/**
 * Anthropic 适配器
 * 支持 Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku 等模型
 */
export class AnthropicAdapter extends LLMAdapter {
  readonly provider = 'anthropic' as const
  readonly name = 'Anthropic'
  readonly defaultBaseUrl = 'https://api.anthropic.com'

  /**
   * 测试连接 —— 发送最小请求 (max_tokens=1) 验证 API Key
   */
  async testConnection(config: AdapterConfig): Promise<{ ok: boolean; error?: string }> {
    try {
      const client = new Anthropic({
        apiKey: config.apiKey,
        baseURL: config.baseUrl || this.defaultBaseUrl,
      })

      await client.messages.create({
        model: config.model,
        max_tokens: 1,
        messages: [{ role: 'user', content: 'Hi' }],
      })

      return { ok: true }
    } catch (error) {
      if (error instanceof Anthropic.APIError) {
        if (error.status === 401) {
          return { ok: false, error: 'API Key 无效，请检查是否正确' }
        } else if (error.status === 403) {
          return { ok: false, error: '无权访问该模型' }
        } else if (error.status === 429) {
          return { ok: false, error: '请求频率超限或额度不足' }
        } else {
          return { ok: false, error: `Anthropic 错误 (${error.status}): ${error.message}` }
        }
      }
      return { ok: false, error: `连接失败: ${String(error)}` }
    }
  }

  async *stream(messages: Message[], config: AdapterConfig): AsyncGenerator<StreamChunk> {
    const client = new Anthropic({
      apiKey: config.apiKey,
      baseURL: config.baseUrl || this.defaultBaseUrl,
    })

    try {
      // 分离系统消息和对话消息
      const systemMessages = messages.filter(m => m.role === 'system')
      const chatMessages = messages.filter(m => m.role !== 'system')
      
      const systemPrompt = systemMessages.map(m => m.content).join('\n\n') || undefined
      const formattedMessages = this.formatMessages(chatMessages) as Anthropic.MessageParam[]

      const stream = await client.messages.stream({
        model: config.model,
        max_tokens: 4096,
        system: systemPrompt,
        messages: formattedMessages,
      }, {
        signal: config.signal as AbortSignal | undefined,
      })

      let totalContent = ''
      let inputTokens = 0
      let outputTokens = 0

      for await (const event of stream) {
        // 检查是否被中断
        if (config.signal?.aborted) {
          yield { content: '', done: true, error: '生成已停止' }
          return
        }

        if (event.type === 'message_start') {
          inputTokens = event.message.usage?.input_tokens || 0
        } else if (event.type === 'content_block_delta') {
          if (event.delta.type === 'text_delta') {
            const text = event.delta.text
            totalContent += text
            yield { content: text, done: false }
          }
        } else if (event.type === 'message_delta') {
          outputTokens = event.usage?.output_tokens || 0
        } else if (event.type === 'message_stop') {
          yield {
            content: '',
            done: true,
            usage: {
              inputTokens,
              outputTokens,
            },
          }
        }
      }

    } catch (error) {
      if (error instanceof Anthropic.APIError) {
        let errorMessage = error.message
        
        if (error.status === 401) {
          errorMessage = 'API Key 无效'
        } else if (error.status === 403) {
          errorMessage = '无权访问该模型'
        } else if (error.status === 429) {
          errorMessage = '请求过于频繁或额度不足'
        } else if (error.status === 500) {
          errorMessage = 'Anthropic 服务器错误'
        } else if (error.status === 529) {
          errorMessage = 'API 过载，请稍后重试'
        }
        
        yield { content: '', done: true, error: errorMessage }
      } else if (error instanceof Error && error.name === 'AbortError') {
        yield { content: '', done: true, error: '生成已停止' }
      } else {
        yield { content: '', done: true, error: String(error) }
      }
    }
  }

  getContextWindow(model: string): number {
    return MODEL_CONTEXT_WINDOWS[model] || MODEL_CONTEXT_WINDOWS['default']
  }

  protected formatMessages(messages: Message[]): Anthropic.MessageParam[] {
    // Anthropic 要求 user/assistant 消息必须严格交替
    // 合并连续的相同角色消息
    const formatted: Anthropic.MessageParam[] = []
    
    for (const m of messages) {
      const role = m.role === 'user' ? 'user' : 'assistant'
      const last = formatted[formatted.length - 1]
      
      if (last && last.role === role) {
        // 合并连续的相同角色消息
        last.content = `${last.content}\n\n${m.content}`
      } else {
        formatted.push({ role, content: m.content })
      }
    }
    
    // 确保第一条消息是 user 角色（Anthropic 的要求）
    if (formatted.length > 0 && formatted[0].role !== 'user') {
      formatted.unshift({ role: 'user', content: '请回答以下问题。' })
    }
    
    return formatted
  }
}
