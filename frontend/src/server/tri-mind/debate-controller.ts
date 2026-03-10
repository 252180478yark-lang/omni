import { v4 as uuidv4 } from 'uuid'
import type {
  DebateParams,
  ModelConfig,
  RoundHistory,
  StreamChunk,
  DebateEvent,
  TokenUsage,
  ChatNode,
  StreamWriter,
} from './types'
import { adapterManager } from './adapters'
import { promptFactory } from './prompt-factory'
import { tokenBudgetManager } from './token-budget'
import { storage } from './storage'

/**
 * 辩论控制器
 *
 * 负责：
 * 1. 并发调用多个模型
 * 2. 管理 AbortController
 * 3. 协调多轮辩论流程
 * 4. 通过 StreamWriter 推送流式数据（SSE/ReadableStream）
 */
export class DebateController {
  private abortControllers = new Map<string, AbortController>()

  private allowEmptyApiKey(provider: string, baseUrl?: string): boolean {
    if (provider !== 'openai') return false
    if (!baseUrl) return false
    const normalized = baseUrl.replace(/\/$/, '')
    const omniBase = (process.env.OMNI_API_BASE_URL || '').replace(/\/$/, '')
    return (
      normalized.includes('localhost:8001') ||
      normalized.includes('127.0.0.1:8001') ||
      normalized.includes('ai-provider-hub:8001') ||
      (omniBase.length > 0 && normalized === `${omniBase}/v1`)
    )
  }

  /**
   * 运行辩论
   * @param params 辩论参数（apiKeys 必须从 params 传入，不再调用 getApiKey）
   * @param streamWriter 可选的流式写入器，用于推送 chunk 和 event 到 SSE/ReadableStream
   */
  async runDebate(
    params: DebateParams,
    streamWriter?: StreamWriter
  ): Promise<void> {
    const {
      sessionId,
      query,
      models,
      rounds,
      files,
      intervention,
      reportDetailLevel,
    } = params
    const apiKeys = params.apiKeys || {}

    const abortController = new AbortController()
    this.abortControllers.set(sessionId, abortController)

    const history: RoundHistory[] = []

    const sendChunk = (chunk: Omit<StreamChunk, 'sessionId'>) => {
      streamWriter?.onChunk?.({ ...chunk, sessionId })
    }

    const sendEvent = (event: DebateEvent) => {
      streamWriter?.onEvent?.(event)
    }

    try {
      // 持久化用户消息节点（使用内存存储）
      try {
        const userNode: ChatNode = {
          id: uuidv4(),
          sessionId,
          parentId: null,
          role: 'user',
          content: query,
          round: 0,
          createdAt: Date.now(),
        }
        storage.addNode(userNode)
        storage.updateSession(sessionId, {
          title: query.slice(0, 30) + (query.length > 30 ? '...' : ''),
        })
      } catch (e) {
        console.warn('持久化用户消息失败:', e)
      }

      for (let round = 1; round <= rounds; round++) {
        console.log(`开始第 ${round}/${rounds} 轮辩论`)

        if (abortController.signal.aborted) {
          console.log('辩论已被用户中断')
          break
        }

        const prompts = promptFactory.buildRoundPrompts(models, {
          round,
          originalQuery: query,
          previousRounds: history,
          fileContext: files,
          userIntervention: intervention,
        })

        const roundResponses = await this.runRound(
          sessionId,
          models,
          prompts,
          apiKeys,
          abortController.signal,
          sendChunk
        )

        history.push({ round, responses: roundResponses })

        try {
          roundResponses.forEach((content, modelId) => {
            if (content) {
              const usage = this._lastRoundUsage.get(modelId)
              const assistantNode: ChatNode = {
                id: uuidv4(),
                sessionId,
                parentId: null,
                role: 'assistant',
                modelId,
                content,
                round,
                tokenInput: usage?.inputTokens,
                tokenOutput: usage?.outputTokens,
                createdAt: Date.now(),
              }
              storage.addNode(assistantNode)
            }
          })
        } catch (e) {
          console.warn('持久化模型响应失败:', e)
        }

        sendEvent({ type: 'round-complete', sessionId, round })

        if (round < rounds) {
          console.log(`等待 3 秒后开始第 ${round + 1} 轮...`)
          await new Promise((resolve) => setTimeout(resolve, 3000))
        }

        if (abortController.signal.aborted) {
          console.log('辩论在轮次间隔中被中断')
          break
        }

        if (round < rounds) {
          for (const model of models) {
            if (tokenBudgetManager.needsCompression(history, model)) {
              console.log(`模型 ${model.name} 需要压缩历史`)
              const compressed = await tokenBudgetManager.compressHistory(
                history,
                model
              )
              history.length = 0
              history.push(...compressed)
              break
            }
          }
        }
      }

      if (!abortController.signal.aborted && history.length > 0) {
        await this.generateVerdict(
          sessionId,
          query,
          models,
          history,
          files,
          apiKeys,
          abortController.signal,
          reportDetailLevel || 'standard',
          sendChunk
        )
      }

      sendEvent({ type: 'debate-complete', sessionId })
    } catch (error) {
      console.error('辩论过程出错:', error)
      sendEvent({
        type: 'error',
        sessionId,
        error: String(error),
      })
    } finally {
      this.abortControllers.delete(sessionId)
    }
  }

  private async runRound(
    sessionId: string,
    models: ModelConfig[],
    prompts: Map<string, import('./types').Message[]>,
    apiKeys: Record<string, string>,
    signal: AbortSignal,
    sendChunk: (chunk: Omit<StreamChunk, 'sessionId'>) => void
  ): Promise<Map<string, string>> {
    const responses = new Map<string, string>()
    const responseBuffers = new Map<string, string>()
    const responseUsage = new Map<string, TokenUsage>()

    const streamPromises = models.map(async (model) => {
      console.log(
        `[辩论] 准备调用模型: ${model.name} (${model.id}), provider=${model.provider}, modelId=${model.modelId}`
      )

      const adapter = adapterManager.get(model.provider)
      if (!adapter) {
        const err = `未找到适配器: ${model.provider}`
        console.error(`[辩论] ${err}`)
        sendChunk({ modelId: model.id, content: '', done: true, error: err })
        return
      }

      const messages = prompts.get(model.id)
      if (!messages) {
        const err = `未找到 Prompt: ${model.id}, 可用keys: ${Array.from(prompts.keys()).join(', ')}`
        console.error(`[辩论] ${err}`)
        sendChunk({ modelId: model.id, content: '', done: true, error: err })
        return
      }

      const apiKey = apiKeys[model.provider] || ''
      console.log(
        `[辩论] ${model.name} API Key: ${apiKey ? apiKey.substring(0, 10) + '...' : '(空)'}`
      )

      if (!apiKey && model.provider !== 'ollama' && !this.allowEmptyApiKey(model.provider, model.baseUrl)) {
        const err = `${model.name} 的 API Key 未设置，请在参数中传入 apiKeys`
        console.error(`[辩论] ${err}`)
        sendChunk({ modelId: model.id, content: '', done: true, error: err })
        return
      }

      try {
        let buffer = ''
        console.log(
          `[辩论] 开始流式请求: ${model.name}, 消息数=${messages.length}, baseUrl=${model.baseUrl || '默认'}`
        )

        const generator = adapter.stream(messages, {
          apiKey,
          baseUrl: model.baseUrl,
          model: model.modelId,
          signal,
        })

        let chunkCount = 0
        for await (const chunk of generator) {
          if (signal.aborted) {
            console.log(`[辩论] ${model.name} 被中断`)
            break
          }

          chunkCount++
          buffer += chunk.content
          responseBuffers.set(model.id, buffer)

          sendChunk({
            modelId: model.id,
            content: chunk.content,
            done: chunk.done,
            usage: chunk.usage,
            error: chunk.error,
          })

          if (chunk.error) {
            console.error(`[辩论] ${model.name} 返回错误: ${chunk.error}`)
          }

          if (chunk.done) {
            console.log(
              `[辩论] ${model.name} 完成, chunks=${chunkCount}, 内容长度=${buffer.length}`
            )
            responses.set(model.id, buffer)
            if (chunk.usage) {
              responseUsage.set(model.id, chunk.usage)
            }
          }
        }

        if (chunkCount === 0) {
          console.warn(`[辩论] ${model.name} 没有返回任何数据`)
        }
      } catch (error) {
        console.error(`[辩论] 模型 ${model.name} 调用异常:`, error)
        sendChunk({
          modelId: model.id,
          content: '',
          done: true,
          error: `调用失败: ${String(error)}`,
        })
      }
    })

    await Promise.allSettled(streamPromises)
    this._lastRoundUsage = responseUsage

    return responses
  }

  private _lastRoundUsage = new Map<string, TokenUsage>()

  private async generateVerdict(
    sessionId: string,
    query: string,
    models: ModelConfig[],
    history: RoundHistory[],
    files: import('./types').FileAttachment[] | undefined,
    apiKeys: Record<string, string>,
    signal: AbortSignal,
    reportDetailLevel: import('./types').ReportDetailLevel,
    sendChunk: (chunk: Omit<StreamChunk, 'sessionId'>) => void
  ): Promise<void> {
    const judge = models.reduce((prev, curr) =>
      curr.contextWindow > prev.contextWindow ? curr : prev
    )

    console.log(`使用 ${judge.name} 作为裁判生成最终裁决`)

    const adapter = adapterManager.get(judge.provider)
    if (!adapter) {
      console.error(`未找到裁判适配器: ${judge.provider}`)
      return
    }

    const verdictPrompt = promptFactory.buildVerdictPrompt({
      originalQuery: query,
      previousRounds: history,
      fileContext: files,
      reportDetailLevel,
    })

    const apiKey = apiKeys[judge.provider] || ''

    try {
      const generator = adapter.stream(verdictPrompt, {
        apiKey,
        baseUrl: judge.baseUrl,
        model: judge.modelId,
        signal,
      })

      let verdictBuffer = ''
      let verdictUsage: TokenUsage | undefined

      for await (const chunk of generator) {
        if (signal.aborted) break

        verdictBuffer += chunk.content
        if (chunk.usage) verdictUsage = chunk.usage

        sendChunk({
          modelId: '__verdict__',
          content: chunk.content,
          done: chunk.done,
          usage: chunk.usage,
          error: chunk.error,
        })
      }

      try {
        if (verdictBuffer) {
          const verdictNode: ChatNode = {
            id: uuidv4(),
            sessionId,
            parentId: null,
            role: 'verdict',
            modelId: judge.id,
            content: verdictBuffer,
            round: history.length + 1,
            tokenInput: verdictUsage?.inputTokens,
            tokenOutput: verdictUsage?.outputTokens,
            createdAt: Date.now(),
          }
          storage.addNode(verdictNode)
        }
      } catch (e) {
        console.warn('持久化裁决内容失败:', e)
      }
    } catch (error) {
      console.error('生成裁决失败:', error)
      sendChunk({
        modelId: '__verdict__',
        content: '',
        done: true,
        error: String(error),
      })
    }
  }

  stopGeneration(sessionId: string): void {
    const controller = this.abortControllers.get(sessionId)
    if (controller) {
      console.log('停止生成:', sessionId)
      controller.abort()
      this.abortControllers.delete(sessionId)
    }
  }
}

export const debateController = new DebateController()
