import OpenAI from 'openai'
import type { Message } from '../types'
import {
  LLMAdapter,
  type StreamChunkPayload,
  type AdapterConfig,
  MODEL_CONTEXT_WINDOWS,
} from './base.adapter'

export class OpenAIAdapter extends LLMAdapter {
  readonly provider = 'openai' as const
  readonly name = 'OpenAI'
  readonly defaultBaseUrl = (() => {
    const hubUrl = process.env.AI_PROVIDER_HUB_URL?.replace(/\/$/, '')
    if (hubUrl) return hubUrl.endsWith('/v1') ? hubUrl : `${hubUrl}/v1`
    return `${(process.env.OMNI_API_BASE_URL || 'http://localhost').replace(/\/$/, '')}/v1`
  })()

  private isLocalHub(baseUrl: string): boolean {
    return (
      baseUrl.includes('localhost:8001') ||
      baseUrl.includes('127.0.0.1:8001') ||
      baseUrl.includes('ai-provider-hub:8001') ||
      baseUrl.endsWith('/v1')
    )
  }

  async testConnection(config: AdapterConfig): Promise<{ ok: boolean; error?: string }> {
    const baseUrl = config.baseUrl || this.defaultBaseUrl
    const apiKey = config.apiKey || 'local-dev-token'
    try {
      const client = new OpenAI({
        apiKey,
        baseURL: baseUrl,
        dangerouslyAllowBrowser: false,
        timeout: 15000,
      })

      // ai-provider-hub currently does not expose /v1/models, use lightweight chat probe.
      if (this.isLocalHub(baseUrl)) {
        await client.chat.completions.create({
          model: config.model,
          messages: [{ role: 'user', content: 'ping' }],
          stream: false,
        })
        return { ok: true }
      }

      const models = await client.models.list()
      for await (const model of models) {
        if (model.id === config.model) return { ok: true }
      }
      return { ok: true }
    } catch (error) {
      if (error instanceof OpenAI.APIError) {
        if (error.status === 401) return { ok: false, error: 'API Key 无效，请检查是否正确' }
        if (error.status === 403) return { ok: false, error: '无权访问，请检查 API Key 权限' }
        if (error.status === 429)
          return { ok: false, error: '请求频率超限或额度不足，请到 OpenAI 后台检查用量和账单' }
        return { ok: false, error: `OpenAI 错误 (${error.status}): ${error.message}` }
      }
      return { ok: false, error: `连接失败: ${String(error)}` }
    }
  }

  async *stream(
    messages: Message[],
    config: AdapterConfig
  ): AsyncGenerator<StreamChunkPayload> {
    const baseUrl = config.baseUrl || this.defaultBaseUrl
    const apiKey = config.apiKey || 'local-dev-token'
    const client = new OpenAI({
      apiKey,
      baseURL: baseUrl,
      dangerouslyAllowBrowser: false,
    })

    try {
      const formattedMessages = this.formatMessages(
        messages
      ) as OpenAI.Chat.ChatCompletionMessageParam[]

      const stream = await client.chat.completions.create(
        {
          model: config.model,
          messages: formattedMessages,
          stream: true,
          stream_options: { include_usage: true },
        },
        { signal: config.signal }
      )

      let totalContent = ''
      let usage: { inputTokens: number; outputTokens: number } | undefined

      for await (const chunk of stream) {
        if (config.signal?.aborted) {
          yield { content: '', done: true, error: '生成已停止' }
          return
        }

        const delta = chunk.choices[0]?.delta?.content || ''
        totalContent += delta

        if (chunk.usage) {
          usage = {
            inputTokens: chunk.usage.prompt_tokens,
            outputTokens: chunk.usage.completion_tokens,
          }
        }

        const finishReason = chunk.choices[0]?.finish_reason
        const done = finishReason !== null && finishReason !== undefined

        yield {
          content: delta,
          done,
          usage: done ? usage : undefined,
        }
      }

      if (!usage) {
        usage = {
          inputTokens: this.estimateTokens(messages.map((m) => m.content).join('')),
          outputTokens: this.estimateTokens(totalContent),
        }
      }
    } catch (error) {
      if (error instanceof OpenAI.APIError) {
        let errorMessage = error.message
        if (error.status === 401) errorMessage = 'API Key 无效'
        else if (error.status === 403) errorMessage = '无权访问该模型'
        else if (error.status === 429)
          errorMessage = '请求频率超限或额度不足，请到 platform.openai.com 检查账单和用量'
        else if (error.status === 500) errorMessage = 'OpenAI 服务器错误'
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
    return messages.map((m) => ({
      role: (m.role === 'verdict' ? 'assistant' : m.role) as 'user' | 'assistant' | 'system',
      content: m.content,
    }))
  }
}
