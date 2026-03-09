import { GoogleGenerativeAI, HarmCategory, HarmBlockThreshold, Content, Part } from '@google/generative-ai'
import { Message } from '../../../../src/lib/types'
import { LLMAdapter, StreamChunk, AdapterConfig, MODEL_CONTEXT_WINDOWS } from './base.adapter'

/**
 * Google Gemini 适配器
 * 支持 Gemini 3 Pro Preview, Gemini 3 Flash Preview 等模型
 */
export class GeminiAdapter extends LLMAdapter {
  readonly provider = 'google' as const
  readonly name = 'Google'
  readonly defaultBaseUrl = 'https://generativelanguage.googleapis.com'

  /**
   * 测试连接
   */
  async testConnection(config: AdapterConfig): Promise<{ ok: boolean; error?: string }> {
    try {
      const genAI = new GoogleGenerativeAI(config.apiKey)
      const requestOptions = config.baseUrl ? { baseUrl: config.baseUrl } : undefined
      const model = genAI.getGenerativeModel({ model: config.model }, requestOptions)
      await model.generateContent('Hi')
      return { ok: true }
    } catch (error) {
      const errStr = String(error)
      if (errStr.includes('API_KEY_INVALID')) {
        return { ok: false, error: 'API Key 无效' }
      } else if (errStr.includes('PERMISSION_DENIED')) {
        return { ok: false, error: '无权访问该模型' }
      } else if (errStr.includes('RESOURCE_EXHAUSTED') || errStr.includes('QUOTA_EXCEEDED')) {
        return { ok: false, error: '配额已用尽或请求过于频繁' }
      } else if (errStr.includes('NOT_FOUND') || errStr.includes('not found')) {
        return { ok: false, error: `模型 "${config.model}" 不存在，请检查模型ID` }
      }
      return { ok: false, error: `连接失败: ${errStr}` }
    }
  }

  async *stream(messages: Message[], config: AdapterConfig): AsyncGenerator<StreamChunk> {
    const genAI = new GoogleGenerativeAI(config.apiKey)
    // 支持自定义 Base URL（代理）
    const requestOptions = config.baseUrl ? { baseUrl: config.baseUrl } : undefined

    try {
      // 分离系统消息和对话消息
      const systemMessages = messages.filter(m => m.role === 'system')
      const chatMessages = messages.filter(m => m.role !== 'system')

      // 构建系统指令（Gemini 要求 Content 格式）
      const systemText = systemMessages.map(m => m.content).join('\n\n')
      
      const modelConfig: any = {
        model: config.model,
        safetySettings: [
          { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_NONE },
          { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_NONE },
          { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_NONE },
          { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_NONE },
        ],
      }

      // systemInstruction 必须是 Content 格式
      if (systemText) {
        modelConfig.systemInstruction = {
          role: 'user' as const,
          parts: [{ text: systemText }] as Part[],
        }
      }

      const model = genAI.getGenerativeModel(modelConfig, requestOptions)

      // 构建请求选项（含 AbortSignal）
      const streamRequestOptions = config.signal 
        ? { signal: config.signal as AbortSignal } 
        : undefined

      // 如果只有一条用户消息，直接用 generateContentStream
      if (chatMessages.length === 1) {
        const result = await model.generateContentStream(
          chatMessages[0].content,
          streamRequestOptions
        )
        
        let totalContent = ''
        let inputTokens = 0
        let outputTokens = 0

        for await (const chunk of result.stream) {
          if (config.signal?.aborted) {
            yield { content: '', done: true, error: '生成已停止' }
            return
          }

          const text = chunk.text()
          totalContent += text

          if (chunk.usageMetadata) {
            inputTokens = chunk.usageMetadata.promptTokenCount || 0
            outputTokens = chunk.usageMetadata.candidatesTokenCount || 0
          }

          yield { content: text, done: false }
        }

        yield {
          content: '',
          done: true,
          usage: {
            inputTokens: inputTokens || this.estimateTokens(messages.map(m => m.content).join('')),
            outputTokens: outputTokens || this.estimateTokens(totalContent),
          },
        }
        return
      }

      // 多轮对话：用 startChat
      const history: Content[] = chatMessages.slice(0, -1).map(m => ({
        role: m.role === 'user' ? 'user' : 'model',
        parts: [{ text: m.content }],
      }))

      // 确保 history 第一条是 user（Gemini 要求）
      if (history.length > 0 && history[0].role !== 'user') {
        history.unshift({
          role: 'user',
          parts: [{ text: '请继续。' }],
        })
      }

      // 确保 history 中 user 和 model 交替出现
      const fixedHistory = this.fixHistory(history)

      const chat = model.startChat({
        history: fixedHistory,
        generationConfig: {
          maxOutputTokens: 8192,
        },
      })

      const lastMessage = chatMessages[chatMessages.length - 1]
      const result = await chat.sendMessageStream(
        lastMessage?.content || '请回答上面的问题。',
        streamRequestOptions
      )

      let totalContent = ''
      let inputTokens = 0
      let outputTokens = 0

      for await (const chunk of result.stream) {
        if (config.signal?.aborted) {
          yield { content: '', done: true, error: '生成已停止' }
          return
        }

        const text = chunk.text()
        totalContent += text

        if (chunk.usageMetadata) {
          inputTokens = chunk.usageMetadata.promptTokenCount || 0
          outputTokens = chunk.usageMetadata.candidatesTokenCount || 0
        }

        yield { content: text, done: false }
      }

      yield {
        content: '',
        done: true,
        usage: {
          inputTokens: inputTokens || this.estimateTokens(messages.map(m => m.content).join('')),
          outputTokens: outputTokens || this.estimateTokens(totalContent),
        },
      }

    } catch (error) {
      let errorMessage = String(error)
      
      if (errorMessage.includes('API_KEY_INVALID')) {
        errorMessage = 'API Key 无效'
      } else if (errorMessage.includes('QUOTA_EXCEEDED') || errorMessage.includes('RESOURCE_EXHAUSTED')) {
        errorMessage = '配额已用尽或请求过于频繁'
      } else if (errorMessage.includes('PERMISSION_DENIED')) {
        errorMessage = '无权访问该模型'
      } else if (errorMessage.includes('NOT_FOUND') || errorMessage.includes('not found')) {
        errorMessage = `模型 "${config.model}" 不存在`
      }
      
      console.error('[Gemini] 流式请求失败:', errorMessage)
      yield { content: '', done: true, error: errorMessage }
    }
  }

  getContextWindow(model: string): number {
    return MODEL_CONTEXT_WINDOWS[model] || MODEL_CONTEXT_WINDOWS['default']
  }

  /**
   * 修复对话历史，确保 user/model 交替出现
   */
  private fixHistory(history: Content[]): Content[] {
    if (history.length === 0) return []
    
    const fixed: Content[] = []
    for (let i = 0; i < history.length; i++) {
      const current = history[i]
      const prev = fixed[fixed.length - 1]
      
      // 如果连续两条相同角色，合并
      if (prev && prev.role === current.role) {
        const prevText = prev.parts.map((p: any) => p.text || '').join('\n')
        const currText = current.parts.map((p: any) => p.text || '').join('\n')
        prev.parts = [{ text: prevText + '\n\n' + currText }]
      } else {
        fixed.push({ ...current })
      }
    }
    
    return fixed
  }
}
