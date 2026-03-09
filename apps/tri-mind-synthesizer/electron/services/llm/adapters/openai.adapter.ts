import OpenAI from 'openai'
import { Message } from '../../../../src/lib/types'
import { LLMAdapter, StreamChunk, AdapterConfig, MODEL_CONTEXT_WINDOWS } from './base.adapter'

/**
 * OpenAI 适配器
 * 支持 GPT-5.2, GPT-5 Mini 等模型
 */
export class OpenAIAdapter extends LLMAdapter {
  readonly provider = 'openai' as const
  readonly name = 'OpenAI'
  readonly defaultBaseUrl = 'https://api.openai.com/v1'

  /**
   * 测试连接 —— 使用轻量的 models.list 接口，不消耗 token
   */
  async testConnection(config: AdapterConfig): Promise<{ ok: boolean; error?: string }> {
    try {
      const client = new OpenAI({
        apiKey: config.apiKey,
        baseURL: config.baseUrl || this.defaultBaseUrl,
        dangerouslyAllowBrowser: false,
        timeout: 15000,
      })

      // 只列出模型列表来验证 API Key，不发送聊天请求
      const models = await client.models.list()
      
      // 检查指定的模型是否可用
      let modelFound = false
      for await (const model of models) {
        if (model.id === config.model) {
          modelFound = true
          break
        }
      }

      if (!modelFound) {
        return { ok: true } // API Key 有效，模型可能是新的还未列出，不报错
      }

      return { ok: true }
    } catch (error) {
      if (error instanceof OpenAI.APIError) {
        if (error.status === 401) {
          return { ok: false, error: 'API Key 无效，请检查是否正确' }
        } else if (error.status === 403) {
          return { ok: false, error: '无权访问，请检查 API Key 权限' }
        } else if (error.status === 429) {
          return { ok: false, error: '请求频率超限或额度不足，请到 OpenAI 后台检查用量和账单' }
        } else {
          return { ok: false, error: `OpenAI 错误 (${error.status}): ${error.message}` }
        }
      }
      return { ok: false, error: `连接失败: ${String(error)}` }
    }
  }

  async *stream(messages: Message[], config: AdapterConfig): AsyncGenerator<StreamChunk> {
    const client = new OpenAI({
      apiKey: config.apiKey,
      baseURL: config.baseUrl || this.defaultBaseUrl,
      dangerouslyAllowBrowser: false,
    })

    try {
      const formattedMessages = this.formatMessages(messages) as OpenAI.Chat.ChatCompletionMessageParam[]

      const stream = await client.chat.completions.create({
        model: config.model,
        messages: formattedMessages,
        stream: true,
        stream_options: { include_usage: true },
      }, {
        signal: config.signal,
      })

      let totalContent = ''
      let usage: { inputTokens: number; outputTokens: number } | undefined

      for await (const chunk of stream) {
        // 检查是否被中断
        if (config.signal?.aborted) {
          yield { content: '', done: true, error: '生成已停止' }
          return
        }

        const delta = chunk.choices[0]?.delta?.content || ''
        totalContent += delta

        // 检查 usage 信息（在最后一个 chunk 中）
        if (chunk.usage) {
          usage = {
            inputTokens: chunk.usage.prompt_tokens,
            outputTokens: chunk.usage.completion_tokens,
          }
        }

        // 检查是否完成
        const finishReason = chunk.choices[0]?.finish_reason
        const done = finishReason !== null && finishReason !== undefined

        yield {
          content: delta,
          done,
          usage: done ? usage : undefined,
        }
      }

      // 确保发送最终的完成信号
      if (!usage) {
        // 如果没有收到 usage，估算一下
        usage = {
          inputTokens: this.estimateTokens(messages.map(m => m.content).join('')),
          outputTokens: this.estimateTokens(totalContent),
        }
      }

    } catch (error) {
      if (error instanceof OpenAI.APIError) {
        let errorMessage = error.message
        
        if (error.status === 401) {
          errorMessage = 'API Key 无效'
        } else if (error.status === 403) {
          errorMessage = '无权访问该模型'
        } else if (error.status === 429) {
          errorMessage = '请求频率超限或额度不足，请到 platform.openai.com 检查账单和用量'
        } else if (error.status === 500) {
          errorMessage = 'OpenAI 服务器错误'
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

  protected formatMessages(messages: Message[]): OpenAI.Chat.ChatCompletionMessageParam[] {
    return messages.map(m => ({
      role: (m.role === 'verdict' ? 'assistant' : m.role) as 'user' | 'assistant' | 'system',
      content: m.content,
    }))
  }
}
